# Manual Steps

Hands-on checklist for setting up, exercising, and verifying the email parser locally.

## SETUP

1. Install [uv](https://docs.astral.sh/uv/) and Python 3.12+.
2. From the repository root:

```bash
cd "/path/to/Email Parser"
uv sync --extra web --extra dev
```

3. Generate deterministic synthetic fixtures:

```bash
uv run python tests/fixtures/generate.py
```

This writes `.eml` and `.truth.json` pairs under `tests/fixtures/synthetic/`.

4. Optional: set environment variables (defaults shown):

| Variable | Default | Purpose |
|----------|---------|---------|
| `EMAILPARSE_OUTPUT_DIR` | `output` | Artifact root |
| `EMAILPARSE_MAX_DEPTH` | `10` | Nesting cap |
| `EMAILPARSE_MAX_FANOUT` | `200` | Max children per document |
| `EMAILPARSE_TOKEN_BUDGET` | `6000` | Context markdown token budget |

5. Start the web server:

```bash
uv run uvicorn web.app:app --host 127.0.0.1 --port 8000
```

Or with Docker:

```bash
docker compose up --build
```

Open `http://127.0.0.1:8000`.

## BEFORE TESTING

1. Run the automated test suite:

```bash
uv run pytest tests -q
```

2. Confirm synthetic fixtures exist:

```bash
ls tests/fixtures/synthetic/*.eml | wc -l
```

Expect 15 cases (see `tests/fixtures/generate.py`).

3. Ensure `output/` is writable (created on first parse).

4. For snapshot work, note that pytest uses syrupy; do not pass `--snapshot-update` until you have reviewed diffs (see AFTER TESTING).

## DURING TESTING

Use the web UI, CLI, or API. For each scenario, record pass/fail in the Expected column.

**Watching SSE in DevTools**

1. Open DevTools → Network.
2. Submit files in the UI.
3. Filter by `events` or type `EventStream`.
4. Select `GET /jobs/{job_id}/events`.
5. Watch `data:` lines: `file_start`, `document`, `file_done`, final `{type: final, status, metrics}`.

**Run log path**

After a job or CLI parse, inspect:

```
output/runs/<run_id>/log.jsonl
output/runs/<run_id>/metrics.json
```

Web jobs use the job id as `run_id`.

### Scenario checklist

| Task | Steps | Expected |
|------|-------|----------|
| Happy path: mixed synthetic `.eml` corpus | Click **Run golden** or upload all `tests/fixtures/synthetic/*.eml` | Job completes `done`; metrics show multiple root emails; no `error` events |
| No attachment | Upload `plain_no_attachment.eml` | One root email; `attachment_count` 0; body paragraph blocks |
| Five attachments | Upload `five_pdfs.eml` | One root email; five PDF child documents; statuses mostly `ok` |
| PDF inside PDF (depth 2) | Upload `pdf_in_pdf.eml` | Outer PDF + embedded `exhibit.pdf` child; `max_depth` ≥ 2 |
| Forwarded email nested | Upload `forwarded_with_pdf.eml` or `nested_forward_pdf.eml` | Forward relation; inner contract PDF reachable in detail tree |
| HTML cid logo | Upload `html_cid_image.eml` | HTML body preferred; inline PNG child; `image_ref` or inline child linked |
| RFC 2047 subject | Upload `rfc2047_subject.eml` | Subject decoded as `Réunion: contrat`; From display name `José García` |
| Duplicate filenames | Upload `duplicate_filenames.eml` | Two distinct `doc_id` values despite both named `same.pdf` |
| Zero-byte and corrupt PDF | Upload `zero_byte_attachment.eml` and `corrupt_pdf.eml` | Root email parses `ok`; attachment documents `failed` or `warning` with warnings; email not lost |
| Same email twice deduped | `uv run email-parser parse same.eml same.eml` or upload duplicate twice in one job | Pipeline skips identical bytes; single document entry per hash in output |
| Missing Date / empty Subject | Upload `missing_date.eml` and `empty_subject.eml` | `date_utc` null or fallback; empty subject stored without crash |
| `.txt` / `.docx` handled or rejected | Upload a `.txt` file and `weird.docx` (see API test) | Plain text parses as `text` document; `.docx` → `unsupported` job still `done` |
| Empty submit | Click Submit with no files | UI prevents submit or API returns 400 |
| Tab close mid-run | Start large batch; close tab; reopen | Server may continue job; new tab can poll `/jobs/{id}` if id known; otherwise stale |
| Refresh mid-run | Refresh during Processing | SSE reconnects if job id in memory; otherwise return to Upload |

CLI spot checks:

```bash
uv run email-parser metrics --corpus tests/fixtures/synthetic
uv run email-parser parse tests/fixtures/synthetic/single_pdf.eml
```

## AFTER TESTING

1. **Inspect output**

```bash
ls output/documents/*/*.json | head
cat output/manifest.json
sqlite3 output/index.sqlite "SELECT doc_id, subject FROM documents LIMIT 5;"
```

2. **Review metrics**

```bash
cat output/runs/*/metrics.json
uv run email-parser metrics --corpus tests/fixtures/synthetic
```

3. **Snapshot diff before `--snapshot-update`**

When pytest snapshot tests fail:

```bash
uv run pytest tests/test_snapshots.py -q
# inspect diff in pytest output
# only after review:
uv run pytest tests/test_snapshots.py --snapshot-update
```

4. **Compare vs baseline**

Save a baseline run directory or copy `output/documents/` elsewhere, then after changes:

```bash
uv run email-parser compare output/runs/BASELINE_ID output/runs/CURRENT_ID
uv run email-parser compare /path/to/baseline/documents output/documents
```

5. **Reset store**

```bash
rm -rf output/*
```

Regenerate fixtures if needed (`uv run python tests/fixtures/generate.py`).

## Recorded automated results (2026-08-15)

These were verified by the test suite and CLI against `tests/fixtures/synthetic/`, not by clicking the UI.

| Scenario | Result |
|----------|--------|
| Full pytest | 80 passed |
| Golden corpus metrics | 17 emails, 30 docs, max_depth 2, 27 ok, 2 failed (zero-byte/corrupt), 1 unsupported, 0 invariant violations, cid_resolution_rate 1.0 |
| PDF-in-PDF / forwards | Covered by pipeline + fixture tests; max_depth 2 |
| RFC 2047 / CID / quoting / alternatives | `tests/test_headers.py`, `test_cid_linkage.py`, `test_quoting.py`, `test_body_selection.py` passed |
| Determinism + snapshots | `tests/test_determinism.py`, `tests/test_snapshots.py` passed |
| API upload / peek / cancel / blob | `tests/test_api.py` 8 passed |
| Baseline metrics | `tests/fixtures/baseline/metrics.json` and `output/runs/baseline/metrics.json` |
| UI click-through (empty submit, tab close, refresh) | Not executed in a browser this run; follow the DURING checklist locally at `http://127.0.0.1:8000` |
