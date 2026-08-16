"""Tests for the synthetic fixture generator."""

from __future__ import annotations

from pathlib import Path

from tests.fixtures.generate import generate_all


def _file_bytes_map(directory: Path) -> dict[str, bytes]:
    """Map relative paths to file bytes for deterministic comparison."""
    return {
        str(path.relative_to(directory)): path.read_bytes()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


def test_generator_is_deterministic(tmp_path: Path) -> None:
    """Running generate_all twice must produce identical bytes."""
    dir_one = tmp_path / "run_one"
    dir_two = tmp_path / "run_two"
    generate_all(dir_one)
    generate_all(dir_two)
    assert _file_bytes_map(dir_one) == _file_bytes_map(dir_two)


def test_at_least_15_emails_with_truth(tmp_path: Path) -> None:
    """Generator must emit at least 15 .eml files each with a truth sidecar."""
    generate_all(tmp_path)
    eml_files = sorted(tmp_path.glob("*.eml"))
    assert len(eml_files) >= 15
    for eml_path in eml_files:
        truth_path = tmp_path / f"{eml_path.stem}.truth.json"
        assert truth_path.exists(), f"missing truth sidecar for {eml_path.name}"
