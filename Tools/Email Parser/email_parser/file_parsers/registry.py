"""Parser discovery, MIME sniffing, and dispatch."""

from __future__ import annotations

from importlib.metadata import entry_points

import puremagic

from email_parser.file_parsers.base import Blob, ParseContext, Parser
from email_parser.file_parsers.email_mime import EmailMimeParser
from email_parser.file_parsers.pdf_pymupdf import PdfPymupdfParser
from email_parser.file_parsers.text_plain import TextPlainParser
from email_parser.ids import make_doc_id
from email_parser.models import (
    CommonMetadata,
    Document,
    DocumentMetadata,
    ParseStatus,
    Provenance,
    SourceType,
)

# Test hook: extra parsers registered for the process lifetime.
_EXTRA: list[Parser] = []

_BUILTIN_CLASSES: tuple[type, ...] = (
    EmailMimeParser,
    PdfPymupdfParser,
    TextPlainParser,
)

_PDF_MIME_TYPES = frozenset({"application/pdf", "application/x-pdf"})
_PDF_MAGIC = b"%PDF-"


def register_parser(parser: Parser) -> None:
    """Test hook: add a parser instance for the process lifetime."""
    _EXTRA.append(parser)


def clear_extra_parsers() -> None:
    """Test hook: remove all process-local extra parsers."""
    _EXTRA.clear()


def _load_entry_point_parsers() -> list[Parser]:
    """Load parser instances from setuptools entry points, if available."""
    loaded: list[Parser] = []
    try:
        eps = entry_points(group="email_parser.parsers")
    except TypeError:
        eps = entry_points().select(group="email_parser.parsers")

    for ep in eps:
        try:
            factory = ep.load()
            loaded.append(factory())
        except Exception:
            continue
    return loaded


def _builtin_parsers() -> list[Parser]:
    """Instantiate built-in parsers directly.

    Always merged into the registry so tests work without ``pip install -e``,
    which may not register entry points in every environment.
    """
    return [cls() for cls in _BUILTIN_CLASSES]


def load_parsers() -> list[Parser]:
    """Discover parsers via entry points and always include built-ins.

    Entry points are tried first, then the three built-in classes are merged
    in directly so pytest runs without an editable install. Extra parsers
    registered via :func:`register_parser` are appended last. Deduplication
    keeps the first instance seen for each parser ``name``.
    """
    by_name: dict[str, Parser] = {}

    for parser in _load_entry_point_parsers():
        by_name.setdefault(parser.name, parser)

    for parser in _builtin_parsers():
        by_name.setdefault(parser.name, parser)

    for parser in _EXTRA:
        by_name.setdefault(parser.name, parser)

    return list(by_name.values())


def sniff_mime(raw: bytes, declared: str | None) -> str:
    """Guess MIME type from magic bytes, then declared type, then octet-stream."""
    fallback = declared or "application/octet-stream"
    if not raw:
        return fallback
    try:
        what = getattr(puremagic, "what", None)
        if callable(what):
            guessed = what(None, raw)
            if guessed:
                return guessed
        matches = puremagic.magic_string(raw)
        if matches:
            mime = matches[0].mime_type
            # puremagic can return an empty string; treat that as "no guess".
            if mime:
                return mime
    except Exception:
        pass
    return fallback


def _is_pdf_claim(parser: Parser, mime_type: str, sniffed: bytes) -> bool:
    """Return True when a parser claims this blob as PDF."""
    if not parser.can_handle(mime_type, sniffed):
        return False
    return mime_type in _PDF_MIME_TYPES or sniffed[:5] == _PDF_MAGIC


def resolve_parser(
    raw: bytes,
    mime_type: str | None = None,
    *,
    pdf_engine: str = "pdf_pymupdf",
    filename: str | None = None,
) -> Parser | None:
    """Pick the best parser for raw bytes and an optional declared MIME type."""
    sniffed = raw[:2048] if len(raw) > 2048 else raw
    resolved_mime = sniff_mime(raw, mime_type)
    # Uploaded .eml files often sniff as octet-stream or text/plain (Gmail exports
    # start with Delivered-To:/Received:). Force RFC 822 unless bytes are PDF.
    if (
        filename
        and filename.lower().endswith((".eml", ".mime"))
        and sniffed[:5] != _PDF_MAGIC
        and resolved_mime not in _PDF_MIME_TYPES
    ):
        resolved_mime = "message/rfc822"
    candidates = [p for p in load_parsers() if p.can_handle(resolved_mime, sniffed)]
    if not candidates:
        return None

    pdf_claimants = [p for p in candidates if _is_pdf_claim(p, resolved_mime, sniffed)]
    if len(pdf_claimants) > 1:
        # Mislabeled PDFs (e.g. text/plain + %PDF- magic) need explicit tie-break.
        best = max(pdf_claimants, key=lambda p: p.priority)
        if pdf_engine != "pdf_pymupdf":
            for parser in pdf_claimants:
                if parser.name == pdf_engine:
                    return parser
        return best

    return max(candidates, key=lambda p: p.priority)


def unsupported_document(blob: Blob, ctx: ParseContext, sniffed_type: str) -> Document:
    """Build a stub document for content no parser could handle."""
    doc_id = make_doc_id(blob.raw)
    return Document(
        doc_id=doc_id,
        source_type=SourceType.unknown,
        mime_type=sniffed_type,
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
        blocks=[],
        provenance=Provenance(
            parser="registry",
            parser_version="0.1.0",
            parsed_at=None,
            status=ParseStatus.unsupported,
            warnings=[f"unsupported content type: {sniffed_type}"],
        ),
    )
