from __future__ import annotations

import io
import re

from pydantic import BaseModel
from pypdf import PdfReader

from mining_rights_daily.errors import DomainError

_CATEGORY = r"(Measured|Indicated|Inferred|Proven|Probable)"
_TABLE_ROW = re.compile(
    rf"^{_CATEGORY}\s+([0-9]+(?:,[0-9]{{3}})*(?:\.[0-9]+)?)\s+([0-9]+(?:\.[0-9]+)?)(?:\s+([0-9]+(?:,[0-9]{{3}})*(?:\.[0-9]+)?))?$",
    re.IGNORECASE,
)
_PROSE_ROW = re.compile(
    rf"\b{_CATEGORY}\b(?:\s+\w+){{0,6}}?\s+([0-9]+(?:\.[0-9]+)?)\s+(?:million tonnes|Mt)\s+at\s+([0-9]+(?:\.[0-9]+)?)%",
    re.IGNORECASE,
)
_RESOURCE = {"measured", "indicated", "inferred"}
_RESERVE = {"proven", "probable"}


class ResourceRow(BaseModel):
    kind: str
    category: str
    tonnes_mt: float
    grade_pct: float
    grade_label: str
    contained_kt: float | None = None
    contained_label: str | None = None


class ExtractResult(BaseModel):
    pdf_url: str
    title: str
    project: str | None
    location: str | None
    effective_date: str | None
    standard: str
    is_synthetic: bool
    rows: list[ResourceRow]
    parse_warnings: list[str]
    text_excerpt: str


def extract_pdf_bytes(payload: bytes, pdf_url: str) -> ExtractResult:
    if not payload:
        raise DomainError("PDF 是空文件")
    if not payload.startswith(b"%PDF"):
        raise DomainError("下载内容不是 PDF")
    try:
        reader = PdfReader(io.BytesIO(payload))
        pages = [(page.extract_text() or "") for page in reader.pages]
    except Exception as exc:
        raise DomainError(f"PDF 无法解析: {exc}") from exc
    text = "\n".join(pages).strip()
    if not text:
        raise DomainError("PDF 没有可提取的文字层，扫描件不在本工具范围内")
    return extract_text(text, pdf_url)


def extract_text(text: str, pdf_url: str) -> ExtractResult:
    lines = [_collapse(line) for line in text.splitlines()]
    lines = [line for line in lines if line]
    li2o = bool(re.search(r"li2o", text, re.IGNORECASE))
    grade_label = "Li2O %" if li2o else "%"
    contained_label = "Li2O kt" if li2o else "kt"
    rows = _table_rows(lines, grade_label, contained_label)
    warnings: list[str] = []
    if not rows:
        rows = _prose_rows(text, grade_label)
        if rows:
            warnings.append("表格未识别，已改用正文里的 million tonnes 句式")
    if not rows:
        warnings.append("没有识别到 Measured、Indicated、Inferred、Proven 或 Probable 行")
    title = lines[0] if lines else pdf_url
    project = _field(text, "Project")
    location = _field(text, "Location")
    effective = _first(r"Effective Date:\s*(\d{4}-\d{2}-\d{2})", text)
    standard = "NI 43-101" if re.search(r"NI\s*43-101", text, re.IGNORECASE) else "unspecified"
    synthetic = bool(re.search(r"synthetic|demonstration", text, re.IGNORECASE))
    return ExtractResult(
        pdf_url=pdf_url,
        title=title,
        project=project,
        location=location,
        effective_date=effective,
        standard=standard,
        is_synthetic=synthetic,
        rows=rows,
        parse_warnings=warnings,
        text_excerpt=_collapse(text)[:500],
    )


def _table_rows(lines: list[str], grade_label: str, contained_label: str) -> list[ResourceRow]:
    rows: list[ResourceRow] = []
    seen: set[tuple[str, str]] = set()
    for line in lines:
        if line.lower().startswith("category"):
            continue
        match = _TABLE_ROW.match(line)
        if match is None:
            continue
        category = match.group(1).capitalize()
        kind = _kind(category)
        key = (kind, category)
        if key in seen:
            continue
        seen.add(key)
        contained = _number(match.group(4)) if match.group(4) else None
        rows.append(
            ResourceRow(
                kind=kind,
                category=category,
                tonnes_mt=_number(match.group(2)),
                grade_pct=_number(match.group(3)),
                grade_label=grade_label,
                contained_kt=contained,
                contained_label=contained_label if contained is not None else None,
            )
        )
    return rows


def _prose_rows(text: str, grade_label: str) -> list[ResourceRow]:
    rows: list[ResourceRow] = []
    seen: set[tuple[str, str]] = set()
    for match in _PROSE_ROW.finditer(text):
        category = match.group(1).capitalize()
        kind = _kind(category)
        key = (kind, category)
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            ResourceRow(
                kind=kind,
                category=category,
                tonnes_mt=_number(match.group(2)),
                grade_pct=_number(match.group(3)),
                grade_label=grade_label,
            )
        )
    return rows


def _kind(category: str) -> str:
    lowered = category.lower()
    if lowered in _RESERVE:
        return "reserve"
    if lowered in _RESOURCE:
        return "resource"
    raise DomainError(f"未知资源类别: {category}")


def _number(value: str) -> float:
    return float(value.replace(",", ""))


def _field(text: str, name: str) -> str | None:
    return _first(rf"{name}:\s*(.+)", text)


def _first(pattern: str, text: str) -> str | None:
    match = re.search(pattern, text, re.IGNORECASE)
    if match is None:
        return None
    return match.group(1).splitlines()[0].strip()


def _collapse(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()
