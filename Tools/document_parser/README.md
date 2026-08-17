# document-parser

Standalone scanned-PDF OCR with citation-anchored blocks. PyMuPDF is confined to `document_parser/raster.py`; PaddleOCR imports live only in `document_parser/ocr/paddle_engine.py`.

## Setup

```bash
cd Tools/document_parser
uv sync --extra dev          # core + tests (no OCR)
uv sync --extra dev --extra ocr   # include PaddleOCR
```

## CLI

```bash
uv run doc-parser version
uv run doc-parser parse path/to/scan.pdf
```

## Python API

```python
from document_parser import parse_pdf, is_available

if is_available():
    result = parse_pdf(path.read_bytes(), filename="scan.pdf")
```

## Email Parser integration

When installed as an optional dependency of the Email Parser (`uv sync --extra ocr` from `Tools/Email Parser/`), `document_parser` is invoked only by `pdf_pymupdf.py` when born-digital extraction is insufficient. See the Email Parser [User Manual](../Email%20Parser/docs/USER_MANUAL.md) for OCR trigger rules and environment variables.

## Tests

```bash
uv run pytest                  # skips @pytest.mark.ocr when paddle not installed
uv run pytest -m ocr           # OCR tests only (requires --extra ocr)
```
