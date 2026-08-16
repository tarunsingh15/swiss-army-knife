"""Parser for PDF attachments using PyMuPDF."""

from __future__ import annotations

from dataclasses import dataclass

import puremagic
import pymupdf

from email_parser.file_parsers.base import Blob, ParseContext, ParseResult
from email_parser.ids import make_block_id, make_doc_id
from email_parser.models import (
    Anchor,
    Block,
    BlockType,
    CommonMetadata,
    Document,
    DocumentMetadata,
    NativeMetadata,
    ParseStatus,
    Provenance,
    RelationType,
    SourceType,
)

_PDF_MIME_TYPES = {"application/pdf", "application/x-pdf"}
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
        if matches:
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


def _failed_document(
    raw: bytes,
    blob: Blob,
    ctx: ParseContext,
    *,
    warnings: list[str],
) -> ParseResult:
    """Build a failed PDF document shell for encryption or corruption."""
    doc_id = make_doc_id(raw)
    document = Document(
        doc_id=doc_id,
        source_type=SourceType.pdf,
        mime_type="application/pdf",
        root_id=ctx.root_id or doc_id,
        parent_id=ctx.parent_id,
        relation_to_parent=blob.relation_to_parent,
        depth=ctx.depth,
        ordinal=blob.ordinal,
        metadata=DocumentMetadata(
            common=CommonMetadata(
                byte_size=len(raw),
                filename=blob.filename,
            ),
        ),
        blocks=[],
        provenance=Provenance(
            parser=PdfPymupdfParser.name,
            parser_version=PdfPymupdfParser.version,
            parsed_at=None,
            status=ParseStatus.failed,
            warnings=warnings,
        ),
    )
    return ParseResult(document=document, child_blobs=[])


class PdfPymupdfParser:
    """Extract citation-anchored blocks from PDF bytes via PyMuPDF."""

    name = "pdf_pymupdf"
    version = "0.1.0"
    priority = 20

    def can_handle(self, mime_type: str, sniffed: bytes) -> bool:
        """Claim PDF blobs by MIME type or %PDF- magic bytes."""
        return mime_type in _PDF_MIME_TYPES or sniffed[:5] == _PDF_MAGIC

    def parse(self, blob: Blob, ctx: ParseContext) -> ParseResult:
        """Parse a PDF blob into blocks, metadata, and embedded child blobs."""
        raw = blob.raw
        doc_id = make_doc_id(raw)

        try:
            doc = pymupdf.open(stream=raw, filetype="pdf")
        except Exception as exc:
            return _failed_document(raw, blob, ctx, warnings=[str(exc)])

        try:
            if doc.needs_pass:
                return _failed_document(
                    raw,
                    blob,
                    ctx,
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
            blocks: list[Block] = []
            ordinal = 0

            for candidate in kept_text:
                block_type = (
                    BlockType.heading
                    if _is_heading(candidate.first_span_size, candidate.median_span_size)
                    else BlockType.paragraph
                )
                blocks.append(
                    Block(
                        block_id=make_block_id(doc_id, ordinal, block_type.value),
                        type=block_type,
                        text=candidate.text,
                        anchor=Anchor(page=candidate.page_number, bbox=candidate.bbox),
                    )
                )
                ordinal += 1

            for rows, page_number, bbox in table_blocks:
                blocks.append(
                    Block(
                        block_id=make_block_id(doc_id, ordinal, BlockType.table.value),
                        type=BlockType.table,
                        rows=rows,
                        text=None,
                        anchor=Anchor(page=page_number, bbox=bbox),
                    )
                )
                ordinal += 1

            for text, page_number, bbox in widget_blocks:
                blocks.append(
                    Block(
                        block_id=make_block_id(doc_id, ordinal, BlockType.form_field.value),
                        type=BlockType.form_field,
                        text=text,
                        anchor=Anchor(page=page_number, bbox=bbox),
                    )
                )
                ordinal += 1

            child_blobs: list[Blob] = []
            child_ordinal = 0

            if doc.embfile_count():
                names = doc.embfile_names()
                for index in range(doc.embfile_count()):
                    embedded_raw = doc.embfile_get(index)
                    filename = names[index] if index < len(names) else str(index)
                    child_blobs.append(
                        Blob(
                            raw=embedded_raw,
                            filename=filename,
                            mime_type=_sniff_mime(embedded_raw),
                            relation_to_parent=RelationType.embedded_file,
                            ordinal=child_ordinal,
                        )
                    )
                    child_ordinal += 1

            for page in doc:
                for annot in page.annots() or []:
                    if annot.type[0] != _PDF_ANNOT_FILE_ATTACHMENT:
                        continue
                    attachment_raw = annot.get_file()
                    if not attachment_raw:
                        continue
                    file_info = annot.file_info or {}
                    filename = file_info.get("filename")
                    child_blobs.append(
                        Blob(
                            raw=attachment_raw,
                            filename=filename,
                            mime_type=_sniff_mime(attachment_raw),
                            relation_to_parent=RelationType.embedded_file,
                            ordinal=child_ordinal,
                        )
                    )
                    child_ordinal += 1

            document = Document(
                doc_id=doc_id,
                source_type=SourceType.pdf,
                mime_type="application/pdf",
                root_id=ctx.root_id or doc_id,
                parent_id=ctx.parent_id,
                relation_to_parent=blob.relation_to_parent,
                depth=ctx.depth,
                ordinal=blob.ordinal,
                metadata=DocumentMetadata(
                    common=CommonMetadata(
                        title=doc.metadata.get("title") or None,
                        byte_size=len(raw),
                        page_count=doc.page_count,
                        filename=blob.filename,
                    ),
                    native=NativeMetadata(
                        producer=doc.metadata.get("producer") or None,
                        has_text_layer=any(count > 0 for count in chars_per_page),
                        needs_ocr=any(page_needs_ocr),
                        chars_per_page=chars_per_page,
                    ),
                ),
                blocks=blocks,
                provenance=Provenance(
                    parser=self.name,
                    parser_version=self.version,
                    parsed_at=None,
                    status=ParseStatus.ok,
                ),
            )
            return ParseResult(document=document, child_blobs=child_blobs)
        except Exception as exc:
            return _failed_document(raw, blob, ctx, warnings=[str(exc)])
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
