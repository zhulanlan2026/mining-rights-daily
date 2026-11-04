from __future__ import annotations

from pathlib import Path

import pytest

from mining_rights_daily.agent.graph.checkpoint import CheckpointConfig, resolve_checkpoint


def test_explicit_sqlite_path_forces_sqlite_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://db/mining")
    monkeypatch.setenv("AGENT_CHECKPOINT_BACKEND", "postgres")
    cfg = resolve_checkpoint("out/local.sqlite")
    assert cfg.backend == "sqlite"
    assert cfg.sqlite_path == Path("out/local.sqlite")
    assert cfg.database_url is None


def test_database_url_selects_postgres_when_backend_unspecified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AGENT_CHECKPOINT_BACKEND", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://db/mining")
    cfg = resolve_checkpoint(None)
    assert cfg.backend == "postgres"
    assert cfg.database_url == "postgresql://db/mining"


def test_sqlite_is_used_without_database_url(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("AGENT_CHECKPOINT_BACKEND", raising=False)
    monkeypatch.setenv("AGENT_CHECKPOINT", str(tmp_path / "mem.sqlite"))
    cfg = resolve_checkpoint(None)
    assert cfg.backend == "sqlite"
    assert cfg.sqlite_path == tmp_path / "mem.sqlite"


def test_postgres_backend_requires_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_CHECKPOINT_BACKEND", "postgres")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValueError, match="DATABASE_URL"):
        resolve_checkpoint(None)


def test_checkpoint_config_rejects_unknown_backend() -> None:
    with pytest.raises(ValueError, match="backend"):
        CheckpointConfig(backend="redis", sqlite_path=Path("x.sqlite"))
