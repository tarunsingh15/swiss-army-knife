"""Header-only email peek helpers for upload previews."""

from __future__ import annotations

import email.policy
from email.parser import BytesHeaderParser
from email.utils import parseaddr

_HEADER_PARSER = BytesHeaderParser(policy=email.policy.default)


def peek_headers(raw: bytes, filename: str) -> list[dict]:
    """Return sender, date, and subject for each message in raw bytes."""
    lowered = filename.lower()
    if lowered.endswith(".mbox"):
        return _peek_mbox(raw, filename)
    return [_peek_single_message(raw, filename, message_index=0)]


def _peek_single_message(raw: bytes, filename: str, *, message_index: int) -> dict:
    """Parse headers for one RFC 822 message without reading the body."""
    msg = _HEADER_PARSER.parsebytes(raw)
    from_name, from_addr = parseaddr(msg.get("From", ""))
    sender = from_name or from_addr or None
    if from_name and from_addr:
        sender = f"{from_name} <{from_addr}>"
    return {
        "filename": filename,
        "sender": sender,
        "date": msg.get("Date"),
        "subject": msg.get("Subject"),
        "message_index": message_index,
    }


def _peek_mbox(raw: bytes, filename: str) -> list[dict]:
    """Split an mbox file and peek headers for each contained message."""
    text = raw.decode("utf-8", errors="replace")
    chunks: list[str] = []
    current: list[str] = []
    for line in text.splitlines(keepends=True):
        if line.startswith("From ") and current:
            chunks.append("".join(current))
            current = [line]
        else:
            current.append(line)
    if current:
        chunks.append("".join(current))

    results: list[dict] = []
    for index, chunk in enumerate(chunks):
        chunk_bytes = chunk.encode("utf-8", errors="replace")
        results.append(_peek_single_message(chunk_bytes, filename, message_index=index))
    return results or [_peek_single_message(raw, filename, message_index=0)]
