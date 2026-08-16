"""Tests for content-addressed document and block IDs."""

from email_parser.ids import make_block_id, make_doc_id


def test_make_doc_id_stable() -> None:
    """Same bytes produce identical doc ids on repeated calls."""
    data = b"same bytes twice"
    assert make_doc_id(data) == make_doc_id(data)


def test_make_doc_id_differs() -> None:
    """Different bytes produce different doc ids."""
    assert make_doc_id(b"alpha") != make_doc_id(b"beta")


def test_make_doc_id_prefix() -> None:
    """Document ids are prefixed with sha256:."""
    doc_id = make_doc_id(b"prefix test")
    assert doc_id.startswith("sha256:")


def test_block_id_stable_and_positional() -> None:
    """Block ids are stable, ordinal-sensitive, and sanitize block types."""
    doc_id = make_doc_id(b"block test")

    block_a = make_block_id(doc_id, 0, "paragraph")
    block_b = make_block_id(doc_id, 0, "paragraph")
    block_next = make_block_id(doc_id, 1, "paragraph")
    block_heading = make_block_id(doc_id, 0, "Heading 1")

    assert block_a == block_b
    assert block_a != block_next
    assert block_a == f"{doc_id}:b0000:paragraph"
    assert block_heading == f"{doc_id}:b0000:heading_1"
