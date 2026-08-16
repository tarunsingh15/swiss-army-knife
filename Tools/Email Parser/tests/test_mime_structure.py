"""Tests for MIME structure handling in EmailMimeParser."""

from __future__ import annotations

from email.message import EmailMessage

from email_parser.file_parsers.base import Blob, ParseContext
from email_parser.file_parsers.email_mime import EmailMimeParser
from email_parser.models import RelationType


def test_attachment_count_and_ordinals() -> None:
    """Attachments are emitted as child blobs with preserved ordinals."""
    msg = EmailMessage()
    msg["Subject"] = "Attachments"
    msg["From"] = "sender@example.com"
    msg.set_content("See attached.")

    for filename, payload in (
        ("one.txt", b"first"),
        ("two.txt", b"second"),
    ):
        msg.add_attachment(payload, maintype="text", subtype="plain", filename=filename)

    result = EmailMimeParser().parse(Blob(raw=msg.as_bytes()), ParseContext())
    attachments = [
        blob for blob in result.child_blobs if blob.relation_to_parent == RelationType.attachment
    ]
    assert len(attachments) == 2
    assert [blob.ordinal for blob in attachments] == [0, 1]
    assert {blob.filename for blob in attachments} == {"one.txt", "two.txt"}


def test_forwarded_message_yields_child_blob() -> None:
    """Nested message/rfc822 parts become forwarded_message child blobs."""
    forwarded = EmailMessage()
    forwarded["Subject"] = "Original"
    forwarded["From"] = "orig@example.com"
    forwarded.set_content("Forwarded body.")

    msg = EmailMessage()
    msg["Subject"] = "Forward wrapper"
    msg["From"] = "sender@example.com"
    msg.set_content("Please see below.")
    msg.add_attachment(forwarded, subtype="rfc822")

    result = EmailMimeParser().parse(Blob(raw=msg.as_bytes()), ParseContext())
    forwarded_blobs = [
        blob
        for blob in result.child_blobs
        if blob.relation_to_parent == RelationType.forwarded_message
    ]
    assert len(forwarded_blobs) == 1
    assert b"Forwarded body." in forwarded_blobs[0].raw
