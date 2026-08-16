"""Canonical document, block, and metadata models for parsed email content."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RelationType(StrEnum):
    """Typed edge from a child document to its parent."""

    attachment = "attachment"
    inline_image = "inline_image"
    embedded_file = "embedded_file"
    forwarded_message = "forwarded_message"
    link_reference = "link_reference"
    derived = "derived"


class BlockType(StrEnum):
    """Kinds of content blocks a parser may emit."""

    heading = "heading"
    paragraph = "paragraph"
    list = "list"
    table = "table"
    image_ref = "image_ref"
    quoted_history = "quoted_history"
    signature = "signature"
    form_field = "form_field"


class SourceType(StrEnum):
    """High-level source family for a document."""

    email = "email"
    pdf = "pdf"
    image = "image"
    text = "text"
    unknown = "unknown"


class ParseStatus(StrEnum):
    """Outcome of a single parse attempt."""

    ok = "ok"
    warning = "warning"
    failed = "failed"
    unsupported = "unsupported"


class Anchor(BaseModel):
    """Page and geometry used to cite a block back to its source file."""

    model_config = ConfigDict(extra="forbid")

    page: int | None = None
    bbox: tuple[float, float, float, float] | None = None
    quads: list[list[float]] | None = None


class CommonMetadata(BaseModel):
    """Cross-format facts that every document may carry."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    created_at: str | None = None
    byte_size: int = 0
    page_count: int | None = None
    language: str | None = None
    filename: str | None = None


class NativeMetadata(BaseModel):
    """Format-specific facts. Extra keys are allowed for engine-specific data."""

    model_config = ConfigDict(extra="allow")

    has_text_layer: bool | None = None
    needs_ocr: bool | None = None
    producer: str | None = None
    chars_per_page: list[int] | None = None
    from_name: str | None = None
    from_addr: str | None = None
    from_domain: str | None = None
    to: list[dict[str, str]] | None = None
    cc: list[dict[str, str]] | None = None
    subject: str | None = None
    date_utc: str | None = None
    date_original: str | None = None
    message_id: str | None = None
    in_reply_to: str | None = None
    references: list[str] | None = None


class DocumentMetadata(BaseModel):
    """Parsed facts split into common and native sections."""

    model_config = ConfigDict(extra="forbid")

    common: CommonMetadata = Field(default_factory=CommonMetadata)
    native: NativeMetadata = Field(default_factory=NativeMetadata)


class Extraction(BaseModel):
    """Inferred (not parsed) field. Never mix these with metadata facts."""

    model_config = ConfigDict(extra="forbid")

    field: str
    value: str
    confidence: float | None = None
    method: str | None = None
    evidence_blocks: list[str] = Field(default_factory=list)


class Provenance(BaseModel):
    """Which parser produced this document and how it went."""

    model_config = ConfigDict(extra="forbid")

    parser: str
    parser_version: str
    parsed_at: str | None = None
    status: ParseStatus = ParseStatus.ok
    warnings: list[str] = Field(default_factory=list)


class Block(BaseModel):
    """One ordered unit of extracted content with an optional citation anchor."""

    model_config = ConfigDict(extra="forbid")

    block_id: str
    type: BlockType
    text: str | None = None
    rows: list[list[str]] | None = None
    child_doc_id: str | None = None
    anchor: Anchor | None = None


class Document(BaseModel):
    """Canonical parsed document. Every parser emits this shape."""

    model_config = ConfigDict(extra="forbid")

    doc_id: str
    source_type: SourceType
    mime_type: str
    root_id: str | None = None
    parent_id: str | None = None
    relation_to_parent: RelationType | None = None
    depth: int = 0
    ordinal: int = 0
    path: str = ""
    metadata: DocumentMetadata = Field(default_factory=DocumentMetadata)
    blocks: list[Block] = Field(default_factory=list)
    extractions: list[Extraction] = Field(default_factory=list)
    provenance: Provenance

    def model_dump_json_stable(self, **kwargs: Any) -> str:
        """Serialize with sorted keys for deterministic snapshots."""
        return self.model_dump_json(indent=2, **kwargs)
