"""Parser for RFC 822 / MIME email messages."""

from __future__ import annotations

import email.policy
import re
from datetime import UTC
from email import message_from_bytes
from email.message import EmailMessage, Message
from email.parser import BytesParser
from email.utils import getaddresses, parseaddr, parsedate_to_datetime

from selectolax.parser import HTMLParser

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

try:
    import puremagic
except ImportError:  # pragma: no cover
    puremagic = None  # type: ignore[assignment]

try:
    import quotequail
except ImportError:  # pragma: no cover
    quotequail = None  # type: ignore[assignment]

try:
    from charset_normalizer import from_bytes as charset_from_bytes
except ImportError:  # pragma: no cover
    charset_from_bytes = None  # type: ignore[assignment]

_EMAIL_MIME_TYPES = frozenset({"message/rfc822", "message/rfc2822"})
_HEADER_PREFIXES = (
    b"From:",
    b"Return-Path:",
    b"Received:",
    b"MIME-Version:",
    b"From ",
)
_SNIFF_WINDOW = 2048


def _normalize_cid(value: str) -> str:
    """Strip angle brackets and whitespace from a Content-ID value."""
    cid = value.strip()
    if cid.startswith("<") and cid.endswith(">"):
        return cid[1:-1]
    return cid


def _sniff_mime(raw: bytes, fallback: str) -> str:
    """Guess MIME type from magic bytes, falling back to the declared type."""
    if not raw:
        return fallback
    if puremagic is not None:
        try:
            what = getattr(puremagic, "what", None)
            if callable(what):
                guessed = what(None, raw)
                if guessed:
                    return guessed
            matches = puremagic.magic_string(raw)
            if matches:
                return matches[0].mime_type
        except Exception:
            pass
    return fallback


def _decode_bytes(raw: bytes, declared_charset: str | None = None) -> str:
    """Decode bytes using declared charset, then charset-normalizer, then replace."""
    if declared_charset:
        try:
            return raw.decode(declared_charset)
        except (LookupError, UnicodeDecodeError):
            pass
    if charset_from_bytes is not None:
        match = charset_from_bytes(raw).best()
        if match is not None:
            return str(match)
    return raw.decode("utf-8", errors="replace")


def _get_part_bytes(part: Message) -> bytes:
    """Return the raw payload bytes for a MIME part."""
    payload = part.get_payload(decode=True)
    if isinstance(payload, bytes):
        return payload
    if isinstance(payload, str):
        return payload.encode("utf-8", errors="replace")
    nested = part.get_payload()
    if isinstance(nested, list) and nested:
        first = nested[0]
        if isinstance(first, Message):
            return first.as_bytes()
    if isinstance(nested, Message):
        return nested.as_bytes()
    return part.as_bytes()


def _decode_part_text(part: Message) -> str:
    """Decode a text/* MIME part to a Python string."""
    charset = part.get_content_charset()
    try:
        content = part.get_content()
        if isinstance(content, str):
            return content
    except Exception:
        pass
    raw = part.get_payload(decode=True)
    if isinstance(raw, bytes):
        return _decode_bytes(raw, charset)
    if raw is None:
        return ""
    return str(raw)


def _parse_address_entry(name: str, addr: str) -> dict[str, str]:
    """Split one address into display name, addr, and domain fields."""
    domain = addr.rsplit("@", 1)[1] if "@" in addr else ""
    return {"name": name, "addr": addr, "domain": domain}


def _parse_address_list(header_value: str | None) -> list[dict[str, str]]:
    """Parse a comma-separated address header into structured entries."""
    if not header_value:
        return []
    return [_parse_address_entry(name, addr) for name, addr in getaddresses([header_value]) if addr]


def _parse_references(header_value: str | None) -> list[str] | None:
    """Split a References header into individual message-id tokens."""
    if not header_value:
        return None
    tokens = re.findall(r"<[^>]+>", header_value)
    if tokens:
        return tokens
    parts = header_value.split()
    return parts or None


def _parse_date(date_header: str | None) -> tuple[str | None, str | None]:
    """Return UTC ISO timestamp and the original Date header string."""
    if not date_header:
        return None, None
    try:
        dt = parsedate_to_datetime(date_header)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        date_utc = dt.astimezone(UTC).isoformat()
        return date_utc, date_header
    except (TypeError, ValueError, IndexError):
        return None, date_header


def _extract_headers(msg: EmailMessage) -> NativeMetadata:
    """Build native metadata from standard email headers."""
    from_name, from_addr = parseaddr(msg.get("From", ""))
    date_utc, date_original = _parse_date(msg.get("Date"))
    references = _parse_references(msg.get("References"))
    from_domain = from_addr.rsplit("@", 1)[1] if "@" in from_addr else ""
    return NativeMetadata(
        from_name=from_name or None,
        from_addr=from_addr or None,
        from_domain=from_domain or None,
        to=_parse_address_list(msg.get("To")) or None,
        cc=_parse_address_list(msg.get("Cc")) or None,
        subject=msg.get("Subject"),
        date_utc=date_utc,
        date_original=date_original,
        message_id=msg.get("Message-ID"),
        in_reply_to=msg.get("In-Reply-To"),
        references=references,
    )


def _looks_like_email_sniff(sniffed: bytes) -> bool:
    """Return True when sniffed bytes resemble an RFC 822 message."""
    if not sniffed:
        return False
    window = sniffed[:_SNIFF_WINDOW]
    if any(window.startswith(prefix) for prefix in _HEADER_PREFIXES):
        return True
    return b"\nFrom:" in window


def _is_forwarded_part(part: Message) -> bool:
    """Return True for nested message/rfc822 payloads."""
    return part.get_content_type() in _EMAIL_MIME_TYPES


def _is_inline_image_part(part: Message) -> bool:
    """Return True for inline image parts referenced by cid: URLs."""
    content_type = part.get_content_type()
    if not content_type.startswith("image/"):
        return False
    disposition = part.get_content_disposition()
    content_id = part.get("Content-ID")
    return disposition == "inline" or bool(content_id)


def _is_attachment_part(part: Message) -> bool:
    """Return True when a part should be emitted as an attachment blob."""
    disposition = part.get_content_disposition()
    if disposition == "attachment":
        return True
    if part.get_filename():
        return True
    content_type = part.get_content_type()
    return content_type.startswith("application/")


def _choose_alternative_part(parts: list[Message]) -> Message | None:
    """Pick one multipart/alternative body, preferring HTML over plain text."""
    html_part: Message | None = None
    plain_part: Message | None = None
    for part in parts:
        content_type = part.get_content_type()
        if content_type == "text/html":
            html_part = part
        elif content_type == "text/plain":
            plain_part = part
    return html_part or plain_part


def _find_body_part(msg: Message) -> tuple[Message | None, str | None]:
    """Locate the primary body part and its MIME type."""
    if msg.is_multipart():
        if msg.get_content_type() == "multipart/alternative":
            chosen = _choose_alternative_part(list(msg.iter_parts()))
            if chosen is None:
                return None, None
            if chosen.is_multipart():
                return _find_body_part(chosen)
            return chosen, chosen.get_content_type()
        for part in msg.iter_parts():
            if part.get_content_type() == "multipart/alternative":
                chosen = _choose_alternative_part(list(part.iter_parts()))
                if chosen is not None:
                    if chosen.is_multipart():
                        nested_part, nested_type = _find_body_part(chosen)
                        if nested_part is not None:
                            return nested_part, nested_type
                    else:
                        return chosen, chosen.get_content_type()
            elif part.get_content_type() in ("text/html", "text/plain"):
                return part, part.get_content_type()
            elif part.is_multipart():
                nested_part, nested_type = _find_body_part(part)
                if nested_part is not None:
                    return nested_part, nested_type
        return None, None
    content_type = msg.get_content_type()
    if content_type in ("text/html", "text/plain"):
        return msg, content_type
    return None, None


def _collect_child_blobs(
    msg: Message,
    body_part: Message | None,
    ordinal: int,
) -> tuple[list[Blob], dict[str, str], int]:
    """Walk the MIME tree and collect child blobs plus a cid lookup map."""
    child_blobs: list[Blob] = []
    cid_map: dict[str, str] = {}

    def walk(part: Message, inside_chosen_alternative: bool = False) -> None:
        nonlocal ordinal

        if part is body_part:
            return

        if _is_forwarded_part(part):
            raw = _get_part_bytes(part)
            child_blobs.append(
                Blob(
                    raw=raw,
                    filename=part.get_filename(),
                    mime_type=_sniff_mime(raw, part.get_content_type()),
                    relation_to_parent=RelationType.forwarded_message,
                    ordinal=ordinal,
                )
            )
            ordinal += 1
            return

        if part.is_multipart():
            if part.get_content_type() == "multipart/alternative":
                chosen = _choose_alternative_part(list(part.iter_parts()))
                for subpart in part.iter_parts():
                    if subpart is chosen:
                        walk(subpart, inside_chosen_alternative=True)
                    elif not inside_chosen_alternative:
                        walk(subpart, inside_chosen_alternative=False)
                return
            for subpart in part.iter_parts():
                walk(subpart, inside_chosen_alternative=inside_chosen_alternative)
            return

        if _is_inline_image_part(part):
            raw = _get_part_bytes(part)
            content_id = part.get("Content-ID")
            normalized_cid = _normalize_cid(content_id) if content_id else None
            child_blobs.append(
                Blob(
                    raw=raw,
                    filename=part.get_filename(),
                    mime_type=_sniff_mime(raw, part.get_content_type()),
                    relation_to_parent=RelationType.inline_image,
                    ordinal=ordinal,
                    content_id=normalized_cid,
                )
            )
            if normalized_cid:
                cid_map[normalized_cid] = make_doc_id(raw)
            ordinal += 1
            return

        if _is_attachment_part(part):
            raw = _get_part_bytes(part)
            child_blobs.append(
                Blob(
                    raw=raw,
                    filename=part.get_filename(),
                    mime_type=_sniff_mime(raw, part.get_content_type()),
                    relation_to_parent=RelationType.attachment,
                    ordinal=ordinal,
                )
            )
            ordinal += 1

    walk(msg)
    return child_blobs, cid_map, ordinal


def _split_signature(text: str) -> tuple[str, str | None]:
    """Split trailing signature content after a line that is exactly '-- '."""
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line == "-- ":
            body = "\n".join(lines[:index]).strip("\n")
            signature = "\n".join(lines[index:]).strip("\n")
            return body, signature or None
    return text, None


def _split_plain_paragraphs(text: str) -> list[str]:
    """Split plain text into paragraphs on blank lines."""
    chunks = re.split(r"\n\s*\n", text.strip())
    return [chunk.strip() for chunk in chunks if chunk.strip()]


def _append_block(
    blocks: list[Block],
    doc_id: str,
    ordinal: int,
    block_type: BlockType,
    *,
    text: str | None = None,
    rows: list[list[str]] | None = None,
    child_doc_id: str | None = None,
) -> int:
    """Append one block and return the next ordinal."""
    blocks.append(
        Block(
            block_id=make_block_id(doc_id, ordinal, block_type.value),
            type=block_type,
            text=text,
            rows=rows,
            child_doc_id=child_doc_id,
            anchor=Anchor(),
        )
    )
    return ordinal + 1


def _emit_plain_segment(
    blocks: list[Block],
    doc_id: str,
    ordinal: int,
    text: str,
    *,
    force_quoted: bool = False,
) -> int:
    """Convert one plain-text segment into paragraph or quoted_history blocks."""
    if force_quoted:
        cleaned = text.strip("\n")
        if cleaned:
            ordinal = _append_block(
                blocks,
                doc_id,
                ordinal,
                BlockType.quoted_history,
                text=cleaned,
            )
        return ordinal

    current_paragraph: list[str] = []
    current_quoted: list[str] = []

    def flush_paragraph() -> None:
        nonlocal ordinal
        if not current_paragraph:
            return
        paragraph = "\n".join(current_paragraph).strip()
        if paragraph:
            ordinal = _append_block(
                blocks,
                doc_id,
                ordinal,
                BlockType.paragraph,
                text=paragraph,
            )
        current_paragraph.clear()

    def flush_quoted() -> None:
        nonlocal ordinal
        if not current_quoted:
            return
        quoted = "\n".join(current_quoted).strip()
        if quoted:
            ordinal = _append_block(
                blocks,
                doc_id,
                ordinal,
                BlockType.quoted_history,
                text=quoted,
            )
        current_quoted.clear()

    for line in text.splitlines():
        if line.startswith(">"):
            flush_paragraph()
            current_quoted.append(line)
            continue
        if line.strip() == "":
            flush_paragraph()
            flush_quoted()
            continue
        flush_quoted()
        current_paragraph.append(line)

    flush_paragraph()
    flush_quoted()
    return ordinal


def _plain_to_blocks(text: str, doc_id: str, ordinal: int) -> tuple[list[Block], int]:
    """Split plain text into paragraph, quoted_history, and signature blocks."""
    blocks: list[Block] = []
    body, signature = _split_signature(text)
    segments: list[tuple[bool, str]]
    if quotequail is not None:
        try:
            segments = quotequail.quote(body)
        except Exception:
            segments = [(True, body)]
    else:
        segments = [(True, body)]

    for expand, segment_text in segments:
        if not segment_text:
            continue
        if expand:
            ordinal = _emit_plain_segment(blocks, doc_id, ordinal, segment_text)
        else:
            ordinal = _emit_plain_segment(
                blocks,
                doc_id,
                ordinal,
                segment_text,
                force_quoted=True,
            )

    if signature:
        ordinal = _append_block(
            blocks,
            doc_id,
            ordinal,
            BlockType.signature,
            text=signature,
        )
    return blocks, ordinal


def _table_rows(table_node) -> list[list[str]]:
    """Extract table rows from a selectolax table node."""
    rows: list[list[str]] = []
    for row in table_node.css("tr"):
        cells = [cell.text(strip=True) for cell in row.css("th, td")]
        if cells:
            rows.append(cells)
    return rows


def _html_to_blocks(html: str, doc_id: str, ordinal: int, cid_map: dict[str, str]) -> tuple[list[Block], int]:
    """Convert HTML body content into structured blocks."""
    blocks: list[Block] = []
    tree = HTMLParser(html)
    root = tree.body or tree.root
    if root is None:
        return blocks, ordinal

    for node in root.css("h1, h2, h3, p, li, table, img"):
        if node.tag in {"h1", "h2", "h3"}:
            text = node.text(strip=True)
            if text:
                ordinal = _append_block(blocks, doc_id, ordinal, BlockType.heading, text=text)
        elif node.tag == "p":
            text = node.text(strip=True)
            if text:
                ordinal = _append_block(blocks, doc_id, ordinal, BlockType.paragraph, text=text)
        elif node.tag == "li":
            text = node.text(strip=True)
            if text:
                ordinal = _append_block(blocks, doc_id, ordinal, BlockType.list, text=text)
        elif node.tag == "table":
            rows = _table_rows(node)
            if rows:
                ordinal = _append_block(blocks, doc_id, ordinal, BlockType.table, rows=rows)
        elif node.tag == "img":
            src = node.attributes.get("src", "")
            if src.startswith("cid:"):
                cid = _normalize_cid(src[4:])
                ordinal = _append_block(
                    blocks,
                    doc_id,
                    ordinal,
                    BlockType.image_ref,
                    text=src,
                    child_doc_id=cid_map.get(cid),
                )
    return blocks, ordinal


def _body_to_blocks(
    body_part: Message | None,
    body_type: str | None,
    doc_id: str,
    cid_map: dict[str, str],
) -> list[Block]:
    """Convert the selected body part into ordered blocks."""
    if body_part is None or body_type is None:
        return []
    content = _decode_part_text(body_part)
    ordinal = 0
    if body_type == "text/html":
        blocks, _ = _html_to_blocks(content, doc_id, ordinal, cid_map)
        return blocks
    blocks, _ = _plain_to_blocks(content, doc_id, ordinal)
    return blocks


class EmailMimeParser:
    """Parse RFC 822 / MIME email blobs into documents and child blobs."""

    name = "email_mime"
    version = "0.1.0"
    priority = 10

    def can_handle(self, mime_type: str, sniffed: bytes) -> bool:
        """Return True when the blob looks like an RFC 822 email message."""
        lowered = (mime_type or "").lower()
        if lowered == "application/vnd.ms-outlook":
            return False
        if lowered in _EMAIL_MIME_TYPES:
            return True
        return _looks_like_email_sniff(sniffed)

    def parse(self, blob: Blob, ctx: ParseContext) -> ParseResult:
        """Parse one email blob into a document and child blobs for the pipeline."""
        msg = BytesParser(policy=email.policy.default).parsebytes(blob.raw)
        if not isinstance(msg, EmailMessage):
            msg = message_from_bytes(blob.raw, policy=email.policy.default)
        native = _extract_headers(msg)
        body_part, body_type = _find_body_part(msg)
        child_blobs, cid_map, _ = _collect_child_blobs(msg, body_part, ordinal=0)
        doc_id = make_doc_id(blob.raw)
        blocks = _body_to_blocks(body_part, body_type, doc_id, cid_map)
        document = Document(
            doc_id=doc_id,
            source_type=SourceType.email,
            mime_type="message/rfc822",
            root_id=ctx.root_id or doc_id,
            parent_id=ctx.parent_id,
            depth=ctx.depth,
            metadata=DocumentMetadata(
                common=CommonMetadata(
                    filename=blob.filename,
                    byte_size=len(blob.raw),
                    title=native.subject,
                ),
                native=native,
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
