"""Stable content-addressed identifiers for documents and blocks."""

from __future__ import annotations

import hashlib
import re


def content_hash(raw_bytes: bytes) -> str:
    """Return the hex SHA-256 of raw bytes."""
    return hashlib.sha256(raw_bytes).hexdigest()


def make_doc_id(raw_bytes: bytes) -> str:
    """Return a content-addressed document id: sha256:<hex>."""
    return f"sha256:{content_hash(raw_bytes)}"


def hash_prefix(doc_id: str, width: int = 2) -> str:
    """Return the first `width` hex chars after the sha256: prefix for sharding."""
    hex_part = doc_id.split(":", 1)[-1]
    return hex_part[:width]


def make_block_id(doc_id: str, ordinal: int, block_type: str) -> str:
    """Return a stable block id derived from document, position, and type.

    Never use random or wall-clock values.
    """
    safe_type = re.sub(r"[^a-z0-9_]+", "_", block_type.lower())
    return f"{doc_id}:b{ordinal:04d}:{safe_type}"
