"""API tests for the FastAPI web wrapper."""

from __future__ import annotations

import time
from email.message import EmailMessage

import pymupdf
import pytest
from fastapi.testclient import TestClient

from web.jobs import JOBS, JOBS_LOCK


@pytest.fixture(autouse=True)
def _clear_jobs() -> None:
    """Reset the in-memory job store between tests."""
    with JOBS_LOCK:
        JOBS.clear()


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Build a TestClient with an isolated output directory."""
    monkeypatch.setenv("EMAILPARSE_OUTPUT_DIR", str(tmp_path))
    from web.app import create_app

    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


def _make_eml(*, subject: str = "Test Subject", body: str = "Hello world") -> bytes:
    """Build a tiny RFC 822 message for upload tests."""
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = "Alice Example <alice@example.com>"
    msg["To"] = "bob@example.com"
    msg["Date"] = "Mon, 15 Aug 2026 12:00:00 +0000"
    msg.set_content(body)
    return msg.as_bytes()


def _make_pdf() -> bytes:
    """Build a one-page PDF payload."""
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Sample PDF attachment")
    payload = doc.tobytes()
    doc.close()
    return payload


def _wait_for_job(client: TestClient, job_id: str, *, timeout_s: float = 10.0) -> dict:
    """Poll job status until it reaches a terminal state."""
    deadline = time.time() + timeout_s
    last: dict = {}
    while time.time() < deadline:
        response = client.get(f"/jobs/{job_id}")
        assert response.status_code == 200
        last = response.json()
        if last["status"] in {"done", "error", "cancelled"}:
            return last
        time.sleep(0.05)
    raise AssertionError(f"Job {job_id} did not finish: {last}")


def test_health_and_index(client: TestClient) -> None:
    """Health and root endpoints respond."""
    health = client.get("/health").json()
    assert health["ok"] is True
    assert health["containerized"] is False
    assert "ocr_available" in health
    assert "ocr_enabled" in health
    response = client.get("/")
    assert response.status_code == 200
    assert "Email Parser" in response.text


def test_peek_returns_subject(client: TestClient) -> None:
    """POST /peek returns header fields without parsing attachments."""
    eml = _make_eml(subject="Peek Subject")
    response = client.post(
        "/peek",
        files=[("files", ("sample.eml", eml, "message/rfc822"))],
    )
    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["subject"] == "Peek Subject"
    assert payload[0]["sender"] == "Alice Example <alice@example.com>"
    assert payload[0]["message_index"] == 0


def test_job_upload_poll_and_document_endpoints(client: TestClient) -> None:
    """Upload, poll to completion, and read document endpoints."""
    eml = _make_eml(subject="Job Subject")
    create = client.post(
        "/jobs",
        files=[("files", ("sample.eml", eml, "message/rfc822"))],
    )
    assert create.status_code == 200
    job_id = create.json()["job_id"]

    status = _wait_for_job(client, job_id)
    assert status["status"] == "done"
    assert status["document_ids"]

    emails = client.get(f"/jobs/{job_id}/emails").json()
    assert emails
    assert emails[0]["subject"] == "Job Subject"

    doc_id = emails[0]["doc_id"]
    document = client.get(f"/documents/{doc_id}")
    assert document.status_code == 200
    assert document.json()["doc_id"] == doc_id

    detail = client.get(f"/documents/{doc_id}/detail").json()
    assert "storage_paths" in detail
    assert detail["storage_paths"]["document_json"]
    assert detail["storage_paths"]["display_json"]

    context = client.get(f"/documents/{doc_id}/context").json()
    assert "markdown" in context
    assert context["token_count"] >= 0


def test_headerless_eml_upload_counts_as_root_email(client: TestClient) -> None:
    """`.eml` files route to email_mime even when magic sniff is inconclusive."""
    raw = b"This is plain text without RFC 822 headers."
    create = client.post(
        "/jobs",
        files=[("files", ("headerless.eml", raw))],
    )
    assert create.status_code == 200
    job_id = create.json()["job_id"]

    status = _wait_for_job(client, job_id)
    assert status["status"] == "done"
    assert status["metrics"]["root_emails"] == 1

    emails = client.get(f"/jobs/{job_id}/emails").json()
    assert len(emails) == 1


def test_missing_document_returns_404(client: TestClient) -> None:
    """Unknown documents return 404."""
    response = client.get("/documents/sha256:does-not-exist")
    assert response.status_code == 404


def test_unsupported_upload_still_completes_job(client: TestClient) -> None:
    """Unsupported uploads produce unsupported documents but the job completes."""
    response = client.post(
        "/jobs",
        files=[("files", ("weird.docx", b"not-really-a-docx", "application/octet-stream"))],
    )
    assert response.status_code == 200
    job_id = response.json()["job_id"]
    status = _wait_for_job(client, job_id)
    assert status["status"] == "done"


def test_cancel_job(client: TestClient) -> None:
    """POST /jobs/{id}/cancel requests cooperative cancellation."""
    eml = _make_eml(subject="Cancel Subject")
    create = client.post(
        "/jobs",
        files=[("files", ("sample.eml", eml, "message/rfc822"))],
    )
    job_id = create.json()["job_id"]
    cancel = client.post(f"/jobs/{job_id}/cancel")
    assert cancel.status_code == 200
    assert cancel.json()["status"] == "cancelling"


def test_files_blob_content_type_for_pdf(client: TestClient) -> None:
    """GET /files/blob returns PDF bytes with an application/pdf content type."""
    from email_parser.ids import make_doc_id

    pdf = _make_pdf()
    create = client.post(
        "/jobs",
        files=[("files", ("sample.pdf", pdf, "application/pdf"))],
    )
    job_id = create.json()["job_id"]
    status = _wait_for_job(client, job_id)
    assert status["status"] == "done"
    doc_id = make_doc_id(pdf)

    blob = client.get(f"/files/blob/{doc_id}")
    assert blob.status_code == 200
    assert blob.headers["content-type"].startswith("application/pdf")
    assert blob.content.startswith(b"%PDF")


def test_job_events_sse_stream(client: TestClient) -> None:
    """GET /jobs/{id}/events streams SSE until the job finishes."""
    eml = _make_eml(subject="SSE Subject")
    create = client.post(
        "/jobs",
        files=[("files", ("sample.eml", eml, "message/rfc822"))],
    )
    job_id = create.json()["job_id"]

    with client.stream("GET", f"/jobs/{job_id}/events") as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        body = response.read().decode("utf-8")

    assert 'data: {"type": "final"' in body or '"status": "done"' in body


def test_golden_endpoint(client: TestClient) -> None:
    """POST /jobs/golden parses synthetic fixtures when present."""
    response = client.post("/jobs/golden")
    assert response.status_code == 200
    payload = response.json()
    assert "run" in payload
    assert "health" in payload
    assert payload["run"]["files"] > 0


def test_peek_pdf_endpoint(client: TestClient) -> None:
    """POST /peek/pdf returns page_count and needs_ocr for PDF uploads."""
    pdf = _make_pdf()
    response = client.post(
        "/peek/pdf",
        files=[("files", ("sample.pdf", pdf, "application/pdf"))],
    )
    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["filename"] == "sample.pdf"
    assert payload[0]["page_count"] == 1
    assert payload[0]["needs_ocr"] is False


def test_direct_pdf_upload_lists_in_root_documents(client: TestClient) -> None:
    """Direct PDF uploads appear in /jobs/{id}/documents."""
    pdf = _make_pdf()
    create = client.post(
        "/jobs",
        files=[("files", ("sample.pdf", pdf, "application/pdf"))],
    )
    assert create.status_code == 200
    job_id = create.json()["job_id"]
    status = _wait_for_job(client, job_id)
    assert status["status"] == "done"

    documents = client.get(f"/jobs/{job_id}/documents").json()
    assert len(documents) == 1
    row = documents[0]
    assert row["kind"] == "pdf"
    assert row["label"] == "sample.pdf"
    assert row["needs_ocr"] is False
    assert row["ocr_used"] is False
