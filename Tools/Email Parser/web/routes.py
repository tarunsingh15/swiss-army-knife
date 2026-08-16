"""HTTP routes for the email parser web API."""

from __future__ import annotations

import asyncio
import json
import mimetypes
import platform
import subprocess
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse
from pydantic import BaseModel

from email_parser.ai_context.citations import render_thumbnail
from email_parser.ai_context.context_view import render_context
from email_parser.config import load_settings
from email_parser.ids import hash_prefix
from email_parser.models import Document
from email_parser.run import root_emails
from email_parser.storage.sqlite_index import SqliteIndex
from email_parser.storage.writer import Store
from web.jobs import JOBS, JOBS_LOCK, Job, get_job, parse_one, run_job
from web.peek import peek_headers

router = APIRouter()


class RevealRequest(BaseModel):
    """Request body for revealing a stored file in the host file manager."""

    doc_id: str


def _sse_response(request: Request, generator):
    """Return an SSE response using the best available backend."""
    try:
        from fastapi.sse import EventSourceResponse

        return EventSourceResponse(generator, request=request)
    except ImportError:
        pass
    try:
        from sse_starlette.sse import EventSourceResponse as StarletteEventSourceResponse

        return StarletteEventSourceResponse(generator)
    except ImportError:
        pass

    async def stream():
        async for payload in generator:
            if isinstance(payload, dict):
                yield f"data: {json.dumps(payload, sort_keys=True)}\n\n"
            else:
                yield payload

    return StreamingResponse(stream(), media_type="text/event-stream")


def _storage_paths_dict(store: Store, doc_id: str, doc: Document | None = None) -> dict[str, str]:
    """Return display-friendly storage path fields for one document."""
    ext = "bin"
    if doc is not None:
        filename = doc.metadata.common.filename or ""
        if "." in filename:
            ext = filename.rsplit(".", 1)[-1][:8]
        elif doc.mime_type == "application/pdf":
            ext = "pdf"
        elif doc.mime_type in {"message/rfc822", "message/rfc2822"}:
            ext = "eml"
    paths = store.paths(doc_id, ext=ext)
    return {
        "blob": str(paths.blob),
        "document_json": str(paths.document_json),
        "display_blob": paths.display_blob,
        "display_json": paths.display_json,
    }


def _find_blob_path(store: Store, doc_id: str) -> Path | None:
    """Locate a materialized blob file for a document id."""
    hex_id = doc_id.split(":", 1)[-1]
    hh = hash_prefix(doc_id)
    blob_dir = store.output_dir / "blobs" / hh
    if not blob_dir.exists():
        return None
    matches = sorted(blob_dir.glob(f"{hex_id}.*"))
    return matches[0] if matches else None


def _load_document_dict(doc_id: str) -> dict | None:
    """Load a document from in-memory jobs or on-disk storage."""
    with JOBS_LOCK:
        for job in JOBS.values():
            for item in job.documents:
                if isinstance(item, dict) and item.get("doc_id") == doc_id:
                    return item
                if isinstance(item, Document) and item.doc_id == doc_id:
                    return item.model_dump(mode="json")

    store = Store()
    json_path = store.paths(doc_id).document_json
    if json_path.exists():
        return json.loads(json_path.read_text(encoding="utf-8"))
    return None


def _load_document(doc_id: str) -> Document | None:
    """Load a Document model from jobs or storage."""
    payload = _load_document_dict(doc_id)
    if payload is None:
        return None
    return Document.model_validate(payload)


def _all_documents_for_job(job: Job) -> list[Document]:
    """Return all documents attached to a job."""
    docs: list[Document] = []
    for item in job.documents:
        if isinstance(item, Document):
            docs.append(item)
        elif isinstance(item, dict):
            docs.append(Document.model_validate(item))
    return docs


def _attachment_count(doc_id: str, documents: list[Document]) -> int:
    """Count child documents attached to a root email."""
    count = 0
    for doc in documents:
        if doc.doc_id == doc_id:
            continue
        if doc.parent_id == doc_id:
            count += 1
        elif doc.root_id == doc_id and doc.parent_id is not None:
            count += 1
    return count


def _count_tokens(text: str) -> int:
    """Count tokens for a context markdown string."""
    try:
        import tiktoken

        encoding = tiktoken.get_encoding("cl100k_base")
        return len(encoding.encode(text))
    except Exception:
        return len(text) // 4


def _children_for_document(doc_id: str, documents: list[Document]) -> list[Document]:
    """Return direct and nested children for a document from an in-memory set."""
    return sorted(
        [
            doc
            for doc in documents
            if doc.doc_id != doc_id
            and (doc.parent_id == doc_id or (doc.root_id == doc_id and doc.parent_id is not None))
        ],
        key=lambda item: (item.depth, item.ordinal, item.doc_id),
    )


def _documents_in_store_for_root(doc_id: str) -> list[Document]:
    """Load child documents for a root from the SQLite index when jobs are empty."""
    settings = load_settings()
    index = SqliteIndex(settings.output_dir / "index.sqlite")
    with index._connect() as conn:
        rows = conn.execute(
            """
            SELECT doc_id FROM documents
            WHERE parent_id = ? OR (root_id = ? AND parent_id IS NOT NULL)
            ORDER BY depth, doc_id
            """,
            (doc_id, doc_id),
        ).fetchall()
    children: list[Document] = []
    for row in rows:
        child = _load_document(row["doc_id"])
        if child is not None:
            children.append(child)
    return children


async def _save_uploads(job_id: str, files: list[UploadFile]) -> list[Path]:
    """Persist uploaded files under output/uploads/<job_id>/."""
    settings = load_settings()
    upload_dir = settings.output_dir / "uploads" / job_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    staged: list[Path] = []
    for upload in files:
        filename = upload.filename or f"upload-{uuid.uuid4().hex}"
        dest = upload_dir / filename
        dest.write_bytes(await upload.read())
        staged.append(dest)
    return staged


@router.get("/")
async def index(request: Request) -> Response:
    """Serve the UI template when present, otherwise a minimal placeholder."""
    templates_dir = Path(__file__).parent / "templates"
    template_path = templates_dir / "index.html"
    if template_path.exists():
        from fastapi.templating import Jinja2Templates

        templates = Jinja2Templates(directory=str(templates_dir))
        return templates.TemplateResponse(request, "index.html", {"request": request})
    return HTMLResponse("Email Parser")


@router.get("/health")
async def health() -> dict[str, bool]:
    """Return basic service health and container detection."""
    return {"ok": True, "containerized": Path("/.dockerenv").exists()}


@router.post("/peek")
async def peek(files: list[UploadFile] = File(...)) -> list[dict]:
    """Return header-only previews for uploaded email files."""
    results: list[dict] = []
    for upload in files:
        raw = await upload.read()
        filename = upload.filename or "upload"
        results.extend(peek_headers(raw, filename))
    return results


@router.post("/jobs/golden")
async def golden_job() -> dict[str, Any]:
    """Parse synthetic fixtures and return lightweight run metrics."""
    fixtures_dir = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "synthetic"
    if not fixtures_dir.is_dir():
        raise HTTPException(status_code=404, detail="Synthetic fixtures not found")

    eml_paths = sorted(fixtures_dir.glob("*.eml"))
    if not eml_paths:
        raise HTTPException(status_code=404, detail="No synthetic .eml fixtures found")

    all_docs: list[Document] = []
    for path in eml_paths:
        doc_dicts = await asyncio.to_thread(parse_one, str(path))
        all_docs.extend(Document.model_validate(item) for item in doc_dicts)

    from web.jobs import _build_run_metrics

    run_metrics = _build_run_metrics(all_docs, len(eml_paths))
    health_metrics = {
        "documents": len(all_docs),
        "emails": len(root_emails(all_docs)),
        "with_warnings": sum(1 for doc in all_docs if doc.provenance.warnings),
        "anchor_blocks": sum(
            1 for doc in all_docs for block in doc.blocks if block.anchor is not None
        ),
    }
    return {"run": run_metrics, "health": health_metrics}


@router.post("/jobs")
async def create_parse_job(request: Request, files: list[UploadFile] = File(...)) -> dict[str, str]:
    """Stage uploads and start a background parse job."""
    if not files:
        raise HTTPException(status_code=400, detail="At least one file is required")
    job_id = uuid.uuid4().hex
    staged = await _save_uploads(job_id, files)
    job = Job(job_id=job_id, status="queued", paths=[str(path) for path in staged])
    with JOBS_LOCK:
        JOBS[job_id] = job
    asyncio.create_task(run_job(job_id, request.app))
    return {"job_id": job_id}


@router.get("/jobs/{job_id}")
async def get_job_status(job_id: str) -> dict[str, Any]:
    """Return job status, metrics, and root document ids."""
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    documents = _all_documents_for_job(job)
    roots = root_emails(documents)
    return {
        "job_id": job.job_id,
        "status": job.status,
        "metrics": job.metrics,
        "document_ids": [doc.doc_id for doc in roots],
    }


@router.get("/jobs/{job_id}/events")
async def job_events(request: Request, job_id: str):
    """Stream job progress events over Server-Sent Events."""
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    async def event_generator():
        seen = 0
        while True:
            if await request.is_disconnected():
                break
            with JOBS_LOCK:
                current_status = job.status
                pending = job.events[seen:]
                seen = len(job.events)
            for event in pending:
                yield {"data": json.dumps(event, sort_keys=True)}
            if current_status in {"done", "cancelled", "error"}:
                final = {"type": "final", "status": current_status, "metrics": job.metrics}
                yield {"data": json.dumps(final, sort_keys=True)}
                break
            await asyncio.sleep(0.05)

    return _sse_response(request, event_generator())


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: str) -> dict[str, str]:
    """Request cooperative cancellation for a running job."""
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    with JOBS_LOCK:
        job.cancel = True
    return {"job_id": job_id, "status": "cancelling"}


@router.get("/jobs/{job_id}/emails")
async def job_emails(job_id: str) -> list[dict]:
    """Return processed root emails for a completed job."""
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    documents = _all_documents_for_job(job)
    emails = root_emails(documents)
    results: list[dict] = []
    for doc in emails:
        native = doc.metadata.native
        results.append(
            {
                "doc_id": doc.doc_id,
                "sender": native.from_addr or native.from_name,
                "date": native.date_utc or native.date_original,
                "subject": native.subject,
                "status": doc.provenance.status.value,
                "attachment_count": _attachment_count(doc.doc_id, documents),
            }
        )
    return results


@router.get("/documents/{doc_id}")
async def get_document(doc_id: str) -> dict:
    """Return the canonical JSON document."""
    payload = _load_document_dict(doc_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return payload


@router.get("/documents/{doc_id}/detail")
async def get_document_detail(doc_id: str) -> dict[str, Any]:
    """Return a document, its children, and storage paths."""
    document = _load_document(doc_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")

    store = Store()
    children_docs: list[Document] = []
    with JOBS_LOCK:
        for job in JOBS.values():
            children_docs.extend(_children_for_document(doc_id, _all_documents_for_job(job)))
    if not children_docs:
        children_docs = _documents_in_store_for_root(doc_id)

    children = [
        {
            "document": child.model_dump(mode="json"),
            "storage_paths": _storage_paths_dict(store, child.doc_id, child),
        }
        for child in children_docs
    ]
    return {
        "document": document.model_dump(mode="json"),
        "children": children,
        "storage_paths": _storage_paths_dict(store, doc_id, document),
    }


@router.get("/documents/{doc_id}/context")
async def get_document_context(doc_id: str) -> dict[str, Any]:
    """Return compact markdown context and token count for a root document."""
    document = _load_document(doc_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")

    settings = load_settings()
    context_path = settings.output_dir / "context" / f"{doc_id}.md"
    if context_path.exists():
        markdown = context_path.read_text(encoding="utf-8")
    else:
        family = [document]
        with JOBS_LOCK:
            for job in JOBS.values():
                for item in _all_documents_for_job(job):
                    if item.root_id == doc_id or item.doc_id == doc_id:
                        if item.doc_id not in {member.doc_id for member in family}:
                            family.append(item)
        markdown = render_context(family, token_budget=settings.token_budget)
    return {"markdown": markdown, "token_count": _count_tokens(markdown)}


@router.get("/documents/{doc_id}/citations/{block_id}/thumbnail.png")
async def citation_thumbnail(doc_id: str, block_id: str) -> Response:
    """Render a PNG thumbnail for a cited PDF block."""
    document = _load_document(doc_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")

    block = next((item for item in document.blocks if item.block_id == block_id), None)
    if block is None or block.anchor is None:
        raise HTTPException(status_code=404, detail="Block not found")

    store = Store()
    blob_path = _find_blob_path(store, doc_id)
    if blob_path is None or not blob_path.exists():
        raise HTTPException(status_code=404, detail="Blob not found")

    page = block.anchor.page or 1
    bbox = block.anchor.bbox
    if bbox is None:
        raise HTTPException(status_code=404, detail="Block has no bbox")

    png = render_thumbnail(blob_path.read_bytes(), page, bbox)
    return Response(content=png, media_type="image/png")


@router.get("/search")
async def search(q: str = "") -> list[dict]:
    """Search indexed chunks with FTS5."""
    settings = load_settings()
    index = SqliteIndex(settings.output_dir / "index.sqlite")
    if not q.strip():
        return []
    return index.search_chunks(q)


@router.get("/files/blob/{doc_id}")
async def get_blob_file(doc_id: str) -> FileResponse:
    """Return raw blob bytes for a document."""
    document = _load_document(doc_id)
    store = Store()
    blob_path = _find_blob_path(store, doc_id)
    if blob_path is None or not blob_path.exists():
        raise HTTPException(status_code=404, detail="Blob not found")

    media_type = document.mime_type if document else "application/octet-stream"
    guessed, _ = mimetypes.guess_type(blob_path.name)
    if guessed:
        media_type = guessed
    return FileResponse(blob_path, media_type=media_type, filename=blob_path.name)


@router.get("/files/json/{doc_id}")
async def get_json_file(doc_id: str) -> FileResponse:
    """Return the stored document JSON file."""
    store = Store()
    json_path = store.paths(doc_id).document_json
    if not json_path.exists():
        raise HTTPException(status_code=404, detail="Document JSON not found")
    return FileResponse(json_path, media_type="application/json", filename=json_path.name)


@router.post("/files/reveal")
async def reveal_file(body: RevealRequest) -> dict[str, str]:
    """Reveal a stored blob in the host file manager when supported."""
    if Path("/.dockerenv").exists():
        raise HTTPException(status_code=501, detail="Reveal is unavailable in containers")

    store = Store()
    blob_path = _find_blob_path(store, body.doc_id)
    if blob_path is None or not blob_path.exists():
        json_path = store.paths(body.doc_id).document_json
        target = json_path if json_path.exists() else None
    else:
        target = blob_path

    if target is None:
        raise HTTPException(status_code=404, detail="File not found")

    if platform.system() == "Darwin":
        subprocess.run(["open", "-R", str(target)], check=False)
        return {"doc_id": body.doc_id, "path": str(target)}

    raise HTTPException(status_code=501, detail="Reveal is only supported on macOS")
