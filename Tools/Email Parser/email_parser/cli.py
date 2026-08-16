"""Command-line interface for the email parser."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import typer

app = typer.Typer(help="Parse emails and PDF attachments into citation-anchored JSON.")

_METRICS_FILENAME = "metrics.json"
_DOCUMENTS_DIRNAME = "documents"
_EXCLUDED_DOC_KEYS = frozenset({"parsed_at"})


def _load_json(path: Path) -> Any:
    """Load JSON from a file path."""
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_metrics_path(path: Path) -> Path | None:
    """Return a metrics.json path when the argument points at one."""
    if path.is_file() and path.name == _METRICS_FILENAME:
        return path
    if path.is_dir():
        candidate = path / _METRICS_FILENAME
        if candidate.is_file():
            return candidate
    return None


def _resolve_documents_dir(path: Path) -> Path | None:
    """Return a documents tree directory when present under or at path."""
    if path.is_dir() and path.name == _DOCUMENTS_DIRNAME:
        return path
    if path.is_dir():
        nested = path / _DOCUMENTS_DIRNAME
        if nested.is_dir():
            return nested
    return None


def _normalize_document(payload: dict[str, Any]) -> dict[str, Any]:
    """Drop volatile provenance fields before comparing document JSON."""
    normalized = json.loads(json.dumps(payload, sort_keys=True))
    provenance = normalized.get("provenance")
    if isinstance(provenance, dict):
        normalized["provenance"] = {
            key: value for key, value in provenance.items() if key not in _EXCLUDED_DOC_KEYS
        }
    return normalized


def _collect_documents(documents_dir: Path) -> dict[str, dict[str, Any]]:
    """Load all document JSON files under a documents/ tree keyed by doc_id."""
    documents: dict[str, dict[str, Any]] = {}
    for json_path in sorted(documents_dir.rglob("*.json")):
        payload = _load_json(json_path)
        doc_id = payload.get("doc_id")
        if not isinstance(doc_id, str):
            doc_id = f"sha256:{json_path.stem}"
        documents[doc_id] = payload
    return documents


def _metrics_diff(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    """Return a shallow JSON diff of two metric objects."""
    keys = sorted(set(left) | set(right))
    diff: dict[str, Any] = {"added_keys": [], "removed_keys": [], "changed": {}}
    for key in keys:
        if key not in left:
            diff["added_keys"].append(key)
        elif key not in right:
            diff["removed_keys"].append(key)
        elif left[key] != right[key]:
            diff["changed"][key] = {"a": left[key], "b": right[key]}
    if not diff["added_keys"] and not diff["removed_keys"] and not diff["changed"]:
        return {}
    return diff


def _document_tree_diff(
    left: dict[str, dict[str, Any]],
    right: dict[str, dict[str, Any]],
) -> dict[str, list[str] | dict[str, list[str]]]:
    """Compare two document trees by doc_id and normalized JSON payload."""
    left_ids = set(left)
    right_ids = set(right)
    added = sorted(right_ids - left_ids)
    removed = sorted(left_ids - right_ids)
    changed: list[str] = []
    for doc_id in sorted(left_ids & right_ids):
        if _normalize_document(left[doc_id]) != _normalize_document(right[doc_id]):
            changed.append(doc_id)
    return {"added": added, "removed": removed, "changed": changed}


def _compare_paths(run_a: Path, run_b: Path) -> dict[str, Any]:
    """Build a combined comparison report for two run or document paths."""
    report: dict[str, Any] = {"a": str(run_a), "b": str(run_b)}

    metrics_a_path = _resolve_metrics_path(run_a)
    metrics_b_path = _resolve_metrics_path(run_b)
    if metrics_a_path and metrics_b_path:
        metrics_diff = _metrics_diff(_load_json(metrics_a_path), _load_json(metrics_b_path))
        if metrics_diff:
            report["metrics"] = metrics_diff
        else:
            report["metrics"] = "identical"

    docs_a_dir = _resolve_documents_dir(run_a)
    docs_b_dir = _resolve_documents_dir(run_b)
    if docs_a_dir and docs_b_dir:
        report["documents"] = _document_tree_diff(
            _collect_documents(docs_a_dir),
            _collect_documents(docs_b_dir),
        )
    elif docs_a_dir or docs_b_dir:
        report["documents"] = {
            "error": "both paths must expose a documents/ tree to compare doc_ids"
        }

    if "metrics" not in report and "documents" not in report:
        report["error"] = (
            "expected runs/<id>, metrics.json, or output/documents directories"
        )
    return report


@app.command()
def version() -> None:
    """Print the package version."""
    from email_parser import __version__

    typer.echo(__version__)


@app.command("metrics")
def metrics_cmd(
    corpus: Path = typer.Option(Path("tests/fixtures/synthetic")),
) -> None:
    """Print Tier A/B metrics for a corpus directory of .eml files."""
    from email_parser.file_parsers.base import Blob
    from email_parser.metrics.health_metrics import compute_health_metrics
    from email_parser.metrics.run_metrics import compute_run_metrics
    from email_parser.pipeline import process

    eml_paths = sorted(corpus.glob("*.eml"))
    started = time.perf_counter()
    documents = []
    for eml_path in eml_paths:
        documents.extend(
            process(Blob(raw=eml_path.read_bytes(), filename=eml_path.name))
        )
    elapsed_s = time.perf_counter() - started

    payload = {
        "run": compute_run_metrics(documents, elapsed_s=elapsed_s),
        "health": compute_health_metrics(documents),
    }
    typer.echo(json.dumps(payload, indent=2, sort_keys=True))


@app.command()
def parse(
    paths: list[Path] = typer.Argument(...),
    output: Path | None = typer.Option(None, "--output", "-o"),
) -> None:
    """Parse files and write artifacts under output/."""
    from email_parser.metrics.health_metrics import compute_health_metrics
    from email_parser.metrics.run_metrics import compute_run_metrics
    from email_parser.run import parse_and_store
    from email_parser.storage.writer import Store

    if output is not None:
        os.environ["EMAILPARSE_OUTPUT_DIR"] = str(output.expanduser().resolve())

    missing = [path for path in paths if not path.exists()]
    if missing:
        raise typer.BadParameter(f"paths not found: {', '.join(str(path) for path in missing)}")

    resolved = [path.resolve() for path in paths]
    started = time.perf_counter()
    run_id, documents = parse_and_store(resolved)
    elapsed_s = time.perf_counter() - started
    metrics = {
        "run": compute_run_metrics(documents, elapsed_s=elapsed_s),
        "health": compute_health_metrics(documents),
    }
    Store().write_run_metrics(run_id, metrics)
    typer.echo(f"run_id={run_id}")
    typer.echo(f"documents={len(documents)}")


@app.command()
def compare(
    run_a: Path = typer.Argument(..., help="runs/<id> dir or metrics.json"),
    run_b: Path = typer.Argument(...),
) -> None:
    """Print changed doc_ids and a JSON diff of two run metric files or document trees."""
    if not run_a.exists():
        raise typer.BadParameter(f"path not found: {run_a}")
    if not run_b.exists():
        raise typer.BadParameter(f"path not found: {run_b}")

    report = _compare_paths(run_a.resolve(), run_b.resolve())
    documents = report.get("documents")
    if isinstance(documents, dict) and "added" in documents:
        typer.echo("Document doc_ids:")
        typer.echo(f"  added:   {len(documents['added'])}")
        for doc_id in documents["added"]:
            typer.echo(f"    + {doc_id}")
        typer.echo(f"  removed: {len(documents['removed'])}")
        for doc_id in documents["removed"]:
            typer.echo(f"    - {doc_id}")
        typer.echo(f"  changed: {len(documents['changed'])}")
        for doc_id in documents["changed"]:
            typer.echo(f"    ~ {doc_id}")

    typer.echo(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    app()
