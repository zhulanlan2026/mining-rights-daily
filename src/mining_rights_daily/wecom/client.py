from __future__ import annotations

import logging
import re
import time
from typing import Any

import httpx

from mining_rights_daily.wecom.messages import split_markdown

_SECRET = re.compile(r"(corpsecret=)[^&\s]+")
_TOKEN = re.compile(r"(access_token=)[^&\s]+")


class WeComApiError(Exception):
    """Enterprise WeChat rejected a send or token request."""


class RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact_secrets(record.getMessage())
        record.args = ()
        return True


def redact_secrets(text: str) -> str:
    text = _SECRET.sub(r"\1***", text)
    return _TOKEN.sub(r"\1***", text)


def install_redaction() -> None:
    redactor = RedactFilter()
    for name in ("httpx", "httpcore"):
        logger = logging.getLogger(name)
        if not any(isinstance(item, RedactFilter) for item in logger.filters):
            logger.addFilter(redactor)


class WeComClient:
    def __init__(
        self,
        corp_id: str,
        secret: str,
        agent_id: int,
        *,
        base_url: str = "https://qyapi.weixin.qq.com/cgi-bin",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        install_redaction()
        self.corp_id = corp_id
        self.secret = secret
        self.agent_id = agent_id
        self.base_url = base_url.rstrip("/")
        self.transport = transport
        self._access_token = ""
        self._expires_at = 0.0

    async def send_text(self, user_id: str, content: str) -> None:
        await self._send(user_id, "text", {"content": content})

    async def send_markdown(self, user_id: str, content: str) -> None:
        for part in split_markdown(content):
            await self._send(user_id, "markdown", {"content": part})

    async def _send(self, user_id: str, msg_type: str, body: dict[str, str]) -> None:
        token = await self._token()
        payload: dict[str, Any] = {
            "touser": user_id,
            "msgtype": msg_type,
            "agentid": self.agent_id,
            msg_type: body,
        }
        async with httpx.AsyncClient(transport=self.transport, timeout=20) as client:
            response = await client.post(
                f"{self.base_url}/message/send",
                params={"access_token": token},
                json=payload,
            )
        self._raise_for_status(response)

    async def _token(self) -> str:
        if self._access_token and time.monotonic() < self._expires_at:
            return self._access_token
        async with httpx.AsyncClient(transport=self.transport, timeout=20) as client:
            response = await client.get(
                f"{self.base_url}/gettoken",
                params={"corpid": self.corp_id, "corpsecret": self.secret},
            )
        data = self._raise_for_status(response)
        token = str(data.get("access_token") or "")
        if not token:
            raise WeComApiError("企业微信没有返回 access_token")
        expires = int(data.get("expires_in") or 7200)
        self._access_token = token
        self._expires_at = time.monotonic() + max(expires - 60, 30)
        return token

    def _raise_for_status(self, response: httpx.Response) -> dict[str, Any]:
        try:
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise WeComApiError("企业微信接口失败") from exc
        if not isinstance(data, dict):
            raise WeComApiError("企业微信接口失败")
        if int(data.get("errcode") or 0) != 0:
            raise WeComApiError(f"企业微信接口失败：{data.get('errcode')}")
        return data
