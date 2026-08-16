"""End-to-end parse, persist, and derive artifacts for one or more files."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from pathlib import Path

from email_parser.ai_context.chunker import chunk_documents
from email_parser.ai_context.citations import anchors_from_document
from email_parser.ai_context.context_view import render_context
from email_parser.config import Settings, load_settings
from email_parser.file_parsers.base import Blob
from email_parser.ids import make_doc_id
from email_parser.models import Document, SourceType
from email_parser.pipeline import process
from email_parser.storage.sqlite_index import SqliteIndex
from email_parser.storage.writer import Store


def _ext_for(blob_name: str | None, mime: str | None) -> str:
    """Pick a blob file extension from name or MIME type."""
    if blob_name and "." in blob_name:
        return blob_name.rsplit(".", 1)[-1][:8]
    if mime == "application/pdf":
        return "pdf"
    if mime in {"message/rfc822", "message/rfc2822"}:
        return "eml"
    return "bin"


def parse_file(
    path: Path,
    settings: Settings | None = None,
    on_progress: Callable[[dict], None] | None = None,
) -> list[Document]:
    """Read one file from disk and run the parse pipeline."""
    raw = path.read_bytes()
    blob = Blob(raw=raw, filename=path.name)
    return process(blob, settings=settings, on_progress=on_progress)


def persist_run(
    documents: list[Document],
    raw_by_id: dict[str, bytes] | None = None,
    settings: Settings | None = None,
    run_id: str | None = None,
    metrics: dict | None = None,
) -> str:
    """Write documents, derived views, and index rows for a completed run."""
    settings = settings or load_settings()
    store = Store(output_dir=settings.output_dir, display_prefix=settings.display_path_prefix)
    index = SqliteIndex(settings.output_dir / "index.sqlite")
    run_id = run_id or uuid.uuid4().hex
    store.start_run(run_id)

    roots = [d for d in documents if d.parent_id is None]
    for root in roots:
        family = [d for d in documents if (d.root_id or d.doc_id) == (root.root_id or root.doc_id)]
        markdown = render_context(family, token_budget=settings.token_budget)
        store.write_context(root.doc_id, markdown)
        chunks = chunk_documents(family)
        store.write_chunks(root.doc_id, chunks)
        index.upsert_chunks(chunks)

    for doc in documents:
        store.write_document(doc)
        index.upsert_document(doc)
        index.upsert_blocks(doc)
        anchors = anchors_from_document(doc)
        store.write_anchors(doc.doc_id, anchors)
        if raw_by_id and doc.doc_id in raw_by_id:
            mime = doc.mime_type
            store.write_blob(raw_by_id[doc.doc_id], ext=_ext_for(doc.metadata.common.filename, mime))

    if metrics is not None:
        store.write_run_metrics(run_id, metrics)
    store.write_manifest(
        {
            "run_id": run_id,
            "doc_count": len(documents),
            "root_count": len(roots),
        }
    )
    return run_id


def parse_and_store(
    paths: list[Path],
    settings: Settings | None = None,
    on_progress: Callable[[dict], None] | None = None,
    run_id: str | None = None,
) -> tuple[str, list[Document]]:
    """Parse many files, persist artifacts, and return (run_id, documents)."""
    settings = settings or load_settings()
    all_docs: list[Document] = []
    raw_by_id: dict[str, bytes] = {}
    for path in paths:
        raw = path.read_bytes()
        blob = Blob(raw=raw, filename=path.name)
        raw_by_id[make_doc_id(raw)] = raw
        docs = process(blob, settings=settings, on_progress=on_progress)
        all_docs.extend(docs)
    rid = persist_run(all_docs, raw_by_id=raw_by_id, settings=settings, run_id=run_id)
    return rid, all_docs


def root_emails(documents: list[Document]) -> list[Document]:
    """Return top-level email documents from a parse result."""
    return [
        d
        for d in documents
        if d.parent_id is None and d.source_type == SourceType.email
    ]
