"""Tests for cid: inline image linkage in EmailMimeParser."""

from __future__ import annotations

from email.message import EmailMessage

from email_parser.file_parsers.base import Blob, ParseContext
from email_parser.file_parsers.email_mime import EmailMimeParser
from email_parser.ids import make_doc_id
from email_parser.models import BlockType, RelationType


def test_cid_image_ref_points_at_inline_image_doc_id() -> None:
    """image_ref.child_doc_id matches make_doc_id for the inline image bytes."""
    image_bytes = b"\x89PNG\r\n\x1a\nfake-image-bytes"

    msg = EmailMessage()
    msg["Subject"] = "Inline image"
    msg["From"] = "sender@example.com"
    html = '<html><body><p>Look:</p><img src="cid:logo123"></body></html>'
    msg.set_content(html, subtype="html")
    msg.add_related(
        image_bytes,
        maintype="image",
        subtype="png",
        cid="logo123",
        filename="logo.png",
    )

    result = EmailMimeParser().parse(Blob(raw=msg.as_bytes()), ParseContext())
    inline_blobs = [
        blob for blob in result.child_blobs if blob.relation_to_parent == RelationType.inline_image
    ]
    image_refs = [block for block in result.document.blocks if block.type == BlockType.image_ref]

    assert len(inline_blobs) == 1
    assert len(image_refs) == 1
    expected_doc_id = make_doc_id(inline_blobs[0].raw)
    assert image_refs[0].child_doc_id == expected_doc_id
    assert image_refs[0].child_doc_id == make_doc_id(image_bytes)
