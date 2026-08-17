"""In-memory job store and background parse workers."""

from __future__ import annotations

import asyncio
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from email_parser.config import Settings, load_settings
from email_parser.ids import make_doc_id
from email_parser.models import Document
from email_parser.run import parse_file, persist_run, root_emails

JOBS: dict[str, Job] = {}
JOBS_LOCK = threading.Lock()  # Shared by async routes and process-pool workers.


@dataclass
class Job:
    """One uploaded parse job tracked in memory."""

    job_id: str
    status: str  # queued|running|done|cancelled|error
    events: list[dict] = field(default_factory=list)
    documents: list = field(default_factory=list)  # Document objects or dumped dicts
    metrics: dict = field(default_factory=dict)
    cancel: bool = False
    paths: list[str] = field(default_factory=list)  # staged file paths


def parse_one(path: str) -> list[dict]:
    """Parse one staged file and return JSON-serializable document dicts."""
    docs = parse_file(Path(path))
    return [document.model_dump(mode="json") for document in docs]


def create_job(staged_paths: list[Path]) -> Job:
    """Register a new queued job for the given staged upload paths."""
    job_id = uuid.uuid4().hex
    job = Job(
        job_id=job_id,
        status="queued",
        paths=[str(path) for path in staged_paths],
    )
    with JOBS_LOCK:
        JOBS[job_id] = job
    return job


def get_job(job_id: str) -> Job | None:
    """Return a job by id, or None when missing."""
    with JOBS_LOCK:
        return JOBS.get(job_id)


def _append_event(job: Job, event: dict) -> None:
    """Append one SSE event to a job under lock."""
    with JOBS_LOCK:
        job.events.append(event)


def _documents_from_dicts(doc_dicts: list[dict]) -> list[Document]:
    """Rehydrate Document models from dumped dicts."""
    return [Document.model_validate(item) for item in doc_dicts]


async def _parse_path(path_str: str, app: Any) -> list[dict]:
    """Parse one path in the process pool, falling back to in-process on failure."""
    loop = asyncio.get_running_loop()
    pool = app.state.process_pool
    try:
        # CPU-bound parse off the event loop; returns JSON-serializable dicts.
        return await loop.run_in_executor(pool, parse_one, path_str)
    except Exception:
        return await asyncio.to_thread(parse_one, path_str)


def _build_run_metrics(documents: list[Document], file_count: int) -> dict:
    """Compute lightweight run metrics for a completed job."""
    statuses: dict[str, int] = {}
    for doc in documents:
        key = doc.provenance.status.value
        statuses[key] = statuses.get(key, 0) + 1
    roots = root_emails(documents)
    return {
        "files": file_count,
        "documents": len(documents),
        "root_emails": len(roots),
        "status_counts": statuses,
        "max_depth": max((doc.depth for doc in documents), default=0),
    }


async def run_job(job_id: str, app: Any, settings: Settings | None = None) -> None:
    """Parse all staged files for a job, persist artifacts, and update job state."""
    settings = settings or load_settings()
    job = get_job(job_id)
    if job is None:
        return

    with JOBS_LOCK:
        job.status = "running"
    _append_event(job, {"type": "status", "status": "running"})

    all_docs: list[Document] = []
    raw_by_id: dict[str, bytes] = {}

    for path_str in job.paths:
        with JOBS_LOCK:
            if job.cancel:
                job.status = "cancelled"
                _append_event(job, {"type": "status", "status": "cancelled"})
                return

        _append_event(job, {"type": "file_start", "path": Path(path_str).name})

        try:
            doc_dicts = await _parse_path(path_str, app)
            docs = _documents_from_dicts(doc_dicts)
            raw = Path(path_str).read_bytes()
            raw_by_id[make_doc_id(raw)] = raw
            all_docs.extend(docs)

            for doc in docs:
                _append_event(
                    job,
                    {
                        "type": "document",
                        "doc_id": doc.doc_id,
                        "filename": doc.metadata.common.filename,
                        "status": doc.provenance.status.value,
                        "depth": doc.depth,
                    },
                )
            _append_event(job, {"type": "file_done", "path": Path(path_str).name})
        except Exception as exc:
            with JOBS_LOCK:
                job.status = "error"
                job.metrics = {"error": str(exc)}
            _append_event(job, {"type": "error", "message": str(exc)})
            return

        with JOBS_LOCK:
            if job.cancel:
                job.status = "cancelled"
                _append_event(job, {"type": "status", "status": "cancelled"})
                return

    metrics = _build_run_metrics(all_docs, len(job.paths))
    try:
        # run_id doubles as job_id so output/runs/<job_id>/ matches the web job.
        persist_run(
            all_docs,
            raw_by_id=raw_by_id,
            settings=settings,
            run_id=job_id,
            metrics=metrics,
        )
    except Exception as exc:
        with JOBS_LOCK:
            job.status = "error"
            job.metrics = {"error": str(exc)}
        _append_event(job, {"type": "error", "message": str(exc)})
        return

    with JOBS_LOCK:
        job.documents = [doc.model_dump(mode="json") for doc in all_docs]
        job.metrics = metrics
        job.status = "done"
    _append_event(job, {"type": "status", "status": "done", "metrics": metrics})
