"""Tests for email header normalization in EmailMimeParser."""

from __future__ import annotations

from datetime import UTC, datetime
from email.message import EmailMessage
from email.utils import format_datetime

from email_parser.file_parsers.base import Blob, ParseContext
from email_parser.file_parsers.email_mime import EmailMimeParser


def _build_email(**headers: str) -> bytes:
    """Build a minimal RFC 822 message from header kwargs."""
    msg = EmailMessage()
    msg.set_content("Body text.")
    for key, value in headers.items():
        msg[key.replace("_", "-")] = value
    return msg.as_bytes()


def test_rfc2047_subject_is_decoded() -> None:
    """Encoded-word subjects are decoded into metadata.native.subject."""
    raw = _build_email(Subject="=?UTF-8?B?SGVsbG8gV29ybGQ=?=")
    result = EmailMimeParser().parse(Blob(raw=raw), ParseContext())
    assert result.document.metadata.native.subject == "Hello World"
    assert result.document.metadata.common.title == "Hello World"


def test_addresses_split_into_name_addr_domain() -> None:
    """To/Cc/From headers are split into display name, addr, and domain."""
    raw = _build_email(
        From='"Alice Example" <alice@example.com>',
        To='"Bob One" <bob.one@example.org>, Carol <carol@example.net>',
        Cc="dan@example.com",
    )
    native = EmailMimeParser().parse(Blob(raw=raw), ParseContext()).document.metadata.native
    assert native.from_name == "Alice Example"
    assert native.from_addr == "alice@example.com"
    assert native.from_domain == "example.com"
    assert native.to == [
        {"name": "Bob One", "addr": "bob.one@example.org", "domain": "example.org"},
        {"name": "Carol", "addr": "carol@example.net", "domain": "example.net"},
    ]
    assert native.cc == [{"name": "", "addr": "dan@example.com", "domain": "example.com"}]


def test_date_normalized_to_utc_iso() -> None:
    """Date headers are converted to UTC ISO while preserving the original string."""
    aware = format_datetime(datetime(2024, 1, 15, 10, 30, tzinfo=UTC))
    raw = _build_email(Date=aware)
    native = EmailMimeParser().parse(Blob(raw=raw), ParseContext()).document.metadata.native
    assert native.date_utc == "2024-01-15T10:30:00+00:00"
    assert native.date_original == aware
