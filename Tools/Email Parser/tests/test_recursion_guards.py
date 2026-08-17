"""Tests for pipeline depth, fanout, and cycle guards."""

from __future__ import annotations

from email_parser.config import Settings
from email_parser.file_parsers.base import Blob, ParseContext, ParseResult
from email_parser.file_parsers.registry import clear_extra_parsers, register_parser
from email_parser.ids import make_doc_id
from email_parser.models import (
    CommonMetadata,
    Document,
    DocumentMetadata,
    ParseStatus,
    Provenance,
    SourceType,
)
from email_parser.pipeline import process


def _make_settings(**overrides: int) -> Settings:
    """Build Settings with small caps for guard tests."""
    return Settings(
        output_dir=__import__("pathlib").Path("output"),
        pdf_engine="pdf_pymupdf",
        max_depth=overrides.get("max_depth", 3),
        max_fanout=overrides.get("max_fanout", 5),
        display_path_prefix="",
        token_budget=6000,
        ocr_enabled=True,
        ocr_dpi=200,
        ocr_min_chars=20,
    )


class _CycleParser:
    """Parser that always re-emits the same bytes as a child."""

    name = "cycle_test"
    version = "0.0.1"
    priority = 1000

    def can_handle(self, mime_type: str, sniffed: bytes) -> bool:
        """Claim a private test MIME type."""
        return mime_type == "application/x-cycle-test"

    def parse(self, blob: Blob, ctx: ParseContext) -> ParseResult:
        """Return the same blob as its only child."""
        doc_id = make_doc_id(blob.raw)
        document = Document(
            doc_id=doc_id,
            source_type=SourceType.unknown,
            mime_type=blob.mime_type or "application/x-cycle-test",
            root_id=ctx.root_id or doc_id,
            parent_id=ctx.parent_id,
            depth=ctx.depth,
            ordinal=blob.ordinal,
            metadata=DocumentMetadata(
                common=CommonMetadata(byte_size=len(blob.raw), filename=blob.filename),
            ),
            blocks=[],
            provenance=Provenance(
                parser=self.name,
                parser_version=self.version,
                parsed_at=None,
                status=ParseStatus.ok,
            ),
        )
        child = Blob(
            raw=blob.raw,
            filename=blob.filename,
            mime_type=blob.mime_type,
            ordinal=0,
        )
        return ParseResult(document=document, child_blobs=[child])


class _FanoutParser:
    """Parser that emits many distinct child blobs."""

    name = "fanout_test"
    version = "0.0.1"
    priority = 1000

    def __init__(self, child_count: int) -> None:
        self.child_count = child_count

    def can_handle(self, mime_type: str, sniffed: bytes) -> bool:
        """Claim a private test MIME type."""
        return mime_type == "application/x-fanout-test"

    def parse(self, blob: Blob, ctx: ParseContext) -> ParseResult:
        """Emit child_count unique child blobs."""
        doc_id = make_doc_id(blob.raw)
        document = Document(
            doc_id=doc_id,
            source_type=SourceType.unknown,
            mime_type=blob.mime_type or "application/x-fanout-test",
            root_id=ctx.root_id or doc_id,
            parent_id=ctx.parent_id,
            depth=ctx.depth,
            ordinal=blob.ordinal,
            metadata=DocumentMetadata(
                common=CommonMetadata(byte_size=len(blob.raw), filename=blob.filename),
            ),
            blocks=[],
            provenance=Provenance(
                parser=self.name,
                parser_version=self.version,
                parsed_at=None,
                status=ParseStatus.ok,
            ),
        )
        children = [
            Blob(raw=f"child-{index}".encode(), mime_type="application/octet-stream", ordinal=index)
            for index in range(self.child_count)
        ]
        return ParseResult(document=document, child_blobs=children)


class _DepthParser:
    """Parser that emits a unique child on every level."""

    name = "depth_test"
    version = "0.0.1"
    priority = 1000

    def can_handle(self, mime_type: str, sniffed: bytes) -> bool:
        """Claim a private test MIME type."""
        return mime_type == "application/x-depth-test"

    def parse(self, blob: Blob, ctx: ParseContext) -> ParseResult:
        """Emit one child with fresh bytes to force deeper nesting."""
        doc_id = make_doc_id(blob.raw)
        document = Document(
            doc_id=doc_id,
            source_type=SourceType.unknown,
            mime_type=blob.mime_type or "application/x-depth-test",
            root_id=ctx.root_id or doc_id,
            parent_id=ctx.parent_id,
            depth=ctx.depth,
            ordinal=blob.ordinal,
            metadata=DocumentMetadata(
                common=CommonMetadata(byte_size=len(blob.raw), filename=blob.filename),
            ),
            blocks=[],
            provenance=Provenance(
                parser=self.name,
                parser_version=self.version,
                parsed_at=None,
                status=ParseStatus.ok,
            ),
        )
        child_raw = f"depth-{ctx.depth + 1}-{len(blob.raw)}".encode()
        child = Blob(raw=child_raw, mime_type="application/x-depth-test", ordinal=0)
        return ParseResult(document=document, child_blobs=[child])


def setup_function() -> None:
    """Clear extra parsers before each test."""
    clear_extra_parsers()


def teardown_function() -> None:
    """Clear extra parsers after each test."""
    clear_extra_parsers()


def test_cycle_guard_deduplicates_same_bytes() -> None:
    """A parser re-emitting identical bytes does not loop forever."""
    register_parser(_CycleParser())
    root = Blob(raw=b"cycle-root", mime_type="application/x-cycle-test")
    docs = process(root, settings=_make_settings(max_depth=10, max_fanout=10))
    assert len(docs) == 1


def test_fanout_guard_truncates_children_and_warns() -> None:
    """Only max_fanout children are enqueued and the parent records a warning."""
    register_parser(_FanoutParser(child_count=15))
    root = Blob(raw=b"fanout-root", mime_type="application/x-fanout-test")
    settings = _make_settings(max_depth=5, max_fanout=5)
    docs = process(root, settings=settings)

    parent = docs[0]
    assert any("fanout truncated" in warning for warning in parent.provenance.warnings)
    # root + 5 unsupported children (unknown binary)
    assert len(docs) == 1 + settings.max_fanout


def test_depth_guard_stops_at_max_depth() -> None:
    """Unique nested children stop when depth exceeds max_depth."""
    register_parser(_DepthParser())
    root = Blob(raw=b"depth-root", mime_type="application/x-depth-test")
    settings = _make_settings(max_depth=3, max_fanout=5)
    docs = process(root, settings=settings)

    depths = {doc.depth for doc in docs}
    assert max(depths) == settings.max_depth + 1
    assert any(
        doc.provenance.status == ParseStatus.failed and "depth cap" in doc.provenance.warnings[0]
        for doc in docs
        if doc.depth == settings.max_depth + 1
    )
    assert len(docs) == settings.max_depth + 2
