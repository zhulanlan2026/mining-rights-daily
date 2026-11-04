from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from contextvars import ContextVar, Token
from dataclasses import dataclass

from mining_rights_daily.agent.protocol import ToolCallError

_BUDGET: ContextVar[RequestBudget | None] = ContextVar("request_budget", default=None)

_RETRY_STATUS = re.compile(r"HTTP\s+(429|500|502|503|504)\b", re.I)
_RETRY_HINTS = (
    "超时",
    "timeout",
    "timed out",
    "connecterror",
    "connection",
    "限流",
    "temporarily",
    "unavailable",
    "reset",
)
_NO_RETRY_HINTS = (
    "未建立",
    "不能为空",
    "不支持",
    "拒绝",
    "格式错误",
    "需要 yyyy",
    "http 401",
    "http 403",
    "http 404",
)


@dataclass(frozen=True)
class RequestBudget:
    deadline: float

    def remaining(self) -> float:
        return self.deadline - asyncio.get_running_loop().time()

    def raise_if_exhausted(self, label: str = "请求") -> None:
        left = self.remaining()
        if left <= 0:
            raise ToolCallError(f"{label}预算已用尽")


def bind_budget(budget: RequestBudget | None) -> Token[RequestBudget | None]:
    return _BUDGET.set(budget)


def reset_budget(token: Token[RequestBudget | None]) -> None:
    _BUDGET.reset(token)


def current_budget() -> RequestBudget | None:
    return _BUDGET.get()


def is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, (TimeoutError, asyncio.TimeoutError, ConnectionError, OSError)):
        return True
    text = str(exc).lower()
    if any(hint in text for hint in _NO_RETRY_HINTS):
        return False
    if _RETRY_STATUS.search(str(exc)):
        return True
    return any(hint in text for hint in _RETRY_HINTS)


async def with_retry[T](
    operation: Callable[[], Awaitable[T]],
    *,
    max_attempts: int = 3,
    base_delay: float = 0.5,
    budget: RequestBudget | None = None,
    label: str = "调用",
) -> T:
    if max_attempts < 1:
        raise ValueError("max_attempts 至少为 1")
    last: BaseException | None = None
    for attempt in range(1, max_attempts + 1):
        if budget is not None:
            budget.raise_if_exhausted(label)
        try:
            return await operation()
        except Exception as exc:
            last = exc
            if attempt >= max_attempts or not is_retryable(exc):
                raise
            delay = base_delay * (2 ** (attempt - 1))
            if budget is not None:
                left = budget.remaining()
                if left <= 0:
                    raise ToolCallError(f"{label}预算已用尽") from exc
                delay = min(delay, max(0.0, left))
            if delay > 0:
                await asyncio.sleep(delay)
    assert last is not None
    raise last
