"""Tests for filesystem storage and the SQLite index."""

from __future__ import annotations

from email_parser.ids import make_doc_id
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
from email_parser.storage.sqlite_index import SqliteIndex
from email_parser.storage.writer import Store


def _sample_document(raw: bytes) -> Document:
    """Build a minimal Document for storage tests."""
    doc_id = make_doc_id(raw)
    return Document(
        doc_id=doc_id,
        source_type=SourceType.email,
        mime_type="message/rfc822",
        root_id=doc_id,
        metadata=DocumentMetadata(
            common=CommonMetadata(byte_size=len(raw)),
            native=NativeMetadata(
                from_addr="sender@example.com",
                from_domain="example.com",
                subject="Kickoff planning",
            ),
        ),
        blocks=[
            Block(
                block_id=f"{doc_id}:b0000:paragraph",
                type=BlockType.paragraph,
                text="Kickoff fee discussion",
            )
        ],
        provenance=Provenance(
            parser="email_mime",
            parser_version="0.1.0",
            status=ParseStatus.ok,
        ),
    )


def test_idempotent_document_write(tmp_path) -> None:
    """Writing the same document twice yields identical bytes and one index row."""
    raw = b"storage idempotent payload"
    store = Store(output_dir=tmp_path)
    doc = _sample_document(raw)
    index = SqliteIndex(tmp_path / "index.sqlite")

    first_path = store.write_document(doc)
    first_bytes = first_path.read_bytes()
    index.upsert_document(doc)
    index.upsert_blocks(doc)

    second_path = store.write_document(doc)
    second_bytes = second_path.read_bytes()
    index.upsert_document(doc)
    index.upsert_blocks(doc)

    assert first_path == second_path
    assert first_bytes == second_bytes
    assert index.document_count() == 1


def test_search_chunks_finds_kickoff(tmp_path) -> None:
    """FTS5 search returns chunks containing the query term."""
    store = Store(output_dir=tmp_path)
    doc = _sample_document(b"chunk search payload")
    index = SqliteIndex(tmp_path / "index.sqlite")

    chunk = {
        "chunk_id": f"{doc.doc_id}:chunk:0001",
        "root_id": doc.root_id,
        "doc_id": doc.doc_id,
        "source_block_ids": [doc.blocks[0].block_id],
        "text": "The kickoff fee is due before launch.",
    }
    store.write_chunks(doc.root_id or doc.doc_id, [chunk])
    index.upsert_chunks([chunk])

    hits = index.search_chunks("kickoff")
    assert len(hits) == 1
    assert hits[0]["chunk_id"] == chunk["chunk_id"]
    assert "kickoff fee" in hits[0]["text"]


def test_paths_and_materialized_files(tmp_path) -> None:
    """paths() resolves under output_dir and written artifacts exist on disk."""
    raw = b"paths materialization payload"
    store = Store(output_dir=tmp_path)
    doc = _sample_document(raw)
    paths = store.paths(doc.doc_id, ext="eml")

    assert paths.blob.is_relative_to(tmp_path)
    assert paths.document_json.is_relative_to(tmp_path)

    store.write_blob(raw, ext="eml")
    store.write_document(doc)

    assert paths.blob.exists()
    assert paths.document_json.exists()


def test_display_prefix_rewrites_paths(tmp_path) -> None:
    """display_* strings use the configured host-visible prefix."""
    doc_id = make_doc_id(b"display prefix payload")
    store = Store(output_dir=tmp_path, display_prefix="/host/output")
    paths = store.paths(doc_id)

    assert paths.display_json.startswith("/host/output")
    assert paths.display_blob.startswith("/host/output")
