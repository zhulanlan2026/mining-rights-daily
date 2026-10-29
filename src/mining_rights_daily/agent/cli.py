from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from datetime import date
from pathlib import Path

from mining_rights_daily.agent.bus import DEFAULT_HTTP_URLS, open_bus
from mining_rights_daily.agent.orchestrator import generate_briefing

_DATE_IN_NAME = re.compile(r"\d{4}-\d{2}-\d{2}")


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Generate a mining-rights daily briefing via MCP.")
    parser.add_argument("--query", required=True, help="Natural-language briefing request.")
    parser.add_argument("--as-of", default=None, help="Briefing date, YYYY-MM-DD. Defaults to today.")
    parser.add_argument("--transport", choices=["stdio", "http"], default=None)
    parser.add_argument("--output", default="-", help="Write Markdown here, or '-' for stdout.")
    parser.add_argument("--news-url", default=None)
    parser.add_argument("--pdf-url", default=None)
    parser.add_argument("--price-url", default=None)
    args = parser.parse_args(argv)
    as_of = date.fromisoformat(args.as_of) if args.as_of else date.today()
    transport = args.transport or os.environ.get("MCP_TRANSPORT", "stdio")
    if transport == "streamable-http":
        transport = "http"
    urls = dict(DEFAULT_HTTP_URLS)
    urls["mining-news"] = args.news_url or os.environ.get("MCP_NEWS_URL", urls["mining-news"])
    urls["mineral-pdf"] = args.pdf_url or os.environ.get("MCP_PDF_URL", urls["mineral-pdf"])
    urls["lme-price"] = args.price_url or os.environ.get("MCP_PRICE_URL", urls["lme-price"])
    markdown = asyncio.run(_run(args.query, as_of, transport, urls))
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


async def _run(query: str, as_of: date, transport: str, urls: dict[str, str]) -> str:
    async with open_bus(transport, urls) as bus:
        return await generate_briefing(query, bus, as_of)


if __name__ == "__main__":
    raise SystemExit(main())
