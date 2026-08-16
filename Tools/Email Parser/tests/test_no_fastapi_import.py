"""Ensure email_parser core does not import FastAPI or web."""

import sys
from pathlib import Path


def _source_files_to_inspect() -> list[Path]:
    """Return source files for email_parser modules that exist at test time."""
    package_root = Path(__file__).resolve().parents[1] / "email_parser"
    relative_paths = [
        "__init__.py",
        "models.py",
        "config.py",
        "ids.py",
        "file_parsers/__init__.py",
        "file_parsers/base.py",
    ]
    return [package_root / rel for rel in relative_paths if (package_root / rel).is_file()]


def test_email_parser_does_not_import_fastapi() -> None:
    """Importing email_parser must not pull FastAPI into sys.modules."""
    sys.modules.pop("fastapi", None)
    for key in list(sys.modules):
        if key == "email_parser" or key.startswith("email_parser."):
            del sys.modules[key]

    import email_parser  # noqa: F401

    assert "fastapi" not in sys.modules, "email_parser import loaded fastapi"


def test_core_sources_do_not_reference_fastapi_or_web() -> None:
    """Core email_parser source files must not reference fastapi or web imports."""
    forbidden_tokens = ("fastapi", "from web")
    for path in _source_files_to_inspect():
        source = path.read_text(encoding="utf-8")
        for token in forbidden_tokens:
            assert token not in source, f"{path} contains forbidden token: {token!r}"
