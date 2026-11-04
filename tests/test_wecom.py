from __future__ import annotations

import asyncio
import base64
import json
import logging
from urllib.parse import urlencode

import httpx

from mining_rights_daily.wecom.app import WeComCallback
from mining_rights_daily.wecom.bridge import answer_user
from mining_rights_daily.wecom.client import WeComClient, redact_secrets
from mining_rights_daily.wecom.config import WeComSettings
from mining_rights_daily.wecom.crypto import decrypt, encrypt, sign
from mining_rights_daily.wecom.messages import parse_query, split_markdown
from mining_rights_daily.wecom.server import start_wecom

CORP = "wwtest"
TOKEN = "tokentoken"
AES_KEY = base64.b64encode(b"0123456789abcdef0123456789abcdef").decode().rstrip("=")
SETTINGS = WeComSettings(
    corp_id=CORP,
    agent_id=1,
    secret="secret",
    token=TOKEN,
    encoding_aes_key=AES_KEY,
)


def test_encrypt_roundtrip_and_query_plus() -> None:
    encrypted = encrypt(AES_KEY, "生成简报", CORP)
    assert decrypt(AES_KEY, encrypted, CORP) == "生成简报"
    assert parse_query("echostr=ab+cd%2Fef")["echostr"] == "ab+cd/ef"


def test_markdown_is_split_under_wecom_limit() -> None:
    parts = split_markdown("甲" * 2000)
    assert len(parts) > 1
    assert all(len(part.encode()) <= 2000 for part in parts)
    assert "".join(part.split("\n", 1)[1] for part in parts) == "甲" * 2000


def test_secrets_are_redacted_before_logs() -> None:
    raw = "https://qyapi.weixin.qq.com/gettoken?corpid=ww&corpsecret=supersecret&access_token=zzz"
    assert "supersecret" not in redact_secrets(raw)
    assert "access_token=***" in redact_secrets(raw)


def test_callback_verifies_url_and_accepts_text_without_waiting() -> None:
    seen: list[tuple[str, str]] = []
    release = asyncio.Event()
    started = asyncio.Event()

    async def on_text(user_id: str, content: str, msg_id: str) -> None:
        del msg_id
        seen.append((user_id, content))
        started.set()
        await release.wait()

    app = WeComCallback(SETTINGS, on_text)

    async def scenario() -> None:
        echo = encrypt(AES_KEY, "ping", CORP)
        verified = await app.handle(
            "GET",
            _target(echo),
            b"",
        )
        assert verified[0] == 200
        assert verified[2] == b"ping"

        message = _text_xml("zhangsan", "生成简报", "1001")
        encrypted = encrypt(AES_KEY, message, CORP)
        pending = asyncio.create_task(app.handle("POST", _target(encrypted), _envelope(encrypted)))
        await asyncio.wait_for(started.wait(), 1)
        status, _kind, body = await asyncio.wait_for(pending, 1)
        assert status == 200
        assert body == b"success"
        release.set()
        await app.drain()
        duplicate = await app.handle("POST", _target(encrypted), _envelope(encrypted))
        assert duplicate[2] == b"success"

    asyncio.run(scenario())
    assert seen == [("zhangsan", "生成简报")]


def test_plain_xml_is_accepted_when_signature_matches() -> None:
    async def scenario() -> None:
        seen: list[str] = []

        async def on_text(user_id: str, content: str, msg_id: str) -> None:
            del user_id, msg_id
            seen.append(content)

        app = WeComCallback(SETTINGS, on_text)
        xml = _text_xml("lisi", "查锂价", "2002").encode()
        signature = sign(TOKEN, "10", "11", None)
        target = "/wecom/callback?msg_signature=" + signature + "&timestamp=10&nonce=11"
        status, _kind, body = await app.handle("POST", target, xml)
        await app.drain()
        assert status == 200
        assert body == b"success"
        assert seen == ["查锂价"]

    asyncio.run(scenario())


def test_answer_sends_progress_then_markdown() -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.texts: list[str] = []
            self.markdown: list[str] = []

        async def send_text(self, user_id: str, content: str) -> None:
            assert user_id == "zhangsan"
            self.texts.append(content)

        async def send_markdown(self, user_id: str, content: str) -> None:
            self.markdown.append(content)

    async def run(user_id: str, content: str) -> str:
        assert user_id == "zhangsan"
        assert content == "生成简报"
        return "# 日报\n"

    async def fails(user_id: str, content: str) -> str:
        del user_id, content
        raise RuntimeError("价格工具超时")

    async def scenario() -> None:
        client = FakeClient()
        await answer_user(client, "zhangsan", "生成简报", run)
        assert client.texts == ["正在生成，请稍等。"]
        assert client.markdown == ["# 日报\n"]
        await answer_user(client, "zhangsan", "生成简报", fails)
        assert "生成失败" in client.texts[-1]

    asyncio.run(scenario())


def test_client_sends_markdown_and_reuses_token() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path.endswith("/gettoken"):
            assert request.url.params["corpsecret"] == "secret"
            return httpx.Response(200, json={"errcode": 0, "access_token": "tok", "expires_in": 7200})
        body = json.loads(request.content)
        assert body["touser"] == "zhangsan"
        assert body["agentid"] == 1
        assert body["markdown"]["content"] == "你好"
        assert request.url.params["access_token"] == "tok"
        return httpx.Response(200, json={"errcode": 0})

    async def scenario() -> None:
        client = WeComClient("ww", "secret", 1, transport=httpx.MockTransport(handler))
        await client.send_markdown("zhangsan", "你好")
        await client.send_markdown("zhangsan", "你好")

    asyncio.run(scenario())
    assert calls.count("/cgi-bin/gettoken") == 1
    assert calls.count("/cgi-bin/message/send") == 2


def test_http_callback_returns_echostr() -> None:
    async def on_text(user_id: str, content: str, msg_id: str) -> None:
        del user_id, content, msg_id

    async def scenario() -> None:
        callback = WeComCallback(SETTINGS, on_text)
        server = await start_wecom("127.0.0.1", 0, callback)
        sockets = server.sockets
        assert sockets is not None
        port = sockets[0].getsockname()[1]
        echo = encrypt(AES_KEY, "hello", CORP)
        query = urlencode(
            {"msg_signature": sign(TOKEN, "1", "2", echo), "timestamp": "1", "nonce": "2", "echostr": echo}
        )
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"http://127.0.0.1:{port}/wecom/callback?{query}")
        finally:
            server.close()
            await server.wait_closed()
        assert response.status_code == 200
        assert response.text == "hello"

    asyncio.run(scenario())


def test_missing_wecom_settings_names_the_variables(monkeypatch) -> None:
    for name in (
        "WECOM_CORP_ID",
        "WECOM_AGENT_ID",
        "WECOM_SECRET",
        "WECOM_TOKEN",
        "WECOM_ENCODING_AES_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    try:
        WeComSettings.from_env()
    except ValueError as exc:
        assert "WECOM_CORP_ID" in str(exc)
    else:
        raise AssertionError("expected missing settings")


def test_redact_filter_rewrites_log_records() -> None:
    from mining_rights_daily.wecom.client import RedactFilter

    record = logging.LogRecord(
        name="httpx",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="HTTP Request: %s",
        args=("https://qyapi.weixin.qq.com/gettoken?corpsecret=supersecret",),
        exc_info=None,
    )
    assert RedactFilter().filter(record) is True
    assert "supersecret" not in record.getMessage()


def _target(encrypted: str) -> str:
    signature = sign(TOKEN, "1", "2", encrypted)
    return f"/wecom/callback?msg_signature={signature}&timestamp=1&nonce=2&echostr={encrypted}"


def _envelope(encrypted: str) -> bytes:
    return (
        "<xml><ToUserName><![CDATA[wwtest]]></ToUserName>"
        f"<Encrypt><![CDATA[{encrypted}]]></Encrypt></xml>"
    ).encode()


def _text_xml(user_id: str, content: str, msg_id: str) -> str:
    return (
        "<xml>"
        f"<FromUserName><![CDATA[{user_id}]]></FromUserName>"
        "<MsgType><![CDATA[text]]></MsgType>"
        f"<Content><![CDATA[{content}]]></Content>"
        f"<MsgId>{msg_id}</MsgId>"
        "</xml>"
    )
