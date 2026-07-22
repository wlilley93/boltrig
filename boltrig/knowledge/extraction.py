"""Bounded, citation-preserving extraction for the first supported formats."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from io import BytesIO
import re

MAX_EXTRACTED_CHARS = 5_000_000
MAX_SEGMENTS = 5_000
TARGET_SEGMENT_CHARS = 2_000


@dataclass(frozen=True)
class ExtractedPart:
    text: str
    locator: dict[str, object]


@dataclass(frozen=True)
class Extraction:
    format: str
    parts: tuple[ExtractedPart, ...]
    content_hash: str
    generator: str
    generator_version: str


def extract(data: bytes, *, media_type: str, filename: str) -> Extraction:
    kind = _kind(media_type, filename)
    if kind == "pdf":
        parts = _pdf_parts(data)
        generator = "pypdf"
        try:
            from pypdf import __version__ as version
        except ImportError as exc:
            raise ValueError("PDF support is unavailable in this installation") from exc
    else:
        parts = _text_parts(data)
        generator, version = "boltrig-text", "1"
    _bounded(parts)
    joined = "\n\n".join(part.text for part in parts)
    return Extraction(
        format="text/plain",
        parts=tuple(parts),
        content_hash=hashlib.sha256(joined.encode("utf-8")).hexdigest(),
        generator=generator,
        generator_version=str(version),
    )


def _kind(media_type: str, filename: str) -> str:
    media = (media_type or "").split(";", 1)[0].strip().lower()
    suffix = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if media == "application/pdf" or suffix == "pdf":
        return "pdf"
    if media.startswith("text/") or suffix in {"txt", "md", "markdown"}:
        return "text"
    raise ValueError("first-slice Knowledge supports text, Markdown, and PDF files")


def _text_parts(data: bytes) -> list[ExtractedPart]:
    if b"\x00" in data:
        raise ValueError("text upload contains NUL bytes")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("text upload must be UTF-8") from exc
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    return _pack_paragraphs(paragraphs)


def _pack_paragraphs(paragraphs: list[str]) -> list[ExtractedPart]:
    parts: list[ExtractedPart] = []
    buffer: list[str] = []
    start = 1
    size = 0
    for index, paragraph in enumerate(paragraphs, start=1):
        if buffer and size + len(paragraph) > TARGET_SEGMENT_CHARS:
            parts.append(_paragraph_part(buffer, start, index - 1))
            buffer, start, size = [], index, 0
        buffer.append(paragraph)
        size += len(paragraph) + 2
    if buffer:
        parts.append(_paragraph_part(buffer, start, len(paragraphs)))
    return parts


def _paragraph_part(parts: list[str], start: int, end: int) -> ExtractedPart:
    locator: dict[str, object] = {"paragraph_start": start, "paragraph_end": end}
    heading = next((line.lstrip("# ") for line in parts if line.startswith("#")), None)
    if heading:
        locator["section"] = heading[:200]
    return ExtractedPart(text="\n\n".join(parts), locator=locator)


def _pdf_parts(data: bytes) -> list[ExtractedPart]:
    if not data.startswith(b"%PDF-"):
        raise ValueError("file labelled as PDF does not have a PDF signature")
    try:
        from pypdf import PdfReader

        reader = PdfReader(BytesIO(data), strict=True)
        if reader.is_encrypted:
            raise ValueError("encrypted PDFs are not supported")
        parts = []
        for page_number, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").strip()
            if text:
                parts.extend(_split_page(text, page_number))
        return parts
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"PDF extraction failed: {type(exc).__name__}") from exc


def _split_page(text: str, page_number: int) -> list[ExtractedPart]:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    if not paragraphs:
        paragraphs = [text]
    packed = _pack_paragraphs(paragraphs)
    return [
        ExtractedPart(text=part.text, locator={"page": page_number, **part.locator})
        for part in packed
    ]


def _bounded(parts: list[ExtractedPart]) -> None:
    if not parts:
        raise ValueError("the document contains no extractable text")
    if len(parts) > MAX_SEGMENTS:
        raise ValueError(f"document produces too many segments (max {MAX_SEGMENTS})")
    if sum(len(part.text) for part in parts) > MAX_EXTRACTED_CHARS:
        raise ValueError("document produces too much extracted text")
