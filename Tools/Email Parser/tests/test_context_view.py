"""Tests for the compact AI context view."""

from email_parser.ai_context.context_view import render_context
from email_parser.ids import make_block_id, make_doc_id
from email_parser.models import (
    Block,
    BlockType,
    CommonMetadata,
    Document,
    DocumentMetadata,
    NativeMetadata,
    ParseStatus,
    Provenance,
    SourceType,
)


def _email_with_quote_split() -> list[Document]:
    """Build a root email with new body text and quoted history."""
    raw = b"context view email"
    doc_id = make_doc_id(raw)
    document = Document(
        doc_id=doc_id,
        source_type=SourceType.email,
        mime_type="message/rfc822",
        root_id=doc_id,
        metadata=DocumentMetadata(
            common=CommonMetadata(title="Budget test", byte_size=len(raw)),
            native=NativeMetadata(
                subject="Budget test",
                from_addr="sender@example.com",
                to=[{"name": "Recipient", "addr": "to@example.com"}],
                date_utc="2026-01-01T00:00:00Z",
            ),
        ),
        blocks=[
            Block(
                block_id=make_block_id(doc_id, 0, BlockType.paragraph.value),
                type=BlockType.paragraph,
                text="New ask",
            ),
            Block(
                block_id=make_block_id(doc_id, 1, BlockType.quoted_history.value),
                type=BlockType.quoted_history,
                text="Old thread",
            ),
        ],
        provenance=Provenance(
            parser="test",
            parser_version="0.0.0",
            status=ParseStatus.ok,
        ),
    )
    return [document]


def test_render_context_excludes_quoted_history_by_default() -> None:
    """Default context includes new body text but not quoted history."""
    rendered = render_context(_email_with_quote_split())
    assert "New ask" in rendered
    assert "Old thread" not in rendered
    assert "--- untrusted source text begins ---" in rendered
    assert "--- untrusted source text ends ---" in rendered


def test_render_context_respects_tiny_token_budget() -> None:
    """A very small token budget truncates or keeps output short."""
    rendered = render_context(_email_with_quote_split(), token_budget=20)
    assert "[truncated]" in rendered or len(rendered) < 120
