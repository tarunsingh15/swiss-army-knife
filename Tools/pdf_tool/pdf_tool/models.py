"""Generic PDF parse result types (independent of email-parser models)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal


class PdfBlockType(StrEnum):
    """Content block kinds emitted by the PDF tool."""

    paragraph = "paragraph"
    heading = "heading"
    table = "table"
    form_field = "form_field"


class PdfParseStatus(StrEnum):
    """Outcome of a PDF parse attempt."""

    ok = "ok"
    failed = "failed"


@dataclass(frozen=True)
class PdfAnchor:
    """Page and bounding box for citing content back to the PDF."""

    page: int
    bbox: tuple[float, float, float, float]


@dataclass(frozen=True)
class PdfBlock:
    """One ordered unit of extracted PDF content."""

    block_type: PdfBlockType
    text: str | None = None
    rows: list[list[str]] | None = None
    anchor: PdfAnchor | None = None


@dataclass(frozen=True)
class EmbeddedFile:
    """Bytes extracted from an embedded file or file-attachment annotation."""

    raw: bytes
    filename: str | None = None
    mime_type: str = "application/octet-stream"


@dataclass(frozen=True)
class PdfMetadata:
    """Document-level facts from the PDF catalog and text layer."""

    title: str | None
    producer: str | None
    page_count: int
    byte_size: int
    filename: str | None
    chars_per_page: list[int] = field(default_factory=list)
    has_text_layer: bool = False
    needs_ocr: bool = False


@dataclass(frozen=True)
class PdfParseResult:
    """Complete output of parsing one PDF byte payload."""

    blocks: list[PdfBlock]
    embedded_files: list[EmbeddedFile]
    metadata: PdfMetadata
    status: PdfParseStatus
    warnings: list[str] = field(default_factory=list)
