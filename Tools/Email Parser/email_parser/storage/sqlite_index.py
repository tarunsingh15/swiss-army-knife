"""SQLite index with FTS5 search over stored chunks."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from email_parser.models import Document

_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
  doc_id TEXT PRIMARY KEY,
  root_id TEXT,
  parent_id TEXT,
  relation_to_parent TEXT,
  depth INTEGER,
  source_type TEXT,
  mime_type TEXT,
  sent_at TEXT,
  from_addr TEXT,
  from_domain TEXT,
  subject TEXT,
  byte_size INTEGER,
  page_count INTEGER,
  status TEXT,
  parser_version TEXT,
  metadata_native_json TEXT,
  extractions_json TEXT
);
CREATE TABLE IF NOT EXISTS blocks (
  block_id TEXT PRIMARY KEY,
  doc_id TEXT,
  type TEXT,
  page INTEGER,
  bbox_json TEXT,
  text TEXT
);
CREATE TABLE IF NOT EXISTS chunks (
  chunk_id TEXT PRIMARY KEY,
  root_id TEXT,
  doc_id TEXT,
  source_block_ids_json TEXT,
  text TEXT
);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(chunk_id UNINDEXED, text);
"""


class SqliteIndex:
    """Content index backed by stdlib sqlite3 with FTS5 chunk search."""

    def __init__(self, db_path: Path) -> None:
        """Open or create the index database at db_path."""
        self.db_path = db_path
        self._init()

    def _connect(self) -> sqlite3.Connection:
        """Return a connection with row factory enabled."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self) -> None:
        """Create schema tables if they do not exist."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def upsert_document(self, doc: Document) -> None:
        """Insert or replace one document row."""
        native = doc.metadata.native
        common = doc.metadata.common
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO documents (
                  doc_id, root_id, parent_id, relation_to_parent, depth,
                  source_type, mime_type, sent_at, from_addr, from_domain,
                  subject, byte_size, page_count, status, parser_version,
                  metadata_native_json, extractions_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    doc.doc_id,
                    doc.root_id,
                    doc.parent_id,
                    doc.relation_to_parent.value if doc.relation_to_parent else None,
                    doc.depth,
                    doc.source_type.value,
                    doc.mime_type,
                    native.date_utc,
                    native.from_addr,
                    native.from_domain,
                    native.subject,
                    common.byte_size,
                    common.page_count,
                    doc.provenance.status.value,
                    doc.provenance.parser_version,
                    json.dumps(native.model_dump(mode="json"), sort_keys=True),
                    json.dumps(
                        [item.model_dump(mode="json") for item in doc.extractions],
                        sort_keys=True,
                    ),
                ),
            )

    def upsert_blocks(self, doc: Document) -> None:
        """Insert or replace block rows for a document."""
        with self._connect() as conn:
            for block in doc.blocks:
                page = block.anchor.page if block.anchor else None
                bbox_json = (
                    json.dumps(block.anchor.bbox, sort_keys=True)
                    if block.anchor and block.anchor.bbox is not None
                    else None
                )
                conn.execute(
                    """
                    INSERT OR REPLACE INTO blocks (
                      block_id, doc_id, type, page, bbox_json, text
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        block.block_id,
                        doc.doc_id,
                        block.type.value,
                        page,
                        bbox_json,
                        block.text,
                    ),
                )

    def upsert_chunks(self, chunks: list[dict]) -> None:
        """Insert or replace chunk rows and refresh FTS entries."""
        with self._connect() as conn:
            for chunk in chunks:
                chunk_id = chunk["chunk_id"]
                conn.execute("DELETE FROM chunks_fts WHERE chunk_id = ?", (chunk_id,))
                conn.execute(
                    """
                    INSERT OR REPLACE INTO chunks (
                      chunk_id, root_id, doc_id, source_block_ids_json, text
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        chunk_id,
                        chunk.get("root_id"),
                        chunk.get("doc_id"),
                        json.dumps(chunk.get("source_block_ids", []), sort_keys=True),
                        chunk.get("text", ""),
                    ),
                )
                conn.execute(
                    "INSERT INTO chunks_fts (chunk_id, text) VALUES (?, ?)",
                    (chunk_id, chunk.get("text", "")),
                )

    def search_chunks(self, query: str, limit: int = 20) -> list[dict]:
        """Return chunks matching an FTS5 query on chunk text."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT c.chunk_id, c.root_id, c.doc_id, c.source_block_ids_json, c.text
                FROM chunks_fts AS fts
                JOIN chunks AS c ON c.chunk_id = fts.chunk_id
                WHERE chunks_fts MATCH ?
                LIMIT ?
                """,
                (query, limit),
            ).fetchall()
        results: list[dict] = []
        for row in rows:
            results.append(
                {
                    "chunk_id": row["chunk_id"],
                    "root_id": row["root_id"],
                    "doc_id": row["doc_id"],
                    "source_block_ids": json.loads(row["source_block_ids_json"] or "[]"),
                    "text": row["text"],
                }
            )
        return results

    def document_count(self) -> int:
        """Return the number of indexed documents."""
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS n FROM documents").fetchone()
        return int(row["n"]) if row else 0
