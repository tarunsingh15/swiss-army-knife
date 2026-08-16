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

## MY NOTES:
MIME Parsing
- Outlook doesnt use MIME format, it uses MSG, a compound file binary format (CFBF), a single file containing a entire internal hierarchy of nested files and folders.
    - Requires the “extract-msg” plugin to handle this tpye
 - Gmail will work with the stdlibrary “email”

File Type Detection (Sniffing)
- Dont trust file names as they can be wrongly labelled.
- “Puremagic” for a purely python library, requires no system binary installation. (Portable)
    - “Python-magic” can be the upgrade.

Body:
- Lxml and BeautifulSoup can be used for XML and HTML parsing, but “selectolax” is significantly faster.
- Using html2text will flatten it to markdown, discarding the hierarchy or the structure.

Quoted-reply stripping:
- Extracting only the newly typed message from an email thread
- Single largest token sink in email, we need to ignore the massive chain of prev emails that get appended to the bottom
- Using Mailgun’s “Talon”, this is open-source, a the only major library that uses ML along with traditional regex.

PDF:
- We need to handle native PDF files, Scanned PDF files or Hybrid PDF files.
- Native PDF files are easy and dirt-cheap to process, the other two types require OCR integration to identify embedded elements.
- For native PDF: using the “PyMuPDF” library which is licensed under AGPL, which is free for personal user by paid for commercial use.
    - Pros: But its is lightning fast, free for personal use and can handle document metadata, annotation and even extract images
    - Cons: Know to have issues with the order, especially can scramble get if the doc has a complex multi-column layout.
    - Wrapper: Recently, “pymupdf4llm” wrapper was released to convert pymupdf’s speed to LLM-ready markdown.
-  If PDFs are full of tables, invoices or complex layouts, I can use “pdfplumber”
    - Pro: uses geometry and visual elements to mathematically reconstruct tables with excellent accuracy, also includes visual debugging tools. Has better TEDS than PyMuPDF.
    - Cons: Has a lot of heavy math, it is slower compared to PyMuPDF. Doesn’t do well with doc metadata, encryption stets, AcroForm field (Acrobat Form, fillable fields in PDFs) values, Will need to use “pypdf” along with it to overcome. (AcroForm fields sit as widgets on top of actual unchangeable PDF files to capture inputs)
- For RAG, we use “Docling” if feeding to LLMs or Vectors DBs
    - Pros: Analyses reading order, capture headers, tables in markdown formats and fixes multi-column reading order issues with traditional native PDFs

> TEDS = Tree-Edit-Distance-based Similarity, an industry-std benchmark to score how accurately an AI or parsing library extracts a table from a doc.

Schema:
- Pydantic, helps validate the parser boundaries, auto-generated JSON schema. 

Storage:
- One SQLLite file should do.
- Need to handle:
    - Structured fields
    - Unstructured JSON
    - Sqlite-vec = adds vector search in the same file. (Only KNN search, ANN is still under dev)


Security:
- Need to handle the security, attacker injections, cut off from internet access run in sandboxes
- ACL-aware retrievals

Note:
- Ignore LangChain or LlamaIndex - their doc abstraction is weaker - no typed edge, no page/bbox anchors
