"""Email-parser adapter around pdf_tool with optional document_parser OCR fallback."""

from __future__ import annotations

from email_parser.config import Settings, load_settings
from email_parser.file_parsers._pdf_mapping import to_child_blobs, to_email_blocks
from email_parser.file_parsers.base import Blob, ParseContext, ParseResult
from email_parser.ids import make_doc_id
from email_parser.models import (
    CommonMetadata,
    Document,
    DocumentMetadata,
    NativeMetadata,
    ParseStatus,
    Provenance,
    SourceType,
)
from pdf_tool import (
    PdfParseResult,
    PdfParseStatus,
    is_pdf,
    parse_pdf,
    render_thumbnail as tool_render_thumbnail,
    search_quote as tool_search_quote,
)
from pdf_tool.pymupdf_engine import ENGINE_VERSION


def _doc_parser_is_available() -> bool:
    """Return True when the optional document_parser package is installed and usable."""
    try:
        from document_parser import is_available
    except ImportError:
        return False
    return is_available()


def _pdf_needs_ocr(result: PdfParseResult, min_chars: int) -> bool:
    """Return True when born-digital extraction is insufficient for OCR fallback."""
    if result.metadata.needs_ocr:
        return True
    if result.status != PdfParseStatus.ok:
        return False
    if not result.blocks:
        return True
    total_chars = sum(result.metadata.chars_per_page or [])
    return total_chars < min_chars


def should_run_ocr(
    blob: Blob,
    ctx: ParseContext,
    pdf_result: PdfParseResult,
    settings: Settings,
) -> bool:
    """Decide whether OCR should run for this PDF blob."""
    if not settings.ocr_enabled or not _doc_parser_is_available():
        return False
    if not _pdf_needs_ocr(pdf_result, settings.ocr_min_chars):
        return False
    # Direct PDF upload (UI or CLI): root blob, no parent.
    if blob.relation_to_parent is None and ctx.parent_id is None:
        return True
    # Email attachment / embedded / forwarded PDF child.
    if blob.relation_to_parent is not None:
        return True
    return False


class PdfPymupdfParser:
    """Email-parser plugin that delegates PDF work to pdf_tool with optional OCR."""

    name = "pdf_pymupdf"
    version = ENGINE_VERSION
    priority = 20

    def can_handle(self, mime_type: str, sniffed: bytes) -> bool:
        """Claim PDF blobs by MIME type or %PDF- magic bytes."""
        return is_pdf(sniffed, mime_type)

    def parse(self, blob: Blob, ctx: ParseContext) -> ParseResult:
        """Parse a PDF via pdf_tool and optionally fall back to document_parser OCR."""
        settings = load_settings()
        raw = blob.raw
        doc_id = make_doc_id(raw)
        result = parse_pdf(raw, filename=blob.filename)

        warnings = list(result.warnings)
        blocks = to_email_blocks(doc_id, result.blocks)
        parser_name = self.name
        native = NativeMetadata(
            producer=result.metadata.producer,
            has_text_layer=result.metadata.has_text_layer,
            needs_ocr=result.metadata.needs_ocr,
            chars_per_page=result.metadata.chars_per_page,
        )

        if should_run_ocr(blob, ctx, result, settings):
            from document_parser import parse_pdf as ocr_parse_pdf

            ocr_result = ocr_parse_pdf(raw, filename=blob.filename, dpi=settings.ocr_dpi)
            warnings.extend(ocr_result.warnings)
            if ocr_result.status.value == "ok" and ocr_result.blocks:
                blocks = to_email_blocks(doc_id, ocr_result.blocks)
                parser_name = f"{self.name}+document_parser"
                native = native.model_copy(
                    update={
                        "needs_ocr": ocr_result.metadata.needs_ocr,
                        "chars_per_page": ocr_result.metadata.chars_per_page,
                        "has_text_layer": ocr_result.metadata.has_text_layer,
                        "ocr_engine": ocr_result.metadata.ocr_engine or "paddle",
                    }
                )
            elif ocr_result.warnings:
                warnings.append(
                    "OCR fallback did not produce blocks; using born-digital extraction"
                )
        elif _pdf_needs_ocr(result, settings.ocr_min_chars) and not _doc_parser_is_available():
            warnings.append(
                "PDF requires OCR but document_parser is not installed "
                "(install with: uv sync --extra ocr)"
            )
        elif _pdf_needs_ocr(result, settings.ocr_min_chars) and not settings.ocr_enabled:
            warnings.append("PDF requires OCR but EMAILPARSE_OCR_ENABLED is false")

        status = ParseStatus.ok if result.status == PdfParseStatus.ok else ParseStatus.failed
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
                    title=result.metadata.title,
                    byte_size=result.metadata.byte_size,
                    page_count=result.metadata.page_count,
                    filename=result.metadata.filename,
                ),
                native=native,
            ),
            blocks=blocks,
            provenance=Provenance(
                parser=parser_name,
                parser_version=self.version,
                parsed_at=None,
                status=status,
                warnings=warnings,
            ),
        )
        return ParseResult(
            document=document,
            child_blobs=to_child_blobs(result.embedded_files),
        )

    def search_quote(
        self,
        raw: bytes,
        needle: str,
        clip: tuple[float, float, float, float] | None,
        page: int,
    ) -> list[list[float]]:
        """Search a page for needle text and return quad point lists."""
        return tool_search_quote(raw, needle, page=page, clip=clip)

    def render_thumbnail(
        self,
        raw: bytes,
        page: int,
        clip: tuple[float, float, float, float],
        dpi: int = 150,
    ) -> bytes:
        """Render a clipped PNG thumbnail for a PDF page region."""
        return tool_render_thumbnail(raw, page, clip, dpi=dpi)
