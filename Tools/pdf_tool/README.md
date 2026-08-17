# pdf-tool

Standalone PDF extraction with citation-anchored blocks, quote search, and thumbnails. PyMuPDF is confined to `pdf_tool/pymupdf_engine.py`.

## Setup

```bash
cd Tools/pdf_tool
uv sync --extra dev
```

## CLI

```bash
uv run pdf-tool version
uv run pdf-tool parse path/to/document.pdf
```

## Python API

```python
from pdf_tool import parse_pdf, search_quote, render_thumbnail, is_pdf

result = parse_pdf(path.read_bytes(), filename="doc.pdf")
```

## Tests

```bash
uv run pytest
```
