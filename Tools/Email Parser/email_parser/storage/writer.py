"""Filesystem writer for parsed document artifacts."""

from __future__ import annotations

import json
from pathlib import Path

from email_parser.config import load_settings
from email_parser.ids import content_hash, hash_prefix
from email_parser.models import Document
from email_parser.storage.paths import StoragePaths


def _hex_from_doc_id(doc_id: str) -> str:
    """Return the bare hex digest from a content-addressed doc id."""
    return doc_id.split(":", 1)[-1]


class Store:
    """Materialize parsed artifacts under a content-addressed output layout."""

    def __init__(self, output_dir: Path | None = None, display_prefix: str = "") -> None:
        """Configure output root and optional host-visible path prefix."""
        settings = load_settings()
        self.output_dir = Path(output_dir or settings.output_dir)
        self.display_prefix = display_prefix or settings.display_path_prefix
        self._ensure_layout()

    def _ensure_layout(self) -> None:
        """Create top-level output directories if missing."""
        for name in ("blobs", "documents", "threads", "context", "chunks", "citations", "runs"):
            (self.output_dir / name).mkdir(parents=True, exist_ok=True)

    def _display(self, path: Path) -> str:
        """Map an absolute local path to a host-visible display string."""
        if not self.display_prefix:
            return str(path)
        rel = path.relative_to(self.output_dir)
        prefix = self.display_prefix.rstrip("/")
        return f"{prefix}/{rel.as_posix()}"

    def paths(self, doc_id: str, ext: str = "bin") -> StoragePaths:
        """Return absolute local paths for a document's artifacts."""
        hex_id = _hex_from_doc_id(doc_id)
        hh = hash_prefix(doc_id)
        blob = self.output_dir / "blobs" / hh / f"{hex_id}.{ext}"
        document_json = self.output_dir / "documents" / hh / f"{hex_id}.json"
        context_md = self.output_dir / "context" / f"{doc_id}.md"
        chunks_jsonl = self.output_dir / "chunks" / f"{doc_id}.jsonl"
        citations_dir = self.output_dir / "citations" / doc_id
        return StoragePaths(
            blob=blob,
            document_json=document_json,
            context_md=context_md,
            chunks_jsonl=chunks_jsonl,
            citations_dir=citations_dir,
            display_blob=self._display(blob),
            display_json=self._display(document_json),
        )

    def write_blob(self, raw: bytes, ext: str = "bin") -> Path:
        """Write raw bytes to blobs/<hh>/<sha256>.<ext>; skip if already present."""
        hex_id = content_hash(raw)
        hh = hex_id[:2]
        path = self.output_dir / "blobs" / hh / f"{hex_id}.{ext}"
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(raw)
        return path

    def write_document(self, doc: Document) -> Path:
        """Write a canonical document JSON under documents/<hh>/<hex>.json."""
        paths = self.paths(doc.doc_id)
        paths.document_json.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(doc.model_dump(mode="json"), indent=2, sort_keys=True)
        paths.document_json.write_text(payload, encoding="utf-8")
        return paths.document_json

    def write_context(self, root_id: str, markdown: str) -> Path:
        """Write thread context markdown for a root document."""
        path = self.output_dir / "context" / f"{root_id}.md"
        path.write_text(markdown, encoding="utf-8")
        return path

    def write_chunks(self, root_id: str, chunks: list[dict]) -> Path:
        """Write chunk records as JSONL for a root document."""
        path = self.output_dir / "chunks" / f"{root_id}.jsonl"
        lines = [json.dumps(chunk, sort_keys=True) for chunk in chunks]
        path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        return path

    def write_anchors(self, doc_id: str, anchors: dict) -> Path:
        """Write citation anchors JSON for a document."""
        path = self.output_dir / "citations" / doc_id / "anchors.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(anchors, indent=2, sort_keys=True), encoding="utf-8")
        return path

    def start_run(self, run_id: str) -> Path:
        """Create runs/<run_id>/ and an empty append-only log.jsonl."""
        run_dir = self.output_dir / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        log_path = run_dir / "log.jsonl"
        log_path.touch(exist_ok=True)
        return run_dir

    def append_log(self, run_id: str, event: dict) -> None:
        """Append one JSON event line to a run log."""
        log_path = self.output_dir / "runs" / run_id / "log.jsonl"
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True) + "\n")

    def write_run_metrics(self, run_id: str, metrics: dict) -> Path:
        """Write run metrics JSON under runs/<run_id>/metrics.json."""
        path = self.output_dir / "runs" / run_id / "metrics.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(metrics, indent=2, sort_keys=True), encoding="utf-8")
        return path

    def write_manifest(self, data: dict) -> Path:
        """Write the top-level output manifest.json."""
        path = self.output_dir / "manifest.json"
        path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        return path
