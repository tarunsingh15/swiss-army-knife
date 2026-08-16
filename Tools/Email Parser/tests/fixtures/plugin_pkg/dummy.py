"""Dummy PDF parser for plugin swap tests."""

from __future__ import annotations

from email_parser.file_parsers.base import Blob, ParseContext, ParseResult
from email_parser.ids import make_doc_id
from email_parser.models import (
    CommonMetadata,
    Document,
    DocumentMetadata,
    ParseStatus,
    Provenance,
    SourceType,
)

_PDF_MAGIC = b"%PDF-"


class DummyParser:
    """Minimal PDF parser stub registered only in tests."""

    name = "dummy_pdf"
    version = "0.0.1"
    priority = 100

    def can_handle(self, mime_type: str, sniffed: bytes) -> bool:
        """Claim blobs whose magic bytes start with %PDF-."""
        return sniffed[:5] == _PDF_MAGIC

    def parse(self, blob: Blob, ctx: ParseContext) -> ParseResult:
        """Return an empty ok document without parsing."""
        doc_id = make_doc_id(blob.raw)
        document = Document(
            doc_id=doc_id,
            source_type=SourceType.pdf,
            mime_type="application/pdf",
            root_id=ctx.root_id or doc_id,
            parent_id=ctx.parent_id,
            depth=ctx.depth,
            ordinal=blob.ordinal,
            metadata=DocumentMetadata(
                common=CommonMetadata(
                    filename=blob.filename,
                    byte_size=len(blob.raw),
                ),
            ),
            blocks=[],
            provenance=Provenance(
                parser=self.name,
                parser_version=self.version,
                parsed_at=None,
                status=ParseStatus.ok,
            ),
        )
        return ParseResult(document=document, child_blobs=[])
