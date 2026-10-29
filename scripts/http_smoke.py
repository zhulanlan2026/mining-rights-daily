"""Start the three MCP servers on HTTP, run one briefing, then stop them."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "out" / "pilbara-lithium-http-2026-10-27.md"
SERVERS = (
    ("mining-news-mcp", 8001),
    ("mineral-pdf-mcp", 8002),
    ("lme-price-mcp", 8003),
)


def wait_port(port: int, timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), 1):
                return
        except OSError:
            time.sleep(0.3)
    raise TimeoutError(f"port {port} did not open")


def main() -> int:
    env = os.environ.copy()
    env["NEWS_ENABLE_LIVE"] = "0"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    processes: list[subprocess.Popen[bytes]] = []
    try:
        for command, port in SERVERS:
            processes.append(
                subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        {
                            "mining-news-mcp": "mining_rights_daily.servers.news",
                            "mineral-pdf-mcp": "mining_rights_daily.servers.pdf",
                            "lme-price-mcp": "mining_rights_daily.servers.price",
                        }[command],
                        "--transport",
                        "streamable-http",
                        "--host",
                        "127.0.0.1",
                        "--port",
                        str(port),
                    ],
                    cwd=ROOT,
                    env=env,
                )
            )
        for _command, port in SERVERS:
            wait_port(port)
        OUT.parent.mkdir(parents=True, exist_ok=True)
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "mining_rights_daily.agent",
                "--transport",
                "http",
                "--as-of",
                "2026-10-27",
                "--query",
                "给我生成一份关于 Pilbara 锂矿的今日简报",
                "--output",
                str(ROOT / "out" / "pilbara-lithium-http.md"),
                "--news-url",
                "http://127.0.0.1:8001/mcp",
                "--pdf-url",
                "http://127.0.0.1:8002/mcp",
                "--price-url",
                "http://127.0.0.1:8003/mcp",
            ],
            cwd=ROOT,
            env=env,
            check=False,
        )
        text = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        required = ("## 新闻摘要", "## 储量数据", "## 价格走势", "## 风险提示", "108.4", "10460")
        missing = [item for item in required if item not in text]
        if completed.returncode != 0 or missing:
            print(f"agent exit {completed.returncode}; missing {missing}", file=sys.stderr)
            return 1
        print(f"http-ok {OUT}")
        return 0
    finally:
        for process in processes:
            process.terminate()
        for process in processes:
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()


if __name__ == "__main__":
    raise SystemExit(main())
