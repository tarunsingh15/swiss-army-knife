"""Command-line interface for the standalone document parser."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from document_parser import is_available, parse_pdf

app = typer.Typer(help="Extract citation-anchored content from scanned PDFs via OCR.")


def _result_to_dict(result) -> dict:
    """Serialize a DocParseResult to a JSON-friendly dict."""
    return {
        "status": result.status.value,
        "warnings": result.warnings,
        "metadata": {
            "title": result.metadata.title,
            "producer": result.metadata.producer,
            "page_count": result.metadata.page_count,
            "byte_size": result.metadata.byte_size,
            "filename": result.metadata.filename,
            "chars_per_page": result.metadata.chars_per_page,
            "has_text_layer": result.metadata.has_text_layer,
            "needs_ocr": result.metadata.needs_ocr,
            "ocr_engine": result.metadata.ocr_engine,
        },
        "blocks": [
            {
                "type": block.block_type.value,
                "text": block.text,
                "rows": block.rows,
                "anchor": (
                    {"page": block.anchor.page, "bbox": block.anchor.bbox}
                    if block.anchor
                    else None
                ),
            }
            for block in result.blocks
        ],
    }


@app.command("parse")
def parse_command(
    path: Path = typer.Argument(..., help="Path to a scanned PDF file"),
) -> None:
    """Parse a scanned PDF and print structured JSON to stdout."""
    if not is_available():
        typer.echo(
            "PaddleOCR is not installed. Run: uv sync --extra ocr",
            err=True,
        )
        raise typer.Exit(code=1)

    raw = path.read_bytes()
    result = parse_pdf(raw, filename=path.name)
    typer.echo(json.dumps(_result_to_dict(result), indent=2, sort_keys=True))


@app.command("version")
def version_command() -> None:
    """Print the document parser engine name, version, and OCR availability."""
    from document_parser import ENGINE_NAME, ENGINE_VERSION

    ocr_status = "available" if is_available() else "not installed"
    typer.echo(f"{ENGINE_NAME} {ENGINE_VERSION} (ocr {ocr_status})")
