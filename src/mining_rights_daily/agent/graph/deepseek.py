from __future__ import annotations

import re
from typing import Any

import httpx

from mining_rights_daily.agent.graph.config import (
    DeepSeekConfig,
    deepseek_config,
    tool_retry_attempts,
    tool_retry_base_delay,
)
from mining_rights_daily.agent.graph.retry import current_budget, with_retry
from mining_rights_daily.agent.graph.skill import load_skill

_NUMBER = re.compile(r"\d+(?:\.\d+)?")


class DeepSeekError(Exception):
    """DeepSeek returned an error or an empty completion."""


class DeepSeekClient:
    """OpenAI-compatible chat client pinned to DeepSeek."""

    def __init__(
        self,
        config: DeepSeekConfig,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.config = config
        self.transport = transport

    @classmethod
    def from_env(cls, transport: httpx.AsyncBaseTransport | None = None) -> DeepSeekClient | None:
        config = deepseek_config()
        if config is None:
            return None
        return cls(config, transport)

    async def complete(self, system: str, user: str) -> str:
        async def once() -> str:
            return await self._complete_once(system, user)

        return await with_retry(
            once,
            max_attempts=tool_retry_attempts(),
            base_delay=tool_retry_base_delay(),
            budget=current_budget(),
            label="DeepSeek",
        )

    async def _complete_once(self, system: str, user: str) -> str:
        url = f"{self.config.base_url}/chat/completions"
        payload = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.2,
            "stream": False,
        }
        headers = {"Authorization": f"Bearer {self.config.api_key}"}
        try:
            async with httpx.AsyncClient(transport=self.transport, timeout=self.config.timeout) as client:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                body: dict[str, Any] = response.json()
        except httpx.HTTPStatusError as exc:
            raise DeepSeekError(f"DeepSeek 请求失败: HTTP {exc.response.status_code}") from exc
        except httpx.HTTPError as exc:
            raise DeepSeekError("DeepSeek 请求失败") from exc
        try:
            content = body["choices"][0]["message"].get("content") or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise DeepSeekError("DeepSeek 没有返回正文") from exc
        text = str(content).strip()
        if not text:
            raise DeepSeekError("DeepSeek 没有返回正文")
        return text


def unsupported_numbers(judgment: str, source: str) -> list[str]:
    return [token for token in _NUMBER.findall(judgment) if token not in source]


def judgment_system_prompt() -> str:
    return (
        load_skill()
        + "\n\n只写简要研判正文，不要标题，不要重复整篇日报。"
        + "不得新增日报正文里没有的数字、吨位、价格或日期。"
        + "不得把参考价写成 LME 结算价，不得把合成报告写成正式披露。\n"
    )


def intent_system_prompt() -> str:
    return (
        "你是意图分类器。必须只返回 JSON，不要解释。"
        '格式：{"intent":"query_news|query_pdf|query_price|query_trend|generate_daily_report|clarify|follow_up"}。'
        "生成日报、简报用 generate_daily_report；只问价格用 query_price；走势用 query_trend；"
        "新闻用 query_news；储量或技术报告用 query_pdf；接着上一轮用 follow_up；无法判断用 clarify。"
    )
