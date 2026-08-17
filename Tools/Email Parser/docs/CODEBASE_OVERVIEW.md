# Codebase Overview

Developer map of the Email Parser project. For end-user setup and API usage, see [USER_MANUAL.md](USER_MANUAL.md). For adding parsers, see [ADDING_A_PARSER.md](ADDING_A_PARSER.md).

## High-level flow

```
Upload / CLI path
      │
      ▼
  Blob (raw bytes + filename)
      │
      ▼
  pipeline.process()  ──worklist──►  resolve_parser()  ──►  Parser.parse()
      │                                      │
      │                                      └── child Blobs enqueued
      ▼
  list[Document]  (all nodes in the tree)
      │
      ▼
  persist_run()  ──►  Store (JSON, blobs, context, chunks)
                 └──►  SqliteIndex (documents, blocks, FTS)
```

Every file type parser emits the same `Document` shape. Parent/child relationships are **document-level** (`parent_id`, `relation_to_parent`), not block-level. Blocks link to child documents only via `child_doc_id` (e.g. inline `cid:` images).

## Directory layout

| Path | Role |
|------|------|
| `email_parser/` | Core library: parse pipeline, parsers, storage, AI context, CLI |
| `web/` | FastAPI app, job queue, static UI |
| `tests/` | Pytest suite, synthetic fixtures, snapshots |
| `docs/` | User manual, metrics, parser guide, this file |
| `scripts/` | Fixture fetch helpers |
| `output/` | Default artifact root (`EMAILPARSE_OUTPUT_DIR`) |

Sibling projects:

| Project | Role |
|---------|------|
| [`Tools/pdf_tool`](../pdf_tool/) | Born-digital PDF extraction (generic models, PyMuPDF engine, CLI) |
| [`Tools/document_parser`](../document_parser/) | Optional scanned-PDF OCR (PaddleOCR backend); installed via `uv sync --extra ocr` |

## Standalone PDF tool (`Tools/pdf_tool/`)

Generic PDF extraction, usable without the email parser:

| Module | Purpose |
|--------|---------|
| `models.py` | `PdfBlock`, `PdfMetadata`, `PdfParseResult`, `EmbeddedFile` |
| `pymupdf_engine.py` | **Only module that imports PyMuPDF** |
| `cli.py` | `pdf-tool parse <file.pdf>` and `pdf-tool version` |

Public API (`from pdf_tool import parse_pdf, search_quote, render_thumbnail, is_pdf`).

The email parser integrates via a thin adapter at `email_parser/file_parsers/pdf_pymupdf.py` that maps `pdf_tool` results into `Document` / `Block` models. When born-digital extraction is insufficient (`needs_ocr`, empty blocks, or chars below `EMAILPARSE_OCR_MIN_CHARS`), the adapter may fall back to `document_parser` **only** for PDF attachments and direct PDF uploads — never for born-digital PDFs that already extracted text.

## Standalone OCR tool (`Tools/document_parser/`)

Optional scanned-PDF OCR, installed with `uv sync --extra ocr`:

| Module | Purpose |
|--------|---------|
| `models.py` | `DocBlock`, `DocMetadata`, `DocParseResult` — mirrors pdf_tool field names |
| `raster.py` | **Only module that imports PyMuPDF** in document_parser |
| `ocr/paddle_engine.py` | **Only module that imports PaddleOCR** |
| `pdf.py` | Orchestration: rasterize → OCR → paragraph blocks |
| `cli.py` | `doc-parser parse <file.pdf>` |

Public API (`from document_parser import parse_pdf, is_available`). When the package or PaddleOCR is missing, `is_available()` is `False` and the email-parser adapter keeps the pdf_tool result with a provenance warning.

## Core library (`email_parser/`)

### `models.py`

Canonical data contracts:

- **`Document`** — one parsed file or MIME part; carries lineage (`root_id`, `parent_id`, `depth`, `path`), `metadata`, `blocks[]`, `provenance`
- **`Block`** — ordered content unit (`paragraph`, `quoted_history`, `image_ref`, etc.); optional `anchor` for PDF citations; optional `child_doc_id` for inline images
- **`RelationType`** — how a child document attaches: `attachment`, `inline_image`, `forwarded_message`, etc.
- **`SourceType`** — high-level family: `email`, `pdf`, `text`, `image`, `unknown`

`root_emails()` counts documents where `parent_id is None` **and** `source_type == email`. Mis-routed `.eml` files parsed as `text` will not appear in the web UI email list.

`root_documents()` returns top-level emails **and** direct-upload PDFs (`source_type` in `{email, pdf}`). The web UI sidebar uses this list.

### `ids.py`

Content-addressed, deterministic identifiers:

- `make_doc_id(raw)` → `sha256:<hex>`
- `make_block_id(doc_id, ordinal, type)` → stable block id (no randomness)
- `hash_prefix(doc_id)` → first two hex chars for directory sharding

### `config.py`

Settings from `EMAILPARSE_*` environment variables: `output_dir`, `max_depth`, `max_fanout`, `pdf_engine`, `token_budget`, and OCR flags (`ocr_enabled`, `ocr_dpi`, `ocr_min_chars`).

### `pipeline.py`

Iterative BFS over a blob worklist:

1. Sniff MIME and resolve a parser
2. Parse blob → `Document` + `child_blobs`
3. Stamp lineage fields (`root_id`, `parent_id`, `depth`, `path`)
4. Enqueue children with incremented depth

Guards:

- **`max_depth`** — emits a failed stub document when exceeded
- **`max_fanout`** — truncates excess children with a warning
- **Content-hash dedup** — identical byte payloads are parsed once per run

### `run.py`

Orchestration layer used by CLI and web jobs:

- `parse_file()` — read disk → `process()`
- `persist_run()` — write all artifacts and index rows for one run
- `root_emails()` — filter top-level email documents (metrics backward compat)
- `root_documents()` — filter top-level emails and direct-upload PDFs for UI listing
- `parse_and_store()` — batch CLI entry point

`persist_run()` builds per-root **context markdown** and **chunks** from each document family sharing a `root_id`.

### `file_parsers/`

Plug-in parsers implementing the `Parser` protocol in `base.py`:

| Module | Parser name | Handles |
|--------|-------------|---------|
| `email_mime.py` | `email_mime` | RFC 822 / MIME; emits child blobs for attachments, forwards, inline images |
| `pdf_pymupdf.py` | `pdf_pymupdf` | **Adapter** — delegates to `pdf_tool`; optional `document_parser` OCR fallback via `should_run_ocr()` |
| `text_plain.py` | `text_plain` | Plain text attachments |

#### `registry.py`

Parser discovery and dispatch:

- Loads built-ins + setuptools entry points (`email_parser.parsers`)
- `sniff_mime()` — puremagic magic bytes, then declared type, then `application/octet-stream`
- `resolve_parser()` — highest `priority` wins; PDF magic overrides mislabeled MIME; `.eml`/`.mime` filenames force `message/rfc822` unless bytes are PDF

#### `email_mime.py`

Email-specific logic:

- Header extraction into `NativeMetadata`
- `_looks_like_email_sniff()` — RFC 822 detection for Gmail-style exports (`Delivered-To:` prefix, long `Received` chains)
- `_choose_alternative_part()` — one canonical body (HTML preferred over plain)
- `_collect_child_blobs()` — attachments, forwards, inline images with `RelationType`
- Quote detection → `quoted_history` blocks (quotequail + `>` fallback)
- `image_ref` blocks with `child_doc_id` pointing at inline image documents

### `storage/`

| Module | Purpose |
|--------|---------|
| `writer.py` (`Store`) | Filesystem layout: `blobs/`, `documents/`, `context/`, `chunks/`, `citations/`, `runs/` |
| `sqlite_index.py` | SQLite index for documents, blocks, chunks, FTS5 search |
| `paths.py` | `StoragePaths` dataclass for resolved artifact paths |

Documents and blobs are sharded by `hash_prefix(doc_id)` (first two hex digits).

### `ai_context/`

Downstream artifacts for RAG / LLM workflows (not used during parse itself):

| Module | Purpose |
|--------|---------|
| `context_view.py` | Render compact markdown thread context with token budget trimming |
| `chunker.py` | Split document families into chunk records |
| `citations.py` | Extract anchors; render PDF block thumbnails |

### `metrics/`

| Module | Purpose |
|--------|---------|
| `run_metrics.py` | Per-run counts: files, documents, depth, status histogram |
| `health_metrics.py` | Structural quality: anchor coverage, CID resolution, invariant violations |
| `accuracy_metrics.py` | Corpus comparison against `.truth.json` fixtures |

### `cli.py`

Typer CLI: `parse`, `metrics`, `compare`, `version`. Writes to `output/` and prints JSON summaries.

## Web layer (`web/`)

### `app.py`

FastAPI factory. Creates a `ProcessPoolExecutor` (2 workers) for CPU-bound parsing off the event loop.

### `jobs.py`

In-memory job store (`JOBS` dict + `JOBS_LOCK`):

1. Stage uploads under `output/uploads/<job_id>/`
2. `run_job()` parses each file (process pool or thread fallback)
3. Append SSE events (`file_start`, `document`, `status`, `final`)
4. `persist_run()` with `run_id=job_id`
5. Store serialized documents on the job for API reads

Cooperative cancel via `job.cancel` flag checked between files.

### `routes.py`

HTTP API and UI:

| Endpoint | Purpose |
|----------|---------|
| `GET /` | Serve `index.html` |
| `GET /health` | Liveness + `ocr_available`, `ocr_enabled` |
| `POST /peek` | Header-only preview without full parse |
| `POST /peek/pdf` | PDF metadata preview: page count, `needs_ocr`, filename |
| `POST /jobs` | Upload files, start background job |
| `GET /jobs/{id}` | Status + metrics |
| `GET /jobs/{id}/events` | SSE progress stream (`response_class=EventSourceResponse`) |
| `GET /jobs/{id}/emails` | Root email summaries (backward compat; same rows as `/documents` for emails) |
| `GET /jobs/{id}/documents` | Root emails + direct-upload PDFs for results sidebar |
| `GET /documents/{id}` | Canonical document JSON |
| `GET /documents/{id}/detail` | Document + children + storage paths |
| `GET /documents/{id}/context` | Markdown context + token count |
| `GET /documents/{id}/citations/{block_id}/thumbnail.png` | PDF citation thumbnail |
| `POST /jobs/golden` | Parse synthetic test fixtures |

Document loading checks in-memory jobs first, then on-disk `Store`.

### `peek.py`

Lightweight RFC 822 header extraction for the upload preview UI (subject, sender, date) without running the full pipeline.

### `static/`

Vanilla JS UI (`app.js`, `app.css`): drag-drop upload for `.eml` and `.pdf`, PDF peek via `/peek/pdf`, SSE job progress, processed-items sidebar via `/jobs/{id}/documents`, OCR/scanned badges when applicable.

## Tests (`tests/`)

| Area | Key files |
|------|-----------|
| API / SSE | `test_api.py` |
| Parser routing | `test_registry.py` |
| Email MIME | `test_mime_structure.py`, `test_cid_linkage.py`, `test_quoting.py` |
| PDF | `test_pdf_pymupdf.py` (OCR gate + `@pytest.mark.ocr` integration) |
| Determinism | `test_determinism.py`, `test_snapshots.py` |
| Invariants | `test_invariants.py` |
| Storage | `test_storage.py` |

Synthetic fixtures live in `tests/fixtures/synthetic/` (generated locally, gitignored).

## Key design decisions

1. **Deterministic IDs** — content hashes, no timestamps in `doc_id` or `block_id`
2. **One canonical body** — `multipart/alternative` picks HTML or plain, not both
3. **Quoted history preserved** — `quoted_history` blocks, not stripped
4. **Document tree, flat blocks** — parent relations on `Document`, not on `Block`
5. **Parser plug-in contract frozen** — `Blob`, `ParseContext`, `ParseResult` in `base.py`
6. **Web jobs are ephemeral** — in-memory only; durable state is under `output/`

## Related docs

- [USER_MANUAL.md](USER_MANUAL.md) — setup, output layout, API reference
- [ADDING_A_PARSER.md](ADDING_A_PARSER.md) — implement a new `Parser`
- [METRICS.md](METRICS.md) — metric definitions
- [MANUAL_STEPS.md](MANUAL_STEPS.md) — hands-on verification checklist
