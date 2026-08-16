"""Deterministic synthetic .eml fixture generator with ground-truth sidecars."""

from __future__ import annotations

import email.policy
import json
from email.headerregistry import Address
from email.message import EmailMessage
from pathlib import Path
from typing import Any

import pymupdf

from tests.fixtures import pdf_cache

# Fixed metadata for deterministic output.
FIXED_DATE = "Wed, 04 Mar 2026 10:02:00 -0400"
DEFAULT_FROM_NAME = "Alice Example"
DEFAULT_FROM_ADDR = "alice@example.com"
DEFAULT_TO = "bob@example.com"

# Minimal 1x1 PNG (hardcoded bytes).
TINY_PNG = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _pdf_cache_key(
    title: str,
    paragraphs: list[str],
    table: list[list[str]] | None,
    embed_pdf_bytes: bytes | None,
) -> tuple[str, tuple[str, ...], tuple[tuple[str, ...], ...] | None, bytes | None]:
    """Build a hashable cache key for precomputed PDF bytes."""
    table_key = tuple(tuple(row) for row in table) if table else None
    return (title, tuple(paragraphs), table_key, embed_pdf_bytes)


def _precomputed_pdf_bytes() -> dict[tuple[str, tuple[str, ...], tuple[tuple[str, ...], ...] | None, bytes | None], bytes]:
    """Map canonical PDF parameters to stable byte payloads."""
    contract_table = (("Milestone", "Fee"), ("Kickoff", "25000"))
    return {
        _pdf_cache_key(
            "Master Services Agreement",
            ["The fee is twenty five thousand dollars."],
            list(contract_table),
            None,
        ): pdf_cache.CONTRACT_PDF,
        _pdf_cache_key("Exhibit A", ["This is the inner exhibit document."], None, None): pdf_cache.INNER_EXHIBIT_PDF,
        _pdf_cache_key(
            "Bundle Document",
            ["This bundle contains an embedded exhibit PDF."],
            None,
            pdf_cache.INNER_EXHIBIT_PDF,
        ): pdf_cache.OUTER_BUNDLE_PDF,
        _pdf_cache_key("Document A", ["First version of same.pdf."], None, None): pdf_cache.DOC_A_PDF,
        _pdf_cache_key("Document B", ["Second version of same.pdf."], None, None): pdf_cache.DOC_B_PDF,
        _pdf_cache_key("Nested Agreement", ["Innermost forwarded PDF content."], None, None): pdf_cache.NESTED_PDF,
        **{
            _pdf_cache_key(f"Report {index}", [f"Content for report {index}."], None, None): getattr(
                pdf_cache, f"REPORT_{index}_PDF"
            )
            for index in range(1, 6)
        },
    }


_PRECOMPUTED_PDFS = _precomputed_pdf_bytes()


def create_pdf(
    title: str,
    paragraphs: list[str],
    table: list[list[str]] | None = None,
    embed_pdf_bytes: bytes | None = None,
) -> bytes:
    """Build a single-page PDF with optional table layout and embedded PDF file."""
    cache_key = _pdf_cache_key(title, paragraphs, table, embed_pdf_bytes)
    cached = _PRECOMPUTED_PDFS.get(cache_key)
    if cached is not None:
        return cached

    doc = pymupdf.open()
    page = doc.new_page()
    y = 72.0

    page.insert_text((72, y), title, fontsize=16)
    y += 28.0

    for paragraph in paragraphs:
        page.insert_text((72, y), paragraph, fontsize=11)
        y += 18.0

    if table:
        col_width = 120.0
        row_height = 18.0
        for row_idx, row in enumerate(table):
            for col_idx, cell in enumerate(row):
                x = 72.0 + col_idx * col_width
                page.insert_text((x, y + row_idx * row_height), cell, fontsize=10)
        y += len(table) * row_height + 12.0

    if embed_pdf_bytes is not None:
        doc.embfile_add("exhibit.pdf", embed_pdf_bytes)

    doc.set_metadata(
        {
            "title": title,
            "creator": "email-parser-fixtures",
            "producer": "email-parser-fixtures",
            "creationDate": "D:20260304100200-04'00'",
            "modDate": "D:20260304100200-04'00'",
        }
    )
    pdf_bytes = doc.tobytes(garbage=4, deflate=True)
    doc.close()
    return pdf_bytes


def pdf_page_count(data: bytes) -> int:
    """Return the number of pages in PDF bytes, or 0 if unreadable."""
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
        count = doc.page_count
        doc.close()
        return count
    except Exception:
        return 0


def _apply_base_headers(
    msg: EmailMessage,
    subject: str,
    message_id: str,
    *,
    include_date: bool = True,
) -> None:
    """Set standard deterministic headers on a message."""
    msg["From"] = f"{DEFAULT_FROM_NAME} <{DEFAULT_FROM_ADDR}>"
    msg["To"] = DEFAULT_TO
    msg["Subject"] = subject
    if include_date:
        msg["Date"] = FIXED_DATE
    msg["Message-ID"] = f"<{message_id}@fixtures.example>"


def _tree_node(
    relation: str,
    filename: str | None,
    page_count: int | None,
    children: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build one attachment-tree node for truth sidecars."""
    return {
        "relation": relation,
        "filename": filename,
        "page_count": page_count,
        "children": children or [],
    }


def _truth_base(case: str, subject: str, *, has_date: bool = True) -> dict[str, Any]:
    """Shared truth fields for most synthetic cases."""
    return {
        "case": case,
        "decoded_subject": subject,
        "from_name": DEFAULT_FROM_NAME,
        "from_addr": DEFAULT_FROM_ADDR,
        "has_date": has_date,
        "attachment_count": 0,
        "inline_image_count": 0,
        "tree": [],
        "quoted_contains": None,
        "new_body_contains": None,
        "prefer_html": False,
        "alternative_html_contains": None,
        "cid_refs": [],
    }


def _fix_boundaries(msg: EmailMessage, prefix: str) -> None:
    """Assign fixed MIME boundaries so repeated generation yields identical bytes."""
    if not msg.is_multipart():
        return
    msg.set_boundary(f"===============fixture-{prefix}==")
    for index, part in enumerate(msg.iter_parts()):
        if part.is_multipart():
            _fix_boundaries(part, f"{prefix}-p{index}")


def _message_bytes(msg: EmailMessage, boundary_prefix: str) -> bytes:
    """Serialize a message with deterministic multipart boundaries."""
    _fix_boundaries(msg, boundary_prefix)
    return msg.as_bytes()


def _write_case(out_dir: Path, stem: str, msg: EmailMessage, truth: dict[str, Any]) -> Path:
    """Write .eml and matching .truth.json for one fixture case."""
    out_dir.mkdir(parents=True, exist_ok=True)
    eml_path = out_dir / f"{stem}.eml"
    truth_path = out_dir / f"{stem}.truth.json"
    eml_path.write_bytes(_message_bytes(msg, stem))
    truth_path.write_text(json.dumps(truth, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return eml_path


def _case_plain_no_attachment(out_dir: Path) -> Path:
    """Plain text email with no attachments."""
    msg = EmailMessage(policy=email.policy.default)
    _apply_base_headers(msg, "Plain note", "plain-no-attachment")
    msg.set_content("This is a plain text note with no attachments.")
    truth = _truth_base("plain_no_attachment", "Plain note")
    return _write_case(out_dir, "plain_no_attachment", msg, truth)


def _case_single_pdf(out_dir: Path) -> Path:
    """Email with one PDF attachment containing title, paragraph, and table."""
    pdf_bytes = create_pdf(
        "Master Services Agreement",
        ["The fee is twenty five thousand dollars."],
        table=[["Milestone", "Fee"], ["Kickoff", "25000"]],
    )
    msg = EmailMessage(policy=email.policy.default)
    _apply_base_headers(msg, "Contract attached", "single-pdf")
    msg.set_content("Please review the attached contract.")
    msg.add_attachment(pdf_bytes, maintype="application", subtype="pdf", filename="contract.pdf")
    truth = _truth_base("single_pdf", "Contract attached")
    truth["attachment_count"] = 1
    truth["tree"] = [
        _tree_node("attachment", "contract.pdf", pdf_page_count(pdf_bytes)),
    ]
    return _write_case(out_dir, "single_pdf", msg, truth)


def _case_five_pdfs(out_dir: Path) -> Path:
    """Email with five small PDF attachments."""
    msg = EmailMessage(policy=email.policy.default)
    _apply_base_headers(msg, "Five reports", "five-pdfs")
    msg.set_content("Attached are five quarterly reports.")
    tree: list[dict[str, Any]] = []
    for index in range(1, 6):
        filename = f"report_{index}.pdf"
        pdf_bytes = create_pdf(f"Report {index}", [f"Content for report {index}."])
        msg.add_attachment(pdf_bytes, maintype="application", subtype="pdf", filename=filename)
        tree.append(_tree_node("attachment", filename, pdf_page_count(pdf_bytes)))
    truth = _truth_base("five_pdfs", "Five reports")
    truth["attachment_count"] = 5
    truth["tree"] = tree
    return _write_case(out_dir, "five_pdfs", msg, truth)


def _case_pdf_in_pdf(out_dir: Path) -> Path:
    """Email with a PDF that embeds another PDF via embfile_add."""
    inner_pdf = create_pdf("Exhibit A", ["This is the inner exhibit document."])
    outer_pdf = create_pdf(
        "Bundle Document",
        ["This bundle contains an embedded exhibit PDF."],
        embed_pdf_bytes=inner_pdf,
    )
    msg = EmailMessage(policy=email.policy.default)
    _apply_base_headers(msg, "PDF bundle", "pdf-in-pdf")
    msg.set_content("See attached bundle PDF.")
    msg.add_attachment(outer_pdf, maintype="application", subtype="pdf", filename="bundle.pdf")
    truth = _truth_base("pdf_in_pdf", "PDF bundle")
    truth["attachment_count"] = 1
    truth["tree"] = [
        _tree_node(
            "attachment",
            "bundle.pdf",
            pdf_page_count(outer_pdf),
            [
                _tree_node("embedded", "exhibit.pdf", pdf_page_count(inner_pdf)),
            ],
        ),
    ]
    return _write_case(out_dir, "pdf_in_pdf", msg, truth)


def _build_contract_inner_email() -> EmailMessage:
    """Build an inner email with contract.pdf attached."""
    pdf_bytes = create_pdf(
        "Master Services Agreement",
        ["The fee is twenty five thousand dollars."],
        table=[["Milestone", "Fee"], ["Kickoff", "25000"]],
    )
    inner = EmailMessage(policy=email.policy.default)
    _apply_base_headers(inner, "Inner contract", "inner-contract")
    inner.set_content("Please see the attached contract.")
    inner.add_attachment(pdf_bytes, maintype="application", subtype="pdf", filename="contract.pdf")
    _fix_boundaries(inner, "inner-contract")
    return inner


def _case_forwarded_with_pdf(out_dir: Path) -> Path:
    """Forward (message/rfc822) of an inner email that carries contract.pdf."""
    inner = _build_contract_inner_email()
    msg = EmailMessage(policy=email.policy.default)
    _apply_base_headers(msg, "Fwd: contract", "forwarded-with-pdf")
    msg.set_content("Forwarding the contract email below.")
    msg.add_attachment(_message_bytes(inner, "inner-contract"), maintype="message", subtype="rfc822")
    truth = _truth_base("forwarded_with_pdf", "Fwd: contract")
    truth["attachment_count"] = 1
    truth["tree"] = [
        _tree_node(
            "forward",
            None,
            None,
            [_tree_node("attachment", "contract.pdf", 1)],
        ),
    ]
    return _write_case(out_dir, "forwarded_with_pdf", msg, truth)


def _case_html_cid_image(out_dir: Path) -> Path:
    """HTML body referencing a cid: inline PNG image."""
    msg = EmailMessage(policy=email.policy.default)
    _apply_base_headers(msg, "HTML with logo", "html-cid-image")
    msg.set_content("Plain text fallback for HTML with inline logo.")
    html = (
        "<html><body><p>Company logo:</p>"
        '<img src="cid:logo@example.com" alt="logo"></body></html>'
    )
    msg.add_alternative(html, subtype="html")
    html_part = msg.get_body(preferencelist=("html",))
    if html_part is not None:
        html_part.make_related()
        html_part.add_related(
            TINY_PNG,
            maintype="image",
            subtype="png",
            cid="logo@example.com",
            filename="logo.png",
            disposition="inline",
        )
    truth = _truth_base("html_cid_image", "HTML with logo")
    truth["inline_image_count"] = 1
    truth["prefer_html"] = True
    truth["cid_refs"] = ["logo@example.com"]
    return _write_case(out_dir, "html_cid_image", msg, truth)


def _case_rfc2047_subject(out_dir: Path) -> Path:
    """Non-ASCII subject and From display name encoded per RFC 2047."""
    msg = EmailMessage(policy=email.policy.default)
    msg["From"] = Address(display_name="José García", username="jose", domain="example.com")
    msg["To"] = DEFAULT_TO
    msg["Subject"] = "Réunion: contrat"
    msg["Date"] = FIXED_DATE
    msg["Message-ID"] = "<rfc2047-subject@fixtures.example>"
    msg.set_content("Bonjour, veuillez examiner le contrat.")
    truth = _truth_base("rfc2047_subject", "Réunion: contrat")
    truth["from_name"] = "José García"
    truth["from_addr"] = "jose@example.com"
    return _write_case(out_dir, "rfc2047_subject", msg, truth)


def _case_duplicate_filenames(out_dir: Path) -> Path:
    """Two attachments sharing the filename same.pdf but different content."""
    pdf_a = create_pdf("Document A", ["First version of same.pdf."])
    pdf_b = create_pdf("Document B", ["Second version of same.pdf."])
    msg = EmailMessage(policy=email.policy.default)
    _apply_base_headers(msg, "Duplicate filenames", "duplicate-filenames")
    msg.set_content("Two attachments with the same filename.")
    msg.add_attachment(pdf_a, maintype="application", subtype="pdf", filename="same.pdf")
    msg.add_attachment(pdf_b, maintype="application", subtype="pdf", filename="same.pdf")
    truth = _truth_base("duplicate_filenames", "Duplicate filenames")
    truth["attachment_count"] = 2
    truth["tree"] = [
        _tree_node("attachment", "same.pdf", pdf_page_count(pdf_a)),
        _tree_node("attachment", "same.pdf", pdf_page_count(pdf_b)),
    ]
    return _write_case(out_dir, "duplicate_filenames", msg, truth)


def _case_zero_byte_attachment(out_dir: Path) -> Path:
    """Attachment with zero bytes."""
    msg = EmailMessage(policy=email.policy.default)
    _apply_base_headers(msg, "Empty attachment", "zero-byte-attachment")
    msg.set_content("This email has an empty attachment.")
    msg.add_attachment(b"", maintype="application", subtype="pdf", filename="empty.pdf")
    truth = _truth_base("zero_byte_attachment", "Empty attachment")
    truth["attachment_count"] = 1
    truth["tree"] = [_tree_node("attachment", "empty.pdf", 0)]
    return _write_case(out_dir, "zero_byte_attachment", msg, truth)


def _case_corrupt_pdf(out_dir: Path) -> Path:
    """Attachment with invalid PDF bytes."""
    corrupt_bytes = b"%PDF-1.4\nnot a real pdf"
    msg = EmailMessage(policy=email.policy.default)
    _apply_base_headers(msg, "Corrupt PDF", "corrupt-pdf")
    msg.set_content("This email has a corrupt PDF attachment.")
    msg.add_attachment(corrupt_bytes, maintype="application", subtype="pdf", filename="bad.pdf")
    truth = _truth_base("corrupt_pdf", "Corrupt PDF")
    truth["attachment_count"] = 1
    truth["tree"] = [_tree_node("attachment", "bad.pdf", pdf_page_count(corrupt_bytes))]
    return _write_case(out_dir, "corrupt_pdf", msg, truth)


def _case_reply_thread(out_dir: Path) -> Path:
    """Reply body with new text and a quoted prior message block."""
    body = (
        "Please review the redlines.\n\n"
        "On 2026-03-01 Jane wrote:\n"
        "> Original question\n"
    )
    msg = EmailMessage(policy=email.policy.default)
    _apply_base_headers(msg, "Re: contract question", "reply-thread")
    msg.set_content(body)
    truth = _truth_base("reply_thread", "Re: contract question")
    truth["new_body_contains"] = "Please review the redlines."
    truth["quoted_contains"] = "Original question"
    return _write_case(out_dir, "reply_thread", msg, truth)


def _case_multipart_alternative(out_dir: Path) -> Path:
    """multipart/alternative with divergent plain and HTML bodies."""
    msg = EmailMessage(policy=email.policy.default)
    _apply_base_headers(msg, "Alternative bodies", "multipart-alternative")
    msg.set_content("PLAIN ONLY VERSION")
    msg.add_alternative("<p>HTML ONLY VERSION</p>", subtype="html")
    truth = _truth_base("multipart_alternative", "Alternative bodies")
    truth["prefer_html"] = True
    truth["alternative_html_contains"] = "HTML ONLY VERSION"
    return _write_case(out_dir, "multipart_alternative", msg, truth)


def _case_missing_date(out_dir: Path) -> Path:
    """Email deliberately missing the Date header."""
    msg = EmailMessage(policy=email.policy.default)
    _apply_base_headers(msg, "No date header", "missing-date", include_date=False)
    msg.set_content("This message has no Date header.")
    truth = _truth_base("missing_date", "No date header", has_date=False)
    return _write_case(out_dir, "missing_date", msg, truth)


def _case_empty_subject(out_dir: Path) -> Path:
    """Email with an empty Subject header."""
    msg = EmailMessage(policy=email.policy.default)
    _apply_base_headers(msg, "", "empty-subject")
    msg.set_content("This message has an empty subject.")
    truth = _truth_base("empty_subject", "")
    return _write_case(out_dir, "empty_subject", msg, truth)


def _case_nested_forward_pdf(out_dir: Path) -> Path:
    """Forward of a forward; innermost message contains a PDF attachment."""
    nested_pdf = create_pdf("Nested Agreement", ["Innermost forwarded PDF content."])
    innermost = EmailMessage(policy=email.policy.default)
    _apply_base_headers(innermost, "Innermost PDF", "nested-innermost")
    innermost.set_content("Innermost message with PDF.")
    innermost.add_attachment(
        nested_pdf,
        maintype="application",
        subtype="pdf",
        filename="nested.pdf",
    )

    middle = EmailMessage(policy=email.policy.default)
    _apply_base_headers(middle, "Middle forward", "nested-middle")
    middle.set_content("Middle forward wrapper.")
    _fix_boundaries(innermost, "nested-innermost")
    middle.add_attachment(_message_bytes(innermost, "nested-innermost"), maintype="message", subtype="rfc822")
    _fix_boundaries(middle, "nested-middle")

    outer = EmailMessage(policy=email.policy.default)
    _apply_base_headers(outer, "Outer forward", "nested-forward-pdf")
    outer.set_content("Outer forward wrapper.")
    outer.add_attachment(_message_bytes(middle, "nested-middle"), maintype="message", subtype="rfc822")

    truth = _truth_base("nested_forward_pdf", "Outer forward")
    truth["attachment_count"] = 1
    truth["tree"] = [
        _tree_node(
            "forward",
            None,
            None,
            [
                _tree_node(
                    "forward",
                    None,
                    None,
                    [_tree_node("attachment", "nested.pdf", pdf_page_count(nested_pdf))],
                ),
            ],
        ),
    ]
    return _write_case(out_dir, "nested_forward_pdf", msg=outer, truth=truth)


_CASE_BUILDERS = [
    _case_plain_no_attachment,
    _case_single_pdf,
    _case_five_pdfs,
    _case_pdf_in_pdf,
    _case_forwarded_with_pdf,
    _case_html_cid_image,
    _case_rfc2047_subject,
    _case_duplicate_filenames,
    _case_zero_byte_attachment,
    _case_corrupt_pdf,
    _case_reply_thread,
    _case_multipart_alternative,
    _case_missing_date,
    _case_empty_subject,
    _case_nested_forward_pdf,
]


def generate_all(out_dir: Path) -> list[Path]:
    """Generate every synthetic fixture case into out_dir and return .eml paths."""
    return [builder(out_dir) for builder in _CASE_BUILDERS]


def main() -> None:
    """Generate fixtures into tests/fixtures/synthetic/."""
    repo_root = Path(__file__).resolve().parents[2]
    out_dir = repo_root / "tests" / "fixtures" / "synthetic"
    paths = generate_all(out_dir)
    print(f"Generated {len(paths)} synthetic fixtures in {out_dir}")


if __name__ == "__main__":
    main()
