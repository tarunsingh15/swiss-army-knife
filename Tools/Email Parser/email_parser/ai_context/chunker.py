"""Provenance-carrying document chunks for retrieval."""

from __future__ import annotations

from email_parser.models import Block, BlockType, Document


def _block_text(block: Block) -> str:
    """Render one block as chunkable plain text."""
    if block.rows:
        lines: list[str] = []
        for row_index, row in enumerate(block.rows):
            escaped = [cell.replace("|", "\\|") for cell in row]
            lines.append("| " + " | ".join(escaped) + " |")
            if row_index == 0:
                lines.append("| " + " | ".join("---" for _ in row) + " |")
        return "\n".join(lines)
    return (block.text or "").strip()


def _page_range(blocks: list[Block]) -> tuple[int | None, int | None]:
    """Return the min/max page numbers covered by block anchors."""
    pages = [
        block.anchor.page
        for block in blocks
        if block.anchor and block.anchor.page is not None
    ]
    if not pages:
        return None, None
    return min(pages), max(pages)


def _provenance_header(
    doc: Document,
    *,
    page_start: int | None,
    page_end: int | None,
) -> str:
    """Build the one-line provenance header for a chunk."""
    relation = doc.relation_to_parent.value if doc.relation_to_parent else "none"
    if page_start is None and page_end is None:
        pages = "None-None"
    elif page_start == page_end:
        pages = f"{page_start}-{page_end}"
    else:
        pages = f"{page_start}-{page_end}"
    return (
        f"[source={doc.source_type.value} doc={doc.doc_id} relation={relation} pages={pages}]"
    )


def chunk_documents(documents: list[Document], max_chars: int = 1200) -> list[dict]:
    """Split documents into provenance-carrying chunks grouped by consecutive blocks."""
    chunks: list[dict] = []

    for doc in documents:
        current_blocks: list[Block] = []
        current_text_parts: list[str] = []
        current_len = 0
        chunk_index = 0

        def flush() -> None:
            nonlocal chunk_index, current_blocks, current_text_parts, current_len
            if not current_blocks:
                return
            page_start, page_end = _page_range(current_blocks)
            header = _provenance_header(doc, page_start=page_start, page_end=page_end)
            body = "\n\n".join(part for part in current_text_parts if part)
            chunks.append(
                {
                    "chunk_id": f"{doc.doc_id}:c{chunk_index:04d}",
                    "root_id": doc.root_id or doc.doc_id,
                    "doc_id": doc.doc_id,
                    "relation_to_parent": doc.relation_to_parent,
                    "source_block_ids": [block.block_id for block in current_blocks],
                    "page_start": page_start,
                    "page_end": page_end,
                    "text": f"{header}\n\n{body}".rstrip(),
                }
            )
            chunk_index += 1
            current_blocks = []
            current_text_parts = []
            current_len = 0

        for block in doc.blocks:
            if block.type in {BlockType.image_ref}:
                continue
            text = _block_text(block)
            if not text:
                continue
            addition = len(text) if not current_text_parts else len(text) + 2
            if current_blocks and current_len + addition > max_chars:
                flush()
            current_blocks.append(block)
            current_text_parts.append(text)
            current_len += addition if current_len else len(text)

        flush()

    return chunks
