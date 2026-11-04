from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from mining_rights_daily.agent.graph.config import checkpoint_path


@dataclass(frozen=True)
class CheckpointConfig:
    """Where LangGraph short-term session snapshots are stored."""

    backend: str
    sqlite_path: Path | None = None
    database_url: str | None = None

    def __post_init__(self) -> None:
        if self.backend not in {"sqlite", "postgres"}:
            raise ValueError(f"未知 Checkpoint backend: {self.backend}")
        if self.backend == "sqlite" and self.sqlite_path is None:
            raise ValueError("sqlite Checkpoint 需要 sqlite_path")
        if self.backend == "postgres" and not self.database_url:
            raise ValueError("postgres Checkpoint 需要 DATABASE_URL")


def resolve_checkpoint(explicit_sqlite: str | Path | None = None) -> CheckpointConfig:
    """Pick Checkpoint backend.

    Explicit --checkpoint / path always forces SQLite for local runs.
    Otherwise: AGENT_CHECKPOINT_BACKEND, or DATABASE_URL ⇒ postgres, else sqlite.
    """

    if explicit_sqlite is not None and str(explicit_sqlite).strip():
        path = Path(str(explicit_sqlite))
        path.parent.mkdir(parents=True, exist_ok=True)
        return CheckpointConfig(backend="sqlite", sqlite_path=path)

    backend = os.environ.get("AGENT_CHECKPOINT_BACKEND", "").strip().lower()
    if backend in {"postgresql", "pg"}:
        backend = "postgres"
    url = os.environ.get("DATABASE_URL", "").strip() or None

    if backend == "postgres" or (not backend and url):
        if not url:
            raise ValueError("PostgreSQL Checkpoint 需要环境变量 DATABASE_URL")
        return CheckpointConfig(backend="postgres", database_url=url)

    if backend and backend != "sqlite":
        raise ValueError(f"未知 Checkpoint backend: {backend}")

    path = checkpoint_path(None)
    return CheckpointConfig(backend="sqlite", sqlite_path=path)


def as_checkpoint_config(value: CheckpointConfig | Path) -> CheckpointConfig:
    if isinstance(value, CheckpointConfig):
        return value
    path = Path(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    return CheckpointConfig(backend="sqlite", sqlite_path=path)


@asynccontextmanager
async def open_checkpointer(config: CheckpointConfig) -> AsyncIterator[Any]:
    if config.backend == "sqlite":
        assert config.sqlite_path is not None
        config.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        async with AsyncSqliteSaver.from_conn_string(str(config.sqlite_path)) as saver:
            yield saver
        return

    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    assert config.database_url is not None
    async with AsyncPostgresSaver.from_conn_string(config.database_url) as saver:
        await saver.setup()
        yield saver
