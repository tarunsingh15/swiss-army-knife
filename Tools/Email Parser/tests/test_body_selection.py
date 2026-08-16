"""Tests for multipart/alternative body selection in EmailMimeParser."""

from __future__ import annotations

from email.message import EmailMessage

from email_parser.file_parsers.base import Blob, ParseContext
from email_parser.file_parsers.email_mime import EmailMimeParser
from email_parser.models import BlockType


def test_multipart_alternative_prefers_html() -> None:
    """When both text/plain and text/html exist, HTML blocks are chosen."""
    msg = EmailMessage()
    msg["Subject"] = "Alternative"
    msg["From"] = "sender@example.com"
    msg.set_content("Plain fallback only.")
    msg.add_alternative(
        "<html><body><h1>HTML Title</h1><p>HTML paragraph.</p></body></html>",
        subtype="html",
    )

    document = EmailMimeParser().parse(Blob(raw=msg.as_bytes()), ParseContext()).document
    texts = [block.text for block in document.blocks if block.text]
    types = [block.type for block in document.blocks]

    assert BlockType.heading in types
    assert "HTML Title" in texts
    assert "HTML paragraph." in texts
    assert "Plain fallback only." not in texts
