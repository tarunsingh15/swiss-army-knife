"""Tests for the standalone document_parser package."""

from __future__ import annotations

import io

import pymupdf
import pytest
from PIL import Image, ImageDraw

from document_parser import DocParseStatus, is_available, parse_pdf
from document_parser.ocr import paddle_engine


def _make_scanned_pdf(text: str = "OCR Test Text") -> bytes:
    """Create a minimal image-only PDF with no text layer."""
    image = Image.new("RGB", (500, 120), "white")
    draw = ImageDraw.Draw(image)
    draw.text((20, 40), text, fill="black")

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    image_bytes = buffer.getvalue()

    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    rect = pymupdf.Rect(72, 72, 472, 192)
    page.insert_image(rect, stream=image_bytes)
    payload = doc.tobytes()
    doc.close()
    return payload


def test_is_available_reports_paddle_state() -> None:
    """is_available mirrors the paddle_engine import probe."""
    assert is_available() is paddle_engine.paddle_is_available()


def test_parse_without_paddle_returns_failed() -> None:
    """parse_pdf fails gracefully when PaddleOCR is not installed."""
    if is_available():
        pytest.skip("PaddleOCR is installed; unavailable-path test not applicable")

    result = parse_pdf(_make_scanned_pdf(), filename="scan.pdf")
    assert result.status == DocParseStatus.failed
    assert result.blocks == []
    assert result.warnings
    assert "not available" in result.warnings[0].lower()


@pytest.mark.ocr
def test_parse_scanned_pdf_extracts_blocks_with_anchors() -> None:
    """parse_pdf OCRs an image-only PDF and returns anchored paragraph blocks."""
    if not is_available():
        pytest.skip("PaddleOCR is not installed")

    result = parse_pdf(_make_scanned_pdf("Hello Scanned PDF"), filename="scan.pdf")
    assert result.status == DocParseStatus.ok
    assert result.metadata.filename == "scan.pdf"
    assert result.metadata.page_count == 1
    assert result.metadata.needs_ocr is True
    assert result.metadata.has_text_layer is False
    assert result.metadata.ocr_engine == "paddleocr"
    assert result.blocks

    for block in result.blocks:
        assert block.anchor is not None
        assert block.anchor.page >= 1
        assert len(block.anchor.bbox) == 4
        x0, y0, x1, y1 = block.anchor.bbox
        assert x1 > x0
        assert y1 > y0

    combined_text = " ".join(block.text or "" for block in result.blocks).lower()
    assert "hello" in combined_text or "scanned" in combined_text or "pdf" in combined_text


def test_group_lines_into_paragraphs_merges_close_lines() -> None:
    """Lines within y-proximity are merged into one paragraph block."""
    from document_parser.ocr.paddle_engine import OcrLine, group_lines_into_paragraphs

    lines = [
        OcrLine(text="First line", bbox=(10.0, 10.0, 100.0, 30.0), confidence=0.9),
        OcrLine(text="Second line", bbox=(10.0, 32.0, 120.0, 52.0), confidence=0.9),
        OcrLine(text="Far away", bbox=(10.0, 200.0, 100.0, 220.0), confidence=0.9),
    ]
    paragraphs = group_lines_into_paragraphs(lines)
    assert len(paragraphs) == 2
    assert "First line" in paragraphs[0].text
    assert "Second line" in paragraphs[0].text
    assert paragraphs[1].text == "Far away"
