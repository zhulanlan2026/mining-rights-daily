from __future__ import annotations

import os
from dataclasses import dataclass

_NAMES = (
    "WECOM_CORP_ID",
    "WECOM_AGENT_ID",
    "WECOM_SECRET",
    "WECOM_TOKEN",
    "WECOM_ENCODING_AES_KEY",
)


@dataclass(frozen=True)
class WeComSettings:
    corp_id: str
    agent_id: int
    secret: str
    token: str
    encoding_aes_key: str

    @classmethod
    def from_env(cls) -> WeComSettings:
        missing = [name for name in _NAMES if not os.environ.get(name, "").strip()]
        if missing:
            joined = "、".join(missing)
            raise ValueError(f"缺少企业微信配置：{joined}")
        try:
            agent_id = int(os.environ["WECOM_AGENT_ID"].strip())
        except ValueError as exc:
            raise ValueError("WECOM_AGENT_ID 必须是数字") from exc
        return cls(
            corp_id=os.environ["WECOM_CORP_ID"].strip(),
            agent_id=agent_id,
            secret=os.environ["WECOM_SECRET"].strip(),
            token=os.environ["WECOM_TOKEN"].strip(),
            encoding_aes_key=os.environ["WECOM_ENCODING_AES_KEY"].strip(),
        )
