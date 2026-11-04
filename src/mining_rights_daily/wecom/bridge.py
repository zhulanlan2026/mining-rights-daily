from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import date
from pathlib import Path

from mining_rights_daily.agent.bus import open_bus
from mining_rights_daily.agent.graph.run import run_turn
from mining_rights_daily.wecom.client import WeComApiError, WeComClient

_LOG = logging.getLogger("mining_rights_daily.wecom")
Runner = Callable[[str, str], Awaitable[str]]


async def answer_user(client: WeComClient, user_id: str, content: str, run: Runner) -> None:
    try:
        await client.send_text(user_id, "正在生成，请稍等。")
        markdown = await run(user_id, content)
        await client.send_markdown(user_id, markdown)
    except Exception as exc:
        _LOG.exception("reply to %s failed", user_id)
        try:
            await client.send_text(user_id, f"生成失败：{exc}")
        except WeComApiError:
            _LOG.exception("failure notice to %s was not delivered", user_id)


def briefing_runner(
    transport: str,
    urls: dict[str, str],
    checkpoint: Path,
) -> Runner:
    async def run(user_id: str, content: str) -> str:
        async with open_bus(transport, urls) as bus:
            return await run_turn(
                content,
                date.today(),
                bus,
                checkpoint,
                f"wecom:{user_id}",
            )

    return run
