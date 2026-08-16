"""Path helpers for materialized storage artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class StoragePaths:
    """Absolute local paths (and host-visible display strings) for one document."""

    blob: Path
    document_json: Path
    context_md: Path
    chunks_jsonl: Path
    citations_dir: Path
    display_blob: str
    display_json: str
