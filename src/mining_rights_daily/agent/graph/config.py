from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-chat"


@dataclass(frozen=True)
class DeepSeekConfig:
    api_key: str
    base_url: str
    model: str
    timeout: float


def deepseek_config() -> DeepSeekConfig | None:
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not key:
        return None
    base = os.environ.get("DEEPSEEK_BASE_URL", DEEPSEEK_BASE_URL).strip().rstrip("/")
    model = os.environ.get("DEEPSEEK_MODEL", DEEPSEEK_MODEL).strip() or DEEPSEEK_MODEL
    timeout = float(os.environ.get("DEEPSEEK_TIMEOUT", "60"))
    return DeepSeekConfig(api_key=key, base_url=base or DEEPSEEK_BASE_URL, model=model, timeout=timeout)


def checkpoint_path(explicit: str | None = None) -> Path:
    raw = explicit or os.environ.get("AGENT_CHECKPOINT") or "out/checkpoints.sqlite"
    path = Path(raw)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def tool_timeout_seconds() -> float:
    return float(os.environ.get("AGENT_TOOL_TIMEOUT", "120"))
