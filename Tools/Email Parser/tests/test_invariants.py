"""Corpus-wide invariant checks over synthetic fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from email_parser.file_parsers.base import Blob
from email_parser.metrics.health_metrics import check_invariants
from email_parser.pipeline import process

SYNTHETIC_DIR = Path(__file__).parent / "fixtures" / "synthetic"


def _synthetic_eml_paths() -> list[Path]:
    """Return synthetic .eml fixtures, or an empty list when none exist."""
    if not SYNTHETIC_DIR.is_dir():
        return []
    return sorted(SYNTHETIC_DIR.glob("*.eml"))


@pytest.mark.parametrize("eml_path", _synthetic_eml_paths(), ids=lambda path: path.name)
def test_no_orphan_parent_ids(eml_path: Path) -> None:
    """Parsed documents must not reference missing parent IDs."""
    documents = process(Blob(raw=eml_path.read_bytes(), filename=eml_path.name))
    violations = check_invariants(documents)
    orphan_violations = [item for item in violations if item.startswith("orphan parent_id")]
    assert not orphan_violations
