"""OCR orchestration for scanned PDF byte payloads."""

from __future__ import annotations

from document_parser.models import (
    DocAnchor,
    DocBlock,
    DocBlockType,
    DocMetadata,
    DocParseResult,
    DocParseStatus,
)
from document_parser.ocr.paddle_engine import (
    ENGINE_NAME,
    group_lines_into_paragraphs,
    paddle_import_error,
    paddle_is_available,
    pixel_bbox_to_pdf_bbox,
    run_ocr_on_image,
)
from document_parser.raster import pdf_catalog_metadata, pdf_page_count, rasterize_pdf

_DEFAULT_DPI = 200


def is_available() -> bool:
    """Return True when the PaddleOCR backend can be loaded."""
    return paddle_is_available()


def parse_pdf(raw: bytes, *, filename: str | None = None, dpi: int = _DEFAULT_DPI) -> DocParseResult:
    """Parse a scanned PDF via rasterization and PaddleOCR."""
    byte_size = len(raw)
    if not is_available():
        return _failed_result(
            raw,
            filename=filename,
            warnings=[f"PaddleOCR is not available: {paddle_import_error()}"],
        )

    try:
        page_count = pdf_page_count(raw)
        title, producer = pdf_catalog_metadata(raw)
    except Exception as exc:
        return _failed_result(raw, filename=filename, warnings=[str(exc)])

    try:
        raster_pages = rasterize_pdf(raw, dpi=dpi)
    except Exception as exc:
        return _failed_result(raw, filename=filename, warnings=[str(exc)])

    blocks: list[DocBlock] = []
    chars_per_page: list[int] = []
    warnings: list[str] = []

    for raster_page in raster_pages:
        try:
            lines = run_ocr_on_image(raster_page.image)
        except Exception as exc:
            warnings.append(f"OCR failed on page {raster_page.page_number}: {exc}")
            chars_per_page.append(0)
            continue

        paragraphs = group_lines_into_paragraphs(lines)
        page_chars = 0
        image_height, image_width = raster_page.image.shape[:2]

        for paragraph in paragraphs:
            if not paragraph.text.strip():
                continue
            page_chars += len(paragraph.text)
            pdf_bbox = pixel_bbox_to_pdf_bbox(
                paragraph.bbox,
                image_width=image_width,
                image_height=image_height,
                page_width=raster_page.page_width,
                page_height=raster_page.page_height,
            )
            blocks.append(
                DocBlock(
                    block_type=DocBlockType.paragraph,
                    text=paragraph.text,
                    anchor=DocAnchor(page=raster_page.page_number, bbox=pdf_bbox),
                )
            )
        chars_per_page.append(page_chars)

    metadata = DocMetadata(
        title=title,
        producer=producer,
        page_count=page_count,
        byte_size=byte_size,
        filename=filename,
        chars_per_page=chars_per_page,
        has_text_layer=False,
        needs_ocr=True,
        ocr_engine=ENGINE_NAME,
    )
    return DocParseResult(
        blocks=blocks,
        metadata=metadata,
        status=DocParseStatus.ok,
        warnings=warnings,
    )


def _failed_result(
    raw: bytes,
    *,
    filename: str | None,
    warnings: list[str],
) -> DocParseResult:
    """Build a failed parse result for missing OCR, corruption, or open errors."""
    return DocParseResult(
        blocks=[],
        metadata=DocMetadata(
            title=None,
            producer=None,
            page_count=0,
            byte_size=len(raw),
            filename=filename,
            needs_ocr=True,
        ),
        status=DocParseStatus.failed,
        warnings=warnings,
    )
