"""Parser for plain-text attachments."""

from __future__ import annotations

import re

from email_parser.file_parsers.base import Blob, ParseContext, ParseResult
from email_parser.ids import make_block_id, make_doc_id
from email_parser.models import (
    Anchor,
    Block,
    BlockType,
    CommonMetadata,
    Document,
    DocumentMetadata,
    ParseStatus,
    Provenance,
    SourceType,
)

try:
    from charset_normalizer import from_bytes as charset_from_bytes
except ImportError:  # pragma: no cover
    charset_from_bytes = None  # type: ignore[assignment]

_EMAIL_HEADER_PREFIXES = (
    b"From:",
    b"Return-Path:",
    b"Received:",
    b"MIME-Version:",
    b"From ",
    b"Delivered-To:",
    b"To:",
    b"Subject:",
    b"Date:",
    b"Message-ID:",
    b"Content-Type:",
)
_SNIFF_WINDOW = 8192


def _decode_text(raw: bytes) -> str:
    """Decode bytes as UTF-8 with charset-normalizer and replace fallbacks."""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        pass
    if charset_from_bytes is not None:
        match = charset_from_bytes(raw).best()
        if match is not None:
            return str(match)
    return raw.decode("utf-8", errors="replace")


def _split_paragraphs(text: str) -> list[str]:
    """Split plain text into non-empty paragraphs on blank lines."""
    chunks = re.split(r"\n\s*\n", text.strip())
    return [chunk.strip() for chunk in chunks if chunk.strip()]


def _looks_like_email_sniff(sniffed: bytes) -> bool:
    """Return True when sniffed bytes resemble an RFC 822 message."""
    if not sniffed:
        return False
    window = sniffed[:_SNIFF_WINDOW]
    if any(window.startswith(prefix) for prefix in _EMAIL_HEADER_PREFIXES):
        return True
    header_block = window.split(b"\r\n\r\n", 1)[0]
    for marker in (
        b"\nFrom:",
        b"\r\nFrom:",
        b"\nSubject:",
        b"\r\nSubject:",
        b"\nTo:",
        b"\r\nTo:",
        b"\nMIME-Version:",
        b"\r\nMIME-Version:",
    ):
        if marker in header_block:
            return True
    return False


def _looks_like_ascii_text(sniffed: bytes) -> bool:
    """Return True when sniffed bytes look like plain ASCII text."""
    if not sniffed:
        return False
    if sniffed.startswith(b"%PDF-") or sniffed.startswith(b"From"):
        return False
    if _looks_like_email_sniff(sniffed):
        return False
    if b"\x00" in sniffed[:1024]:
        return False
    return bool(sniffed[:1].isalpha())


class TextPlainParser:
    """Parse plain-text blobs into paragraph blocks."""

    name = "text_plain"
    version = "0.1.0"
    priority = 5

    def can_handle(self, mime_type: str, sniffed: bytes) -> bool:
        """Claim text/plain MIME types or conservative ASCII sniff matches."""
        lowered = (mime_type or "").lower()
        if lowered == "text/plain" or lowered.startswith("text/plain"):
            return True
        return _looks_like_ascii_text(sniffed)

    def parse(self, blob: Blob, ctx: ParseContext) -> ParseResult:
        """Decode text and emit one paragraph block per blank-line segment."""
        text = _decode_text(blob.raw)
        doc_id = make_doc_id(blob.raw)
        blocks: list[Block] = []
        for ordinal, paragraph in enumerate(_split_paragraphs(text)):
            blocks.append(
                Block(
                    block_id=make_block_id(doc_id, ordinal, BlockType.paragraph.value),
                    type=BlockType.paragraph,
                    text=paragraph,
                    anchor=Anchor(),
                )
            )

        document = Document(
            doc_id=doc_id,
            source_type=SourceType.text,
            mime_type="text/plain",
            root_id=ctx.root_id or doc_id,
            parent_id=ctx.parent_id,
            relation_to_parent=blob.relation_to_parent,
            depth=ctx.depth,
            ordinal=blob.ordinal,
            metadata=DocumentMetadata(
                common=CommonMetadata(
                    filename=blob.filename,
                    byte_size=len(blob.raw),
                ),
            ),
            blocks=blocks,
            provenance=Provenance(
                parser=self.name,
                parser_version=self.version,
                parsed_at=None,
                status=ParseStatus.ok,
            ),
        )
        return ParseResult(document=document, child_blobs=[])
