"""Email-parser adapter around the standalone pdf_tool package."""

from __future__ import annotations

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
from pdf_tool import (
    PdfBlockType,
    PdfParseStatus,
    is_pdf,
    parse_pdf,
    render_thumbnail as tool_render_thumbnail,
    search_quote as tool_search_quote,
)
from pdf_tool.pymupdf_engine import ENGINE_VERSION

_BLOCK_TYPE_MAP: dict[PdfBlockType, BlockType] = {
    PdfBlockType.paragraph: BlockType.paragraph,
    PdfBlockType.heading: BlockType.heading,
    PdfBlockType.table: BlockType.table,
    PdfBlockType.form_field: BlockType.form_field,
}


def _to_email_blocks(doc_id: str, result_blocks) -> list[Block]:
    """Map generic pdf_tool blocks into email-parser Block models."""
    blocks: list[Block] = []
    for ordinal, item in enumerate(result_blocks):
        block_type = _BLOCK_TYPE_MAP[item.block_type]
        anchor = None
        if item.anchor is not None:
            anchor = Anchor(page=item.anchor.page, bbox=item.anchor.bbox)
        blocks.append(
            Block(
                block_id=make_block_id(doc_id, ordinal, block_type.value),
                type=block_type,
                text=item.text,
                rows=item.rows,
                anchor=anchor,
            )
        )
    return blocks


def _to_child_blobs(embedded_files) -> list[Blob]:
    """Map embedded pdf_tool files into pipeline child blobs."""
    child_blobs: list[Blob] = []
    for index, item in enumerate(embedded_files):
        child_blobs.append(
            Blob(
                raw=item.raw,
                filename=item.filename,
                mime_type=item.mime_type,
                relation_to_parent=RelationType.embedded_file,
                ordinal=index,
            )
        )
    return child_blobs


class PdfPymupdfParser:
    """Email-parser plugin that delegates PDF work to pdf_tool."""

    name = "pdf_pymupdf"
    version = ENGINE_VERSION
    priority = 20

    def can_handle(self, mime_type: str, sniffed: bytes) -> bool:
        """Claim PDF blobs by MIME type or %PDF- magic bytes."""
        return is_pdf(sniffed, mime_type)

    def parse(self, blob: Blob, ctx: ParseContext) -> ParseResult:
        """Parse a PDF blob via pdf_tool and map the result to email-parser models."""
        raw = blob.raw
        doc_id = make_doc_id(raw)
        result = parse_pdf(raw, filename=blob.filename)

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
                native=NativeMetadata(
                    producer=result.metadata.producer,
                    has_text_layer=result.metadata.has_text_layer,
                    needs_ocr=result.metadata.needs_ocr,
                    chars_per_page=result.metadata.chars_per_page,
                ),
            ),
            blocks=_to_email_blocks(doc_id, result.blocks),
            provenance=Provenance(
                parser=self.name,
                parser_version=self.version,
                parsed_at=None,
                status=status,
                warnings=list(result.warnings),
            ),
        )
        return ParseResult(
            document=document,
            child_blobs=_to_child_blobs(result.embedded_files),
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
