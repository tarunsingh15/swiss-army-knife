"""PaddleOCR backend (sole PaddleOCR / paddlepaddle import site)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

ENGINE_NAME = "paddleocr"
ENGINE_VERSION = "0.1.0"

_Y_PROXIMITY_FACTOR = 1.5

_ocr_engine: object | None = None
_import_checked = False
_import_error: str | None = None


@dataclass(frozen=True)
class OcrLine:
    """One OCR text line with a pixel-space bounding box."""

    text: str
    bbox: tuple[float, float, float, float]
    confidence: float


@dataclass(frozen=True)
class OcrParagraph:
    """Paragraph clustered from one or more OCR lines."""

    text: str
    bbox: tuple[float, float, float, float]


def paddle_is_available() -> bool:
    """Return True when paddlepaddle and PaddleOCR import successfully."""
    _ensure_import_checked()
    return _import_error is None


def paddle_import_error() -> str | None:
    """Return the import error message when Paddle is unavailable."""
    _ensure_import_checked()
    return _import_error


def _ensure_import_checked() -> None:
    """Probe Paddle imports once and cache the outcome."""
    global _import_checked, _import_error
    if _import_checked:
        return
    _import_checked = True
    try:
        import paddle  # noqa: F401
        from paddleocr import PaddleOCR  # noqa: F401
    except ImportError as exc:
        _import_error = str(exc)


def _get_ocr_engine() -> object:
    """Return a lazily constructed PaddleOCR instance."""
    global _ocr_engine, _import_error
    _ensure_import_checked()
    if _import_error is not None:
        raise RuntimeError(f"PaddleOCR is not available: {_import_error}")
    if _ocr_engine is None:
        from paddleocr import PaddleOCR

        _ocr_engine = PaddleOCR(use_angle_cls=True, lang="en", show_log=False)
    return _ocr_engine


def _quad_to_bbox(quad: list[list[float]]) -> tuple[float, float, float, float]:
    """Convert a four-point quad to an axis-aligned bbox tuple."""
    xs = [point[0] for point in quad]
    ys = [point[1] for point in quad]
    return (min(xs), min(ys), max(xs), max(ys))


def _merge_bboxes(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    """Return the union of two axis-aligned bounding boxes."""
    return (
        min(left[0], right[0]),
        min(left[1], right[1]),
        max(left[2], right[2]),
        max(left[3], right[3]),
    )


def _line_height(bbox: tuple[float, float, float, float]) -> float:
    """Return the vertical extent of a bbox."""
    return max(bbox[3] - bbox[1], 1.0)


def group_lines_into_paragraphs(
    lines: list[OcrLine],
    *,
    y_proximity_factor: float = _Y_PROXIMITY_FACTOR,
) -> list[OcrParagraph]:
    """Cluster OCR lines into paragraph blocks by vertical proximity."""
    if not lines:
        return []

    ordered = sorted(lines, key=lambda line: (line.bbox[1], line.bbox[0]))
    paragraphs: list[OcrParagraph] = []
    current_texts: list[str] = []
    current_bbox = ordered[0].bbox
    previous_bbox = ordered[0].bbox

    for line in ordered:
        gap = line.bbox[1] - previous_bbox[3]
        threshold = _line_height(previous_bbox) * y_proximity_factor
        if current_texts and gap > threshold:
            paragraphs.append(
                OcrParagraph(text=" ".join(current_texts), bbox=current_bbox)
            )
            current_texts = []
            current_bbox = line.bbox
        else:
            if current_texts:
                current_bbox = _merge_bboxes(current_bbox, line.bbox)
            else:
                current_bbox = line.bbox
        current_texts.append(line.text)
        previous_bbox = line.bbox

    if current_texts:
        paragraphs.append(OcrParagraph(text=" ".join(current_texts), bbox=current_bbox))
    return paragraphs


def run_ocr_on_image(image: np.ndarray) -> list[OcrLine]:
    """Run PaddleOCR on one page image and return detected lines."""
    engine = _get_ocr_engine()
    raw_result = engine.ocr(image, cls=True)
    if not raw_result:
        return []

    page_lines = raw_result[0]
    if page_lines is None:
        return []

    lines: list[OcrLine] = []
    for item in page_lines:
        if not item or len(item) < 2:
            continue
        quad, text_info = item[0], item[1]
        if not text_info:
            continue
        text = str(text_info[0]).strip()
        if not text:
            continue
        confidence = float(text_info[1]) if len(text_info) > 1 else 0.0
        lines.append(
            OcrLine(
                text=text,
                bbox=_quad_to_bbox(quad),
                confidence=confidence,
            )
        )
    return lines


def pixel_bbox_to_pdf_bbox(
    bbox: tuple[float, float, float, float],
    *,
    image_width: int,
    image_height: int,
    page_width: float,
    page_height: float,
) -> tuple[float, float, float, float]:
    """Map pixel-space OCR coordinates to PDF user-space points."""
    if image_width <= 0 or image_height <= 0:
        return bbox
    scale_x = page_width / image_width
    scale_y = page_height / image_height
    x0, y0, x1, y1 = bbox
    return (x0 * scale_x, y0 * scale_y, x1 * scale_x, y1 * scale_y)
