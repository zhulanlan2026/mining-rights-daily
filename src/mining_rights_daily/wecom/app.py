from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit

from mining_rights_daily.wecom.config import WeComSettings
from mining_rights_daily.wecom.crypto import WeComCryptoError, decrypt, sign, signatures_match
from mining_rights_daily.wecom.messages import encrypt_field, parse_inbound, parse_query

OnText = Callable[[str, str, str], Awaitable[None]]
_LOG = logging.getLogger("mining_rights_daily.wecom")


class WeComCallback:
    """Verify the callback URL and accept text messages without blocking the reply."""

    def __init__(self, settings: WeComSettings, on_text: OnText) -> None:
        self.settings = settings
        self.on_text = on_text
        self._seen: set[str] = set()
        self._tasks: set[asyncio.Task[None]] = set()

    async def handle(self, method: str, target: str, body: bytes) -> tuple[int, str, bytes]:
        parsed = urlsplit(target)
        if parsed.path == "/healthz":
            return 200, "text/plain; charset=utf-8", b"ok"
        if parsed.path != "/wecom/callback":
            return 404, "text/plain; charset=utf-8", b"not found"
        query = parse_query(parsed.query)
        if method == "GET":
            return self._verify(query)
        if method == "POST":
            return self._receive(query, body)
        return 404, "text/plain; charset=utf-8", b"not found"

    async def drain(self) -> None:
        if self._tasks:
            await asyncio.gather(*list(self._tasks))

    def _verify(self, query: dict[str, str]) -> tuple[int, str, bytes]:
        echo = query.get("echostr") or ""
        if not echo or not self._signed(query, echo):
            return 401, "text/plain; charset=utf-8", b"invalid signature"
        try:
            plain = decrypt(self.settings.encoding_aes_key, echo, self.settings.corp_id)
        except WeComCryptoError:
            return 401, "text/plain; charset=utf-8", b"invalid signature"
        return 200, "text/plain; charset=utf-8", plain.encode()

    def _receive(self, query: dict[str, str], body: bytes) -> tuple[int, str, bytes]:
        try:
            xml_text = body.decode("utf-8")
            encrypted = encrypt_field(xml_text)
        except ValueError:
            return 400, "text/plain; charset=utf-8", b"bad xml"
        if not self._signed(query, encrypted):
            return 401, "text/plain; charset=utf-8", b"invalid signature"
        if encrypted is not None:
            try:
                xml_text = decrypt(self.settings.encoding_aes_key, encrypted, self.settings.corp_id)
            except WeComCryptoError:
                return 401, "text/plain; charset=utf-8", b"invalid signature"
        try:
            inbound = parse_inbound(xml_text)
        except ValueError:
            return 400, "text/plain; charset=utf-8", b"bad xml"
        if inbound.msg_type == "text" and inbound.content and inbound.user_id:
            if inbound.msg_id and inbound.msg_id in self._seen:
                return 200, "text/plain; charset=utf-8", b"success"
            if inbound.msg_id:
                self._remember(inbound.msg_id)
            _LOG.info("text from %s (%s chars)", inbound.user_id, len(inbound.content))
            task = asyncio.create_task(self._safe_text(inbound.user_id, inbound.content, inbound.msg_id))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
        return 200, "text/plain; charset=utf-8", b"success"

    def _signed(self, query: dict[str, str], encrypt: str | None) -> bool:
        timestamp = query.get("timestamp") or ""
        nonce = query.get("nonce") or ""
        actual = query.get("msg_signature") or ""
        if not timestamp or not nonce or not actual:
            return False
        expected = sign(self.settings.token, timestamp, nonce, encrypt)
        return signatures_match(expected, actual)

    def _remember(self, msg_id: str) -> None:
        self._seen.add(msg_id)
        if len(self._seen) > 1000:
            self._seen.clear()
            self._seen.add(msg_id)

    async def _safe_text(self, user_id: str, content: str, msg_id: str) -> None:
        try:
            await self.on_text(user_id, content, msg_id)
        except Exception:
            _LOG.exception("wecom reply failed for %s", user_id)
