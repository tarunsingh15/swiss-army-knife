"""Frozen plug-and-play parser contract. Do not change this module's public shape."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from email_parser.models import Document, RelationType


@dataclass
class Blob:
    """A raw byte payload waiting to be parsed."""

    raw: bytes
    filename: str | None = None
    mime_type: str | None = None
    relation_to_parent: RelationType | None = None
    ordinal: int = 0
    content_id: str | None = None


@dataclass
class ParseContext:
    """Limits and identity passed into a single parse call."""

    max_depth: int = 10
    max_fanout: int = 200
    depth: int = 0
    parent_id: str | None = None
    root_id: str | None = None
    pdf_engine: str = "pdf_pymupdf"


@dataclass
class ParseResult:
    """A parsed document plus child blobs for the pipeline to enqueue.

    Parsers must not recurse: return child blobs and let pipeline.process()
    walk the tree with depth/fanout guards.
    """

    document: Document
    child_blobs: list[Blob] = field(default_factory=list)


class Parser(Protocol):
    """Every file-type parser implements this and nothing more."""

    name: str
    version: str
    priority: int

    def can_handle(self, mime_type: str, sniffed: bytes) -> bool:
        """Claim a blob by sniffed magic bytes, never by file extension."""

    def parse(self, blob: Blob, ctx: ParseContext) -> ParseResult:
        """Return (document, child_blobs). NEVER recurse — hand children back."""
