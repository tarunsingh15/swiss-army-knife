"""PyMuPDF-backed PDF extraction engine.

All PyMuPDF imports are confined to this module so the rest of the codebase
can depend on pdf_tool without touching pymupdf directly.
"""

from __future__ import annotations

from dataclasses import dataclass

import puremagic
import pymupdf

from pdf_tool.models import (
    EmbeddedFile,
    PdfAnchor,
    PdfBlock,
    PdfBlockType,
    PdfMetadata,
    PdfParseResult,
    PdfParseStatus,
)

ENGINE_NAME = "pymupdf"
ENGINE_VERSION = "0.1.0"

_PDF_MIME_TYPES = frozenset({"application/pdf", "application/x-pdf"})
_PDF_MAGIC = b"%PDF-"
_PDF_ANNOT_FILE_ATTACHMENT = 17
_HEADER_FOOTER_Y_TOLERANCE = 8.0
_HEADING_SIZE_RATIO = 1.15
_HEADING_SIZE_DELTA = 1.0


@dataclass(frozen=True)
class _TextBlockCandidate:
    """Intermediate text block before header/footer filtering."""

    text: str
    page_number: int
    bbox: tuple[float, float, float, float]
    first_span_size: float
    median_span_size: float


def is_pdf_bytes(raw: bytes, mime_type: str | None = None) -> bool:
    """Return True when bytes look like a PDF by MIME type or %PDF- magic."""
    if mime_type and mime_type in _PDF_MIME_TYPES:
        return True
    return raw[:5] == _PDF_MAGIC


def _bbox_to_tuple(bbox: object) -> tuple[float, float, float, float]:
    """Convert pymupdf geometry to a plain four-float bbox tuple."""
    if isinstance(bbox, (tuple, list)) and len(bbox) == 4:
        return (float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]))
    return (float(bbox.x0), float(bbox.y0), float(bbox.x1), float(bbox.y1))


def _quad_to_points(quad: object) -> list[float]:
    """Convert a pymupdf Quad to eight plain floats (ul, ur, ll, lr)."""
    return [
        float(quad.ul.x),
        float(quad.ul.y),
        float(quad.ur.x),
        float(quad.ur.y),
        float(quad.ll.x),
        float(quad.ll.y),
        float(quad.lr.x),
        float(quad.lr.y),
    ]


def _sniff_mime(raw: bytes) -> str:
    """Return the best-effort MIME type for embedded child blobs."""
    try:
        matches = puremagic.magic_string(raw)
        if matches and matches[0].mime_type:
            return matches[0].mime_type
    except (puremagic.PureError, IndexError, ValueError):
        pass
    return "application/octet-stream"


def _median(values: list[float]) -> float:
    """Return the median of numeric values, or 0.0 when empty."""
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _join_block_text(block: dict) -> tuple[str, float, list[float]]:
    """Join span text in a dict block and collect span sizes."""
    parts: list[str] = []
    sizes: list[float] = []
    first_span_size = 0.0
    for line in block.get("lines", []):
        for span in line.get("spans", []):
            parts.append(span.get("text", ""))
            size = float(span.get("size", 0.0))
            sizes.append(size)
            if not first_span_size and size:
                first_span_size = size
    if not first_span_size and sizes:
        first_span_size = sizes[0]
    return "".join(parts).strip(), first_span_size, sizes


def _is_heading(first_span_size: float, median_span_size: float) -> bool:
    """Return True when the first span is clearly larger than body text."""
    if first_span_size <= 0 or median_span_size <= 0:
        return False
    return (
        first_span_size >= median_span_size * _HEADING_SIZE_RATIO
        and first_span_size >= median_span_size + _HEADING_SIZE_DELTA
    )


def _drop_repeating_headers_footers(
    candidates: list[_TextBlockCandidate],
) -> list[_TextBlockCandidate]:
    """Drop text blocks that repeat at the same y-range on three or more pages."""
    by_text: dict[str, list[_TextBlockCandidate]] = {}
    for candidate in candidates:
        if not candidate.text:
            continue
        by_text.setdefault(candidate.text, []).append(candidate)

    drop_keys: set[tuple[int, tuple[float, float, float, float], str]] = set()
    for text, occurrences in by_text.items():
        if len(occurrences) < 3:
            continue
        y0_values = [item.bbox[1] for item in occurrences]
        if max(y0_values) - min(y0_values) <= _HEADER_FOOTER_Y_TOLERANCE:
            for item in occurrences:
                drop_keys.add((item.page_number, item.bbox, item.text))

    kept: list[_TextBlockCandidate] = []
    for candidate in candidates:
        key = (candidate.page_number, candidate.bbox, candidate.text)
        if key not in drop_keys:
            kept.append(candidate)
    return kept


def _failed_result(
    raw: bytes,
    *,
    filename: str | None,
    warnings: list[str],
) -> PdfParseResult:
    """Build a failed parse result for encryption, corruption, or open errors."""
    return PdfParseResult(
        blocks=[],
        embedded_files=[],
        metadata=PdfMetadata(
            title=None,
            producer=None,
            page_count=0,
            byte_size=len(raw),
            filename=filename,
        ),
        status=PdfParseStatus.failed,
        warnings=warnings,
    )


class PyMuPDFEngine:
    """Extract citation-anchored blocks and embedded files from PDF bytes."""

    name = ENGINE_NAME
    version = ENGINE_VERSION

    def parse(self, raw: bytes, *, filename: str | None = None) -> PdfParseResult:
        """Parse a PDF into blocks, metadata, and embedded file payloads."""
        try:
            doc = pymupdf.open(stream=raw, filetype="pdf")
        except Exception as exc:
            return _failed_result(raw, filename=filename, warnings=[str(exc)])

        try:
            if doc.needs_pass:
                return _failed_result(
                    raw,
                    filename=filename,
                    warnings=["PDF is password protected and cannot be opened without a password"],
                )

            chars_per_page: list[int] = []
            page_needs_ocr: list[bool] = []
            text_candidates: list[_TextBlockCandidate] = []
            table_blocks: list[tuple[list[list[str]], int, tuple[float, float, float, float]]] = []
            widget_blocks: list[tuple[str, int, tuple[float, float, float, float]]] = []

            for page in doc:
                page_number = page.number + 1
                plain_text = page.get_text("text")
                char_count = len(plain_text.strip())
                chars_per_page.append(char_count)
                needs_ocr = char_count == 0
                page_needs_ocr.append(needs_ocr)

                if not needs_ocr:
                    data = page.get_text("dict", sort=True)
                    page_span_sizes: list[float] = []
                    page_blocks: list[tuple[str, float, tuple[float, float, float, float], list[float]]] = []

                    for block in data.get("blocks", []):
                        if block.get("type") != 0:
                            continue
                        text, first_span_size, span_sizes = _join_block_text(block)
                        if not text:
                            continue
                        bbox = _bbox_to_tuple(block["bbox"])
                        page_span_sizes.extend(span_sizes)
                        page_blocks.append((text, first_span_size, bbox, span_sizes))

                    median_size = _median(page_span_sizes)
                    for text, first_span_size, bbox, _span_sizes in page_blocks:
                        text_candidates.append(
                            _TextBlockCandidate(
                                text=text,
                                page_number=page_number,
                                bbox=bbox,
                                first_span_size=first_span_size,
                                median_span_size=median_size,
                            )
                        )

                for table in page.find_tables().tables:
                    rows = [["" if cell is None else str(cell) for cell in row] for row in table.extract()]
                    table_blocks.append((rows, page_number, _bbox_to_tuple(table.bbox)))

                for widget in page.widgets() or []:
                    field_name = widget.field_name or ""
                    field_value = widget.field_value or ""
                    widget_blocks.append(
                        (
                            f"{field_name}={field_value}",
                            page_number,
                            _bbox_to_tuple(widget.rect),
                        )
                    )

            kept_text = _drop_repeating_headers_footers(text_candidates)
            blocks: list[PdfBlock] = []

            for candidate in kept_text:
                block_type = (
                    PdfBlockType.heading
                    if _is_heading(candidate.first_span_size, candidate.median_span_size)
                    else PdfBlockType.paragraph
                )
                blocks.append(
                    PdfBlock(
                        block_type=block_type,
                        text=candidate.text,
                        anchor=PdfAnchor(page=candidate.page_number, bbox=candidate.bbox),
                    )
                )

            for rows, page_number, bbox in table_blocks:
                blocks.append(
                    PdfBlock(
                        block_type=PdfBlockType.table,
                        rows=rows,
                        anchor=PdfAnchor(page=page_number, bbox=bbox),
                    )
                )

            for text, page_number, bbox in widget_blocks:
                blocks.append(
                    PdfBlock(
                        block_type=PdfBlockType.form_field,
                        text=text,
                        anchor=PdfAnchor(page=page_number, bbox=bbox),
                    )
                )

            embedded_files: list[EmbeddedFile] = []

            if doc.embfile_count():
                names = doc.embfile_names()
                for index in range(doc.embfile_count()):
                    embedded_raw = doc.embfile_get(index)
                    name = names[index] if index < len(names) else str(index)
                    embedded_files.append(
                        EmbeddedFile(
                            raw=embedded_raw,
                            filename=name,
                            mime_type=_sniff_mime(embedded_raw),
                        )
                    )

            for page in doc:
                for annot in page.annots() or []:
                    if annot.type[0] != _PDF_ANNOT_FILE_ATTACHMENT:
                        continue
                    attachment_raw = annot.get_file()
                    if not attachment_raw:
                        continue
                    file_info = annot.file_info or {}
                    embedded_files.append(
                        EmbeddedFile(
                            raw=attachment_raw,
                            filename=file_info.get("filename"),
                            mime_type=_sniff_mime(attachment_raw),
                        )
                    )

            metadata = PdfMetadata(
                title=doc.metadata.get("title") or None,
                producer=doc.metadata.get("producer") or None,
                page_count=doc.page_count,
                byte_size=len(raw),
                filename=filename,
                chars_per_page=chars_per_page,
                has_text_layer=any(count > 0 for count in chars_per_page),
                needs_ocr=any(page_needs_ocr),
            )
            return PdfParseResult(
                blocks=blocks,
                embedded_files=embedded_files,
                metadata=metadata,
                status=PdfParseStatus.ok,
            )
        except Exception as exc:
            return _failed_result(raw, filename=filename, warnings=[str(exc)])
        finally:
            doc.close()

    def search_quote(
        self,
        raw: bytes,
        needle: str,
        clip: tuple[float, float, float, float] | None,
        page: int,
    ) -> list[list[float]]:
        """Search a page for needle text and return quad point lists."""
        doc = pymupdf.open(stream=raw, filetype="pdf")
        try:
            page_obj = doc[page - 1]
            search_kwargs: dict[str, object] = {"quads": True}
            if clip is not None:
                search_kwargs["clip"] = clip
            quads = page_obj.search_for(needle, **search_kwargs)
            return [_quad_to_points(quad) for quad in quads]
        finally:
            doc.close()

    def render_thumbnail(
        self,
        raw: bytes,
        page: int,
        clip: tuple[float, float, float, float],
        dpi: int = 150,
    ) -> bytes:
        """Render a clipped PNG thumbnail for a PDF page region."""
        doc = pymupdf.open(stream=raw, filetype="pdf")
        try:
            page_obj = doc[page - 1]
            pixmap = page_obj.get_pixmap(dpi=dpi, clip=clip)
            return pixmap.tobytes("png")
        finally:
            doc.close()
