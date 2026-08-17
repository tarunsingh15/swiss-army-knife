"""Shared mapping from pdf_tool / document_parser results to email-parser models."""

from __future__ import annotations

from email_parser.file_parsers.base import Blob
from email_parser.ids import make_block_id
from email_parser.models import Anchor, Block, BlockType, RelationType
from pdf_tool.models import PdfBlockType

_BLOCK_TYPE_MAP: dict[str, BlockType] = {
    PdfBlockType.paragraph.value: BlockType.paragraph,
    PdfBlockType.heading.value: BlockType.heading,
    PdfBlockType.table.value: BlockType.table,
    PdfBlockType.form_field.value: BlockType.form_field,
}


def to_email_blocks(doc_id: str, result_blocks) -> list[Block]:
    """Map generic pdf_tool or document_parser blocks into email-parser Block models."""
    blocks: list[Block] = []
    for ordinal, item in enumerate(result_blocks):
        block_type = _BLOCK_TYPE_MAP[item.block_type.value]
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


def to_child_blobs(embedded_files) -> list[Blob]:
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
