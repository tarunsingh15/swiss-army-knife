# Email Parser

Local email and PDF attachment parser that emits citation-anchored JSON for search and RAG workflows. Parses `.eml` files and nested attachments deterministically—no LLM, embeddings, or OCR in the parse path.

## Quick start

```bash
uv sync --extra web --extra dev
uv run python tests/fixtures/generate.py
uv run pytest tests -q
uv run uvicorn web.app:app --host 127.0.0.1 --port 8000
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000).

CLI:

```bash
uv run email-parser parse tests/fixtures/synthetic/plain_no_attachment.eml
uv run email-parser metrics --corpus tests/fixtures/synthetic
```

## Docker

```bash
docker compose up --build
```

Artifacts are written to `./output` (mounted volume).

## Documentation

- [User Manual](docs/USER_MANUAL.md) — architecture, output layout, design choices, API, CLI
- [Manual Steps](docs/MANUAL_STEPS.md) — setup and hands-on test checklist
- [Adding a Parser](docs/ADDING_A_PARSER.md) — plug-in protocol and worked example
- [Metrics](docs/METRICS.md) — Tier A/B/C metric definitions

## License note

PDF parsing uses [PyMuPDF](https://pymupdf.readthedocs.io/) (AGPL-3.0 / commercial dual license). Review licensing before redistribution in a closed product.
