from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from urllib.parse import unquote

MARKDOWN_LIMIT = 2000


@dataclass(frozen=True)
class Inbound:
    user_id: str
    msg_type: str
    content: str
    msg_id: str


def parse_query(query: str) -> dict[str, str]:
    """Decode a query string without treating '+' as a space."""

    found: dict[str, str] = {}
    for part in query.split("&"):
        if not part:
            continue
        key, _, value = part.partition("=")
        found[unquote(key)] = unquote(value)
    return found


def parse_inbound(xml_text: str) -> Inbound:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise ValueError("消息 XML 无法解析") from exc
    return Inbound(
        user_id=_text(root, "FromUserName"),
        msg_type=_text(root, "MsgType"),
        content=_text(root, "Content"),
        msg_id=_text(root, "MsgId"),
    )


def encrypt_field(xml_text: str) -> str | None:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise ValueError("消息 XML 无法解析") from exc
    value = _text(root, "Encrypt")
    return value or None


def split_markdown(text: str, limit: int = MARKDOWN_LIMIT) -> list[str]:
    body = text.strip() or "未获取到数据。"
    if len(body.encode()) <= limit:
        return [body]
    raw = _split_bytes(body, limit - 24)
    total = len(raw)
    parts: list[str] = []
    for index, part in enumerate(raw, start=1):
        piece = f"（{index}/{total}）\n{part.lstrip()}"
        if len(piece.encode()) <= limit:
            parts.append(piece)
            continue
        head, _rest = _take(piece, limit)
        parts.append(head)
    return parts


def _split_bytes(text: str, limit: int) -> list[str]:
    parts: list[str] = []
    current = ""
    for paragraph in text.split("\n"):
        candidate = paragraph if not current else current + "\n" + paragraph
        if len(candidate.encode()) <= limit:
            current = candidate
            continue
        if current:
            parts.append(current)
        block = paragraph
        while len(block.encode()) > limit:
            head, block = _take(block, limit)
            parts.append(head)
        current = block
    if current:
        parts.append(current)
    return parts or [text]


def _take(text: str, limit: int) -> tuple[str, str]:
    raw = text.encode()
    if len(raw) <= limit:
        return text, ""
    cut = limit
    while cut > 0 and raw[cut] & 0xC0 == 0x80:
        cut -= 1
    if cut == 0:
        cut = limit
    head = raw[:cut].decode()
    return head, text[len(head) :]


def _text(root: ET.Element, tag: str) -> str:
    node = root.find(tag)
    if node is None or node.text is None:
        return ""
    return node.text.strip()
