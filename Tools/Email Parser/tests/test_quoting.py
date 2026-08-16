"""Tests for quote and signature splitting in EmailMimeParser."""

from __future__ import annotations

from email.message import EmailMessage

from email_parser.file_parsers.base import Blob, ParseContext
from email_parser.file_parsers.email_mime import EmailMimeParser
from email_parser.models import BlockType


def test_quoted_lines_become_quoted_history_blocks() -> None:
    """Lines starting with '>' are emitted as quoted_history blocks."""
    body = "\n".join(
        [
            "New reply text.",
            "",
            "> previous line one",
            "> previous line two",
        ]
    )
    msg = EmailMessage()
    msg["Subject"] = "Reply"
    msg["From"] = "sender@example.com"
    msg.set_content(body)

    blocks = EmailMimeParser().parse(Blob(raw=msg.as_bytes()), ParseContext()).document.blocks
    quoted = [block for block in blocks if block.type == BlockType.quoted_history]
    paragraphs = [block for block in blocks if block.type == BlockType.paragraph]

    assert len(paragraphs) == 1
    assert paragraphs[0].text == "New reply text."
    assert len(quoted) == 1
    assert "> previous line one" in quoted[0].text
    assert "> previous line two" in quoted[0].text
