from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

from mining_rights_daily.errors import DomainError
from mining_rights_daily.net import fetch_limited
from mining_rights_daily.paths import (
    REPORTS_DIR,
    SAMPLE_REPORT_ID,
    SAMPLE_REPORT_PATH,
    SAMPLE_REPORT_URL,
)
from mining_rights_daily.pdfparse.document import ExtractResult, extract_pdf_bytes
from mining_rights_daily.pdfparse.sample_pdf import build_sample_pdf

MAX_PDF_BYTES = 20 * 1024 * 1024


def extract_resources(pdf_url: str) -> ExtractResult:
    if not pdf_url or not pdf_url.strip():
        raise DomainError("pdf_url 不能为空")
    payload = _load(pdf_url.strip())
    return extract_pdf_bytes(payload, pdf_url.strip())


def ensure_sample_report() -> Path:
    SAMPLE_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not SAMPLE_REPORT_PATH.exists():
        SAMPLE_REPORT_PATH.write_bytes(build_sample_pdf())
    return SAMPLE_REPORT_PATH


def _load(pdf_url: str) -> bytes:
    if pdf_url.startswith("catalog:"):
        catalog_id = pdf_url.removeprefix("catalog:")
        if catalog_id != SAMPLE_REPORT_ID:
            raise DomainError(
                f"未知报告目录 {pdf_url!r}。已登记: {SAMPLE_REPORT_URL}"
            )
        path = ensure_sample_report()
        return path.read_bytes()
    if pdf_url.startswith("file://"):
        path = _file_url_path(pdf_url)
        reports = REPORTS_DIR.resolve()
        resolved = path.resolve()
        if not resolved.is_relative_to(reports):
            raise DomainError("file URL 必须位于内置 reports 目录")
        if not resolved.is_file():
            raise DomainError(f"找不到 PDF: {resolved}")
        return resolved.read_bytes()
    if pdf_url.startswith(("http://", "https://")):
        payload, _detail = fetch_limited(pdf_url, timeout=20, max_bytes=MAX_PDF_BYTES)
        return payload
    raise DomainError("pdf_url 只接受 catalog:、file://、http:// 或 https://")


def _file_url_path(pdf_url: str) -> Path:
    parsed = urlparse(pdf_url)
    raw_path = unquote(parsed.path)
    if parsed.netloc and len(parsed.netloc) == 1:
        raw_path = f"{parsed.netloc}:{raw_path}"
    return Path(url2pathname(raw_path))
