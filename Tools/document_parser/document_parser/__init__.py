"""Standalone scanned-PDF OCR tool (PaddleOCR backend).

Use this package when born-digital PDF extraction is insufficient and OCR is
required. PyMuPDF is confined to ``document_parser.raster``; Paddle imports
live only in ``document_parser.ocr.paddle_engine``.
"""

from __future__ import annotations

from document_parser.models import (
    DocAnchor,
    DocBlock,
    DocBlockType,
    DocMetadata,
    DocParseResult,
    DocParseStatus,
)
from document_parser.ocr.paddle_engine import ENGINE_NAME, ENGINE_VERSION
from document_parser.pdf import is_available, parse_pdf

__all__ = [
    "ENGINE_NAME",
    "ENGINE_VERSION",
    "DocAnchor",
    "DocBlock",
    "DocBlockType",
    "DocMetadata",
    "DocParseResult",
    "DocParseStatus",
    "is_available",
    "parse_pdf",
]
