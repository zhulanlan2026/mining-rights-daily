from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from datetime import date
from urllib.parse import parse_qs, urlsplit

Producer = Callable[[str, date, str], AsyncIterator[dict[str, str]]]


def format_sse(event: str, data: str) -> str:
    body = "".join(f"data: {line}\n" for line in (data.split("\n") or [""]))
    return f"event: {event}\n{body}\n"


async def start_sse(host: str, port: int, producer: Producer) -> asyncio.Server:
    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            raw = await reader.readuntil(b"\r\n\r\n")
        except (asyncio.IncompleteReadError, ConnectionError):
            writer.close()
            return
        line = raw.decode("latin1").split("\r\n", 1)[0]
        parts = line.split(" ")
        if len(parts) < 2 or parts[0] != "GET":
            await _http(writer, 404, "not found")
            return
        parsed = urlsplit(parts[1])
        if parsed.path == "/healthz":
            await _http(writer, 200, "ok")
            return
        if parsed.path != "/v1/briefing":
            await _http(writer, 404, "not found")
            return
        query_map = parse_qs(parsed.query)
        query = (query_map.get("query") or [""])[0].strip()
        if not query:
            await _http(writer, 400, "query required")
            return
        thread_id = (query_map.get("thread_id") or ["default"])[0] or "default"
        as_of_raw = (query_map.get("as_of") or [None])[0]
        try:
            as_of = date.fromisoformat(as_of_raw) if as_of_raw else date.today()
        except ValueError:
            await _http(writer, 400, "bad as_of")
            return
        writer.write(
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: text/event-stream; charset=utf-8\r\n"
            b"Cache-Control: no-cache\r\n"
            b"Connection: close\r\n\r\n"
        )
        await writer.drain()
        async for event in producer(query, as_of, thread_id):
            name = event.get("event") or "message"
            data = event.get("markdown") or event.get("node") or ""
            writer.write(format_sse(name, data).encode("utf-8"))
            await writer.drain()
        writer.close()
        await writer.wait_closed()

    return await asyncio.start_server(handle, host, port)


async def serve_forever(server: asyncio.Server) -> None:
    async with server:
        await server.serve_forever()


async def _http(writer: asyncio.StreamWriter, status: int, body: str) -> None:
    payload = body.encode("utf-8")
    reason = {200: "OK", 400: "Bad Request", 404: "Not Found"}.get(status, "Error")
    writer.write(
        f"HTTP/1.1 {status} {reason}\r\nContent-Type: text/plain; charset=utf-8\r\n"
        f"Content-Length: {len(payload)}\r\nConnection: close\r\n\r\n".encode("ascii")
        + payload
    )
    await writer.drain()
    writer.close()
    await writer.wait_closed()


def briefing_producer(
    transport: str,
    urls: dict[str, str],
    checkpoint,
) -> Producer:
    async def produce(query: str, as_of: date, thread_id: str) -> AsyncIterator[dict[str, str]]:
        from mining_rights_daily.agent.bus import open_bus
        from mining_rights_daily.agent.graph.run import stream_turn

        async with open_bus(transport, urls) as bus:
            async for event in stream_turn(query, as_of, bus, checkpoint, thread_id):
                yield event

    return produce
