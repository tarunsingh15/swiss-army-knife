"""Generic document parse result types (mirror pdf_tool field names)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class DocBlockType(StrEnum):
    """Content block kinds emitted by the document parser."""

    paragraph = "paragraph"
    heading = "heading"
    table = "table"
    form_field = "form_field"


class DocParseStatus(StrEnum):
    """Outcome of a document parse attempt."""

    ok = "ok"
    failed = "failed"


@dataclass(frozen=True)
class DocAnchor:
    """Page and bounding box for citing content back to the PDF."""

    page: int
    bbox: tuple[float, float, float, float]


@dataclass(frozen=True)
class DocBlock:
    """One ordered unit of extracted document content."""

    block_type: DocBlockType
    text: str | None = None
    rows: list[list[str]] | None = None
    anchor: DocAnchor | None = None


@dataclass(frozen=True)
class DocMetadata:
    """Document-level facts from the PDF and OCR pass."""

    title: str | None
    producer: str | None
    page_count: int
    byte_size: int
    filename: str | None
    chars_per_page: list[int] = field(default_factory=list)
    has_text_layer: bool = False
    needs_ocr: bool = True
    ocr_engine: str | None = None


@dataclass(frozen=True)
class DocParseResult:
    """Complete output of parsing one PDF byte payload via OCR."""

    blocks: list[DocBlock]
    metadata: DocMetadata
    status: DocParseStatus
    warnings: list[str] = field(default_factory=list)
