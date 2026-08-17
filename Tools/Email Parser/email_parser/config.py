"""Runtime settings loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env_int(name: str, default: int) -> int:
    """Read an integer environment variable, falling back to default."""
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return int(raw)


def _env_str(name: str, default: str) -> str:
    """Read a string environment variable, falling back to default."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw


def _env_bool(name: str, default: bool) -> bool:
    """Read a boolean environment variable, falling back to default."""
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    """Process-wide parser settings."""

    output_dir: Path
    pdf_engine: str
    max_depth: int
    max_fanout: int
    display_path_prefix: str
    token_budget: int
    ocr_enabled: bool
    ocr_dpi: int
    ocr_min_chars: int


def load_settings() -> Settings:
    """Load settings from EMAILPARSE_* environment variables."""
    output = _env_str("EMAILPARSE_OUTPUT_DIR", "output")
    return Settings(
        output_dir=Path(output).expanduser().resolve(),
        pdf_engine=_env_str("EMAILPARSE_PDF_ENGINE", "pdf_pymupdf"),
        max_depth=_env_int("EMAILPARSE_MAX_DEPTH", 10),
        max_fanout=_env_int("EMAILPARSE_MAX_FANOUT", 200),
        display_path_prefix=_env_str("EMAILPARSE_DISPLAY_PATH_PREFIX", ""),
        token_budget=_env_int("EMAILPARSE_TOKEN_BUDGET", 6000),
        ocr_enabled=_env_bool("EMAILPARSE_OCR_ENABLED", True),
        ocr_dpi=_env_int("EMAILPARSE_OCR_DPI", 200),
        ocr_min_chars=_env_int("EMAILPARSE_OCR_MIN_CHARS", 20),
    )
