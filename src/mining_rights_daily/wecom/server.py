from __future__ import annotations

import asyncio

from mining_rights_daily.wecom.app import WeComCallback


async def start_wecom(host: str, port: int, callback: WeComCallback) -> asyncio.Server:
    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            request = await _read_request(reader)
        except (asyncio.IncompleteReadError, ConnectionError, ValueError):
            writer.close()
            return
        if request is None:
            writer.close()
            return
        method, target, body = request
        status, content_type, payload = await callback.handle(method, target, body)
        reason = {200: "OK", 400: "Bad Request", 401: "Unauthorized", 404: "Not Found"}.get(
            status, "Error"
        )
        writer.write(
            f"HTTP/1.1 {status} {reason}\r\nContent-Type: {content_type}\r\n"
            f"Content-Length: {len(payload)}\r\nConnection: close\r\n\r\n".encode("ascii")
            + payload
        )
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    return await asyncio.start_server(handle, host, port)


async def _read_request(reader: asyncio.StreamReader) -> tuple[str, str, bytes] | None:
    raw = await reader.readuntil(b"\r\n\r\n")
    head, _, rest = raw.partition(b"\r\n\r\n")
    lines = head.decode("latin1").split("\r\n")
    if not lines or " " not in lines[0]:
        return None
    method, target, _version = lines[0].split(" ", 2)
    length = 0
    for line in lines[1:]:
        name, _, value = line.partition(":")
        if name.lower() == "content-length":
            length = int(value.strip() or "0")
    body = rest
    if len(body) < length:
        body += await reader.readexactly(length - len(body))
    return method, target, body[:length]
