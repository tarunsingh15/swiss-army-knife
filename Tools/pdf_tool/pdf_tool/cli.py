"""Command-line interface for the standalone PDF tool."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from pdf_tool import parse_pdf

app = typer.Typer(help="Extract citation-anchored content from PDF files.")


def _result_to_dict(result) -> dict:
    """Serialize a PdfParseResult to a JSON-friendly dict."""
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
        "embedded_files": [
            {
                "filename": item.filename,
                "mime_type": item.mime_type,
                "byte_size": len(item.raw),
            }
            for item in result.embedded_files
        ],
    }


@app.command("parse")
def parse_command(
    path: Path = typer.Argument(..., help="Path to a PDF file"),
) -> None:
    """Parse a PDF and print structured JSON to stdout."""
    raw = path.read_bytes()
    result = parse_pdf(raw, filename=path.name)
    typer.echo(json.dumps(_result_to_dict(result), indent=2, sort_keys=True))


@app.command("version")
def version_command() -> None:
    """Print the PDF tool engine name and version."""
    from pdf_tool import ENGINE_NAME, ENGINE_VERSION

    typer.echo(f"{ENGINE_NAME} {ENGINE_VERSION}")
