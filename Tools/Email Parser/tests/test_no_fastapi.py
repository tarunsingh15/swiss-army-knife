"""Ensure email_parser core imports without FastAPI."""

import sys


def test_email_parser_imports_without_fastapi(monkeypatch) -> None:
    """Importing email_parser must not require or load FastAPI."""
    monkeypatch.setitem(sys.modules, "fastapi", None)
    for key in list(sys.modules):
        if key == "email_parser" or key.startswith("email_parser."):
            del sys.modules[key]
    import email_parser  # noqa: F401
