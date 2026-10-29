"""HTTP fetch with a small public-host check.

The check blocks obvious local and non-routable targets. It does not resolve DNS,
so a public name that later points at an internal address is still possible.
"""

from __future__ import annotations

import ipaddress

import httpx

from mining_rights_daily.errors import DomainError

USER_AGENT = "mining-rights-daily/0.1"
_BLOCKED_HOSTS = {
    "localhost",
    "localhost.localdomain",
    "0.0.0.0",
    "127.0.0.1",
    "::1",
    "metadata.google.internal",
}


def assert_public_http(url: str) -> str:
    parsed = httpx.URL(url)
    if parsed.scheme not in {"http", "https"}:
        raise DomainError("只接受 http 或 https 链接")
    if parsed.username or parsed.password:
        raise DomainError("拒绝带账号口令的链接")
    host = (parsed.host or "").lower().rstrip(".")
    if not host or host in _BLOCKED_HOSTS or host.endswith(".local") or host.endswith(".internal"):
        raise DomainError(f"拒绝访问内部主机: {host or url}")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
    ):
        raise DomainError(f"拒绝访问非公网地址: {host}")
    return str(parsed)


def _guard_redirect(response: httpx.Response) -> None:
    assert_public_http(str(response.url))


def open_client(timeout: float, headers: dict[str, str] | None = None) -> httpx.Client:
    merged = {"User-Agent": USER_AGENT}
    if headers:
        merged.update(headers)
    return httpx.Client(
        timeout=timeout,
        follow_redirects=True,
        headers=merged,
        event_hooks={"response": [_guard_redirect]},
    )


def fetch_limited(
    url: str,
    *,
    timeout: float,
    max_bytes: int,
    headers: dict[str, str] | None = None,
) -> tuple[bytes, str]:
    assert_public_http(url)
    try:
        with open_client(timeout, headers) as client:
            with client.stream("GET", url) as response:
                response.raise_for_status()
                content_type = response.headers.get("content-type", "")
                chunks: list[bytes] = []
                total = 0
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > max_bytes:
                        raise DomainError(f"响应超过 {max_bytes} 字节，已中止")
                    chunks.append(chunk)
                final_url = str(response.url)
    except DomainError:
        raise
    except httpx.HTTPStatusError as exc:
        raise DomainError(f"下载失败: HTTP {exc.response.status_code}") from exc
    except httpx.HTTPError as exc:
        raise DomainError(f"下载失败: {exc.__class__.__name__}") from exc
    return b"".join(chunks), f"{final_url} ({content_type})".strip()


def iter_text_preview(text: str, limit: int = 8000) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "…"
