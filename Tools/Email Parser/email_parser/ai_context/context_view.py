"""Compact markdown context view for model consumption."""

from __future__ import annotations

from email_parser.models import Block, BlockType, Document, ParseStatus, SourceType

try:
    import tiktoken

    _ENCODING = tiktoken.get_encoding("cl100k_base")
except Exception:  # pragma: no cover - optional dependency path
    _ENCODING = None


def _count_tokens(text: str) -> int:
    """Return token count using tiktoken when available, else len//4."""
    if _ENCODING is not None:
        return len(_ENCODING.encode(text))
    return len(text) // 4


def _format_address(entry: dict[str, str]) -> str:
    """Format one to/cc entry as name or address."""
    name = (entry.get("name") or "").strip()
    addr = (entry.get("addr") or entry.get("address") or "").strip()
    if name and addr:
        return f"{name} <{addr}>"
    return name or addr or "unknown"


def _format_recipients(doc: Document) -> str:
    """Join to and cc recipients for the email header."""
    native = doc.metadata.native
    parts: list[str] = []
    for entry in native.to or []:
        formatted = _format_address(entry)
        if formatted:
            parts.append(formatted)
    for entry in native.cc or []:
        formatted = _format_address(entry)
        if formatted:
            parts.append(formatted)
    return ", ".join(parts) if parts else "unknown"


def _format_sender(doc: Document) -> str:
    """Return a display sender string from native metadata."""
    native = doc.metadata.native
    if native.from_name and native.from_addr:
        return f"{native.from_name} <{native.from_addr}>"
    return native.from_name or native.from_addr or native.from_domain or "unknown"


def _attachment_lines(children: list[Document]) -> list[str]:
    """Build A1/A2 attachment summary lines for an email header."""
    lines: list[str] = []
    for index, child in enumerate(children, 1):
        name = child.metadata.common.filename or child.doc_id
        if child.provenance.status == ParseStatus.failed:
            reason = "; ".join(child.provenance.warnings) or child.provenance.status.value
            lines.append(f"  A{index} = {name} — FAILED: {reason}")
            continue
        type_label = child.source_type.value
        pages = child.metadata.common.page_count
        if pages is not None:
            lines.append(f"  A{index} = {name} ({type_label}, {pages}pp)")
        else:
            lines.append(f"  A{index} = {name} ({type_label})")
    return lines


def _select_blocks(
    doc: Document,
    *,
    include_quoted: bool,
    include_signature: bool = False,
) -> list[Block]:
    """Return blocks eligible for the compact context body."""
    selected: list[Block] = []
    for block in doc.blocks:
        if block.type == BlockType.quoted_history and not include_quoted:
            continue
        if block.type == BlockType.signature and not include_signature:
            continue
        selected.append(block)
    return selected


def _block_text(block: Block) -> str:
    """Render a block as plain text for the untrusted fence."""
    if block.rows:
        lines: list[str] = []
        for row_index, row in enumerate(block.rows):
            escaped = [cell.replace("|", "\\|") for cell in row]
            lines.append("| " + " | ".join(escaped) + " |")
            if row_index == 0:
                lines.append("| " + " | ".join("---" for _ in row) + " |")
        return "\n".join(lines)
    return (block.text or "").strip()


def _root_emails(documents: list[Document]) -> list[Document]:
    """Return root email documents in stable ordinal order."""
    roots = [
        doc
        for doc in documents
        if doc.source_type == SourceType.email and (doc.parent_id is None or doc.depth == 0)
    ]
    if roots:
        return sorted(roots, key=lambda item: (item.ordinal, item.doc_id))
    return sorted(
        [doc for doc in documents if doc.source_type == SourceType.email],
        key=lambda item: (item.ordinal, item.doc_id),
    )


def _children_for_root(documents: list[Document], root: Document) -> list[Document]:
    """Return attachment documents belonging to a root email."""
    children = [
        doc
        for doc in documents
        if doc.doc_id != root.doc_id and (doc.root_id == root.doc_id or doc.parent_id == root.doc_id)
    ]
    return sorted(children, key=lambda item: (item.depth, item.ordinal, item.doc_id))


def render_context(
    documents: list[Document],
    token_budget: int = 6000,
    include_quoted: bool = False,
) -> str:
    """Compact markdown for a model. Root emails first, then attachments listed."""
    roots = _root_emails(documents)
    header_lines: list[str] = []
    body_blocks: list[Block] = []

    for email_index, root in enumerate(roots, 1):
        native = root.metadata.native
        date = native.date_utc or native.date_original or "unknown date"
        sender = _format_sender(root)
        recipients = _format_recipients(root)
        subject = native.subject or root.metadata.common.title or "no subject"
        children = _children_for_root(documents, root)
        thread_total = len(roots)
        thread_position = email_index

        header_lines.append(f"EMAIL E{email_index} — {date}, {sender} → {recipients}")
        header_lines.append(f"Subject: {subject}")
        header_lines.append(
            f"Thread: {thread_position} of {thread_total}. Attachments: {len(children)}"
        )
        header_lines.extend(_attachment_lines(children))
        header_lines.append(f"[E{email_index} body, new content only]")
        header_lines.append("")
        body_blocks.extend(_select_blocks(root, include_quoted=include_quoted))

    header = "\n".join(header_lines).rstrip()
    fence_start = "--- untrusted source text begins ---"
    fence_end = "--- untrusted source text ends ---"

    block_texts = [_block_text(block) for block in body_blocks]
    block_texts = [text for text in block_texts if text]

    if not block_texts:
        untrusted_body = ""
    else:
        untrusted_body = "\n\n".join(block_texts)

    truncated = False
    while untrusted_body:
        candidate = f"{header}\n\n{fence_start}\n{untrusted_body}\n{fence_end}"
        if _count_tokens(candidate) <= token_budget:
            return candidate
        if "\n\n" in untrusted_body:
            untrusted_body = untrusted_body.rsplit("\n\n", 1)[0]
            truncated = True
            continue
        if len(untrusted_body) > 1:
            keep = max(1, len(untrusted_body) // 2)
            untrusted_body = untrusted_body[:keep]
            truncated = True
            continue
        untrusted_body = ""
        truncated = True
        break

    suffix = "\n[truncated]\n" if truncated else ""
    if header:
        return f"{header}\n\n{fence_start}\n{untrusted_body}{suffix}{fence_end}"
    return f"{fence_start}\n{untrusted_body}{suffix}{fence_end}"
