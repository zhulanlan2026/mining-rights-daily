from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
import uuid
from datetime import date
from pathlib import Path

from mining_rights_daily.agent.bus import DEFAULT_HTTP_URLS, open_bus
from mining_rights_daily.agent.graph.checkpoint import CheckpointConfig, resolve_checkpoint
from mining_rights_daily.agent.graph.run import run_turn
from mining_rights_daily.agent.sse import briefing_producer, serve_forever, start_sse
from mining_rights_daily.logging import configure_logging
from mining_rights_daily.wecom.app import WeComCallback
from mining_rights_daily.wecom.bridge import answer_user, briefing_runner
from mining_rights_daily.wecom.client import WeComClient
from mining_rights_daily.wecom.config import WeComSettings
from mining_rights_daily.wecom.server import start_wecom

_DATE_IN_NAME = re.compile(r"\d{4}-\d{2}-\d{2}")


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Generate a mining-rights daily briefing via MCP.")
    parser.add_argument("--query", default=None, help="Natural-language briefing request.")
    parser.add_argument("--as-of", default=None, help="Briefing date, YYYY-MM-DD. Defaults to today.")
    parser.add_argument("--transport", choices=["stdio", "http"], default=None)
    parser.add_argument("--output", default="-", help="Write Markdown here, or '-' for stdout.")
    parser.add_argument("--thread-id", default=None, help="Conversation id. Reuse it to follow up.")
    parser.add_argument(
        "--checkpoint",
        default=None,
        help="SQLite file for short-term memory. Forces sqlite backend when set.",
    )
    parser.add_argument("--serve", action="store_true", help="Serve SSE at /v1/briefing.")
    parser.add_argument("--wecom", action="store_true", help="Receive Enterprise WeChat messages.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--news-url", default=None)
    parser.add_argument("--pdf-url", default=None)
    parser.add_argument("--price-url", default=None)
    args = parser.parse_args(argv)
    transport = args.transport or os.environ.get("MCP_TRANSPORT", "stdio")
    if transport == "streamable-http":
        transport = "http"
    urls = dict(DEFAULT_HTTP_URLS)
    urls["mining-news"] = args.news_url or os.environ.get("MCP_NEWS_URL", urls["mining-news"])
    urls["mineral-pdf"] = args.pdf_url or os.environ.get("MCP_PDF_URL", urls["mineral-pdf"])
    urls["lme-price"] = args.price_url or os.environ.get("MCP_PRICE_URL", urls["lme-price"])
    try:
        store = resolve_checkpoint(args.checkpoint)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    if args.serve and args.wecom:
        parser.error("--serve and --wecom cannot be used together")
    if args.serve:
        asyncio.run(_serve(transport, urls, store, args.host, args.port or 8765))
        return 0
    if args.wecom:
        port = args.port or int(os.environ.get("WECOM_PORT", "8780"))
        try:
            asyncio.run(_wecom(transport, urls, store, args.host, port))
        except ValueError as exc:
            print(exc, file=sys.stderr)
            return 2
        return 0
    if not args.query:
        parser.error("--query is required")
    as_of = date.fromisoformat(args.as_of) if args.as_of else date.today()
    thread_id = args.thread_id or str(uuid.uuid4())
    markdown = asyncio.run(_run(args.query, as_of, transport, urls, store, thread_id))
    if args.output == "-":
        sys.stdout.write(markdown)
    else:
        destination = stamp_output_path(Path(args.output), as_of)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(markdown, encoding="utf-8")
        print(f"wrote {destination}", file=sys.stderr)
    return 0


def stamp_output_path(path: Path, as_of: date) -> Path:
    """Put the briefing date in the file name when it is not already there."""

    stamp = as_of.isoformat()
    if _DATE_IN_NAME.search(path.stem):
        return path
    return path.with_name(f"{path.stem}-{stamp}{path.suffix}")


async def _run(
    query: str,
    as_of: date,
    transport: str,
    urls: dict[str, str],
    store: CheckpointConfig,
    thread_id: str,
) -> str:
    async with open_bus(transport, urls) as bus:
        return await run_turn(query, as_of, bus, store, thread_id)


async def _serve(
    transport: str, urls: dict[str, str], store: CheckpointConfig, host: str, port: int
) -> None:
    server = await start_sse(host, port, briefing_producer(transport, urls, store))
    print(f"sse http://{host}:{port}/v1/briefing", file=sys.stderr)
    print(f"checkpoint backend={store.backend}", file=sys.stderr)
    await serve_forever(server)


async def _wecom(
    transport: str, urls: dict[str, str], store: CheckpointConfig, host: str, port: int
) -> None:
    configure_logging("wecom")
    settings = WeComSettings.from_env()
    client = WeComClient(settings.corp_id, settings.secret, settings.agent_id)
    runner = briefing_runner(transport, urls, store)

    async def on_text(user_id: str, content: str, msg_id: str) -> None:
        del msg_id
        await answer_user(client, user_id, content, runner)

    callback = WeComCallback(settings, on_text)
    server = await start_wecom(host, port, callback)
    print(f"wecom http://{host}:{port}/wecom/callback", file=sys.stderr)
    print(f"checkpoint backend={store.backend}", file=sys.stderr)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    raise SystemExit(main())
