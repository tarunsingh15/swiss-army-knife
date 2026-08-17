# Email Parser

Local email and PDF attachment parser that emits citation-anchored JSON for search and RAG workflows. Parses `.eml` files and nested attachments deterministically—no LLM, embeddings, or OCR in the parse path.

## Prerequisites

- **Python 3.12+** (see `.python-version`)
- **[uv](https://docs.astral.sh/uv/)** package manager

The project path contains a space—always quote it in shell commands:

```bash
cd "/path/to/Email Parser"
```

## Setup

Install dependencies for CLI, web UI, and tests:

```bash
uv sync --extra web --extra dev
```

**Required:** generate synthetic test fixtures (they are gitignored and not committed):

```bash
uv run python tests/fixtures/generate.py
```

This writes 15 `.eml` and `.truth.json` pairs under `tests/fixtures/synthetic/`. Skip this step and pytest, the golden corpus UI action, and several integration tests will fail.

### Install tiers

| Goal | Command |
|------|---------|
| CLI / library only | `uv sync` |
| + tests / lint | `uv sync --extra dev` |
| + web UI / API | `uv sync --extra web` |
| Full local dev | `uv sync --extra web --extra dev` |

## Run

### Web UI and API

```bash
uv run uvicorn web.app:app --host 127.0.0.1 --port 8000
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000).

### CLI

```bash
uv run email-parser --help
uv run email-parser version
uv run email-parser parse tests/fixtures/synthetic/plain_no_attachment.eml
uv run email-parser metrics --corpus tests/fixtures/synthetic
uv run email-parser compare output/runs/A output/runs/B
```

### Docker

```bash
docker compose up --build
```

Artifacts are written to `./output` (mounted volume). The web UI is available at [http://127.0.0.1:8000](http://127.0.0.1:8000).

To run tests inside Docker:

```bash
docker compose --profile test run --rm test
```

Note: synthetic fixtures are excluded from the Docker build context. The test profile may fail fixture-dependent tests unless the image generates them at build time.

## Test

```bash
uv run pytest tests -q
```

Confirm fixtures exist before running:

```bash
ls tests/fixtures/synthetic/*.eml | wc -l   # expect 15
```

For snapshot updates (review diffs first):

```bash
uv run pytest tests/test_snapshots.py --snapshot-update
```

## Troubleshooting

**`ModuleNotFoundError` (pymupdf, selectolax, puremagic, etc.)**

Run `uv sync --extra web --extra dev` from the project directory. Do not rely on a separate Conda or global Python environment.

**`bad interpreter` or wrong Python version**

The project `.venv` may be stale after moving or renaming the directory. Recreate it:

```bash
rm -rf .venv && uv sync --extra web --extra dev
```

**`VIRTUAL_ENV` mismatch warning**

If another virtual environment is active (e.g. Conda), uv prints a warning and ignores it. This is safe when using `uv run`. To silence the warning, run `deactivate` or `unset VIRTUAL_ENV`.

**Missing fixtures / golden corpus 404**

Run `uv run python tests/fixtures/generate.py`. Synthetic fixtures are generated locally and not checked into git.

## Documentation

- [Codebase Overview](docs/CODEBASE_OVERVIEW.md) — developer map of modules and data flow
- [User Manual](docs/USER_MANUAL.md) — architecture, output layout, design choices, API, CLI
- [Manual Steps](docs/MANUAL_STEPS.md) — setup and hands-on test checklist
- [Adding a Parser](docs/ADDING_A_PARSER.md) — plug-in protocol and worked example
- [Metrics](docs/METRICS.md) — Tier A/B/C metric definitions
