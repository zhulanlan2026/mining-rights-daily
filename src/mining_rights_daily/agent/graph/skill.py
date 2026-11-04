from __future__ import annotations

from pathlib import Path

SKILL_PATH = (
    Path(__file__).resolve().parents[2] / "skills" / "mining-daily-report" / "SKILL.md"
)


def load_skill() -> str:
    return SKILL_PATH.read_text(encoding="utf-8")


def required_headings(text: str | None = None) -> list[str]:
    body = load_skill() if text is None else text
    capture = False
    found: list[str] = []
    for line in body.splitlines():
        if line.startswith("## "):
            capture = line.strip() == "## 必须章节"
            continue
        if capture and line.startswith("- "):
            found.append(f"## {line[2:].strip()}")
    return found
