"""Tier B health metrics and structural invariant checks."""

from __future__ import annotations

from email_parser.models import BlockType, Document, SourceType


def _block_text_chars(block) -> int:
    """Return character count for a block's textual payload."""
    if block.text:
        return len(block.text)
    if block.rows:
        return sum(len(cell) for row in block.rows for cell in row)
    return 0


def _anchor_is_empty(anchor) -> bool:
    """Return True when an anchor carries no page, bbox, or quads."""
    return (
        anchor.page is None
        and anchor.bbox is None
        and not anchor.quads
    )


def _block_anchor_covered(block, source_type: SourceType) -> bool:
    """Return True when a block satisfies anchor coverage rules for its source."""
    if block.anchor is None:
        return False
    if source_type == SourceType.email:
        if _anchor_is_empty(block.anchor):
            return False
        return True
    return block.anchor.page is not None or block.anchor.bbox is not None


def check_invariants(documents: list[Document]) -> list[str]:
    """Return human-readable invariant violation messages for a document set."""
    violations: list[str] = []
    doc_ids = {doc.doc_id for doc in documents}
    anchor_required_types = {
        BlockType.table,
        BlockType.heading,
        BlockType.paragraph,
    }

    for doc in documents:
        if doc.parent_id is not None and doc.parent_id not in doc_ids:
            violations.append(
                f"orphan parent_id {doc.parent_id!r} on document {doc.doc_id!r}"
            )

        if doc.depth > 10:
            violations.append(
                f"depth {doc.depth} exceeds cap on document {doc.doc_id!r}"
            )

        seen_block_ids: set[str] = set()
        for block in doc.blocks:
            if block.block_id in seen_block_ids:
                violations.append(
                    f"duplicate block_id {block.block_id!r} in document {doc.doc_id!r}"
                )
            seen_block_ids.add(block.block_id)

            if doc.source_type == SourceType.email:
                continue
            if block.type not in anchor_required_types:
                continue
            anchor = block.anchor
            if anchor is None or (anchor.page is None and anchor.bbox is None):
                violations.append(
                    f"missing page+bbox on {block.type.value} block "
                    f"{block.block_id!r} in document {doc.doc_id!r}"
                )

    return violations


def compute_health_metrics(documents: list[Document]) -> dict:
    """Compute corpus health signals that do not require labeled ground truth."""
    page_char_counts: list[int] = []
    total_block_chars = 0
    quoted_chars = 0
    covered_blocks = 0
    total_blocks = 0
    image_ref_blocks = 0
    resolved_image_refs = 0

    doc_ids = {doc.doc_id for doc in documents}

    for doc in documents:
        if doc.source_type == SourceType.pdf:
            chars_per_page = doc.metadata.native.chars_per_page
            if chars_per_page:
                page_char_counts.extend(chars_per_page)

        for block in doc.blocks:
            total_blocks += 1
            block_chars = _block_text_chars(block)
            total_block_chars += block_chars
            if block.type == BlockType.quoted_history:
                quoted_chars += block_chars
            if _block_anchor_covered(block, doc.source_type):
                covered_blocks += 1
            if block.type == BlockType.image_ref:
                image_ref_blocks += 1
                if block.child_doc_id in doc_ids:
                    resolved_image_refs += 1

    chars_per_page_avg = (
        sum(page_char_counts) / len(page_char_counts) if page_char_counts else 0.0
    )
    anchor_coverage = covered_blocks / total_blocks if total_blocks else 0.0
    quoted_text_ratio = quoted_chars / total_block_chars if total_block_chars else 0.0
    cid_resolution_rate = (
        resolved_image_refs / image_ref_blocks if image_ref_blocks else 1.0
    )

    return {
        "tier": "B",
        "chars_per_page_avg": chars_per_page_avg,
        "anchor_coverage": anchor_coverage,
        "quoted_text_ratio": quoted_text_ratio,
        "cid_resolution_rate": cid_resolution_rate,
        "invariant_violations": check_invariants(documents),
    }
