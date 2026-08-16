"""Tests for pydantic models in email_parser.models."""

from email_parser.ids import make_doc_id
from email_parser.models import (
    Anchor,
    Block,
    BlockType,
    CommonMetadata,
    Document,
    DocumentMetadata,
    Extraction,
    NativeMetadata,
    ParseStatus,
    Provenance,
    SourceType,
)


def _sample_document(doc_id: str, *, parsed_at: str | None = None) -> Document:
    """Build a representative Document for round-trip tests."""
    return Document(
        doc_id=doc_id,
        source_type=SourceType.email,
        mime_type="message/rfc822",
        root_id=doc_id,
        metadata=DocumentMetadata(
            common=CommonMetadata(title="Test subject", byte_size=3),
            native=NativeMetadata(has_text_layer=True, producer="test-parser"),
        ),
        blocks=[
            Block(
                block_id=f"{doc_id}:b0000:paragraph",
                type=BlockType.paragraph,
                text="Hello",
                anchor=Anchor(page=1, bbox=(0.0, 0.0, 100.0, 20.0)),
            )
        ],
        extractions=[
            Extraction(
                field="subject",
                value="Test subject",
                confidence=0.95,
                method="regex",
                evidence_blocks=[f"{doc_id}:b0000:paragraph"],
            )
        ],
        provenance=Provenance(
            parser="email_mime",
            parser_version="0.1.0",
            parsed_at=parsed_at,
            status=ParseStatus.ok,
        ),
    )


def _dump_without_parsed_at(document: Document) -> dict:
    """Return model_dump excluding provenance.parsed_at when present."""
    dumped = document.model_dump(mode="json")
    provenance = dumped.get("provenance")
    if isinstance(provenance, dict) and "parsed_at" in provenance:
        dumped = {
            **dumped,
            "provenance": {k: v for k, v in provenance.items() if k != "parsed_at"},
        }
    return dumped


def test_model_roundtrip() -> None:
    """Document serializes and deserializes with stable fields except parsed_at."""
    doc = _sample_document(make_doc_id(b"model roundtrip"))
    restored = Document.model_validate_json(doc.model_dump_json())
    assert _dump_without_parsed_at(doc) == _dump_without_parsed_at(restored)


def test_doc_id_stable_across_two_runs() -> None:
    """make_doc_id is stable and produces equal dumps for identical documents."""
    doc_id = make_doc_id(b"abc")
    assert make_doc_id(b"abc") == doc_id

    doc_one = _sample_document(doc_id, parsed_at=None)
    doc_two = _sample_document(doc_id, parsed_at=None)
    assert _dump_without_parsed_at(doc_one) == _dump_without_parsed_at(doc_two)
