"""Download a small subset of permissively licensed public email fixtures."""

from __future__ import annotations

import sys
import urllib.error
import urllib.request
from pathlib import Path

FIXTURES: list[tuple[str, str, str]] = [
    (
        "msg_01.txt",
        "https://raw.githubusercontent.com/python/cpython/main/Lib/test/test_email/data/msg_01.txt",
        "PSF License",
    ),
    (
        "msg_02.txt",
        "https://raw.githubusercontent.com/python/cpython/main/Lib/test/test_email/data/msg_02.txt",
        "PSF License",
    ),
    (
        "msg_03.txt",
        "https://raw.githubusercontent.com/python/cpython/main/Lib/test/test_email/data/msg_03.txt",
        "PSF License",
    ),
]

README_BODY = """# Public email fixtures

Small permissively licensed samples vendored for parser testing.

| File | Source | License |
|------|--------|---------|
{rows}
"""


def fetch_public_fixtures(out_dir: Path) -> list[Path]:
    """Download public fixtures into out_dir; return paths written."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    for filename, url, _license in FIXTURES:
        dest = out_dir / filename
        request = urllib.request.Request(url, headers={"User-Agent": "email-parser-fixture-fetch/1.0"})
        with urllib.request.urlopen(request, timeout=30) as response:
            dest.write_bytes(response.read())
        written.append(dest)

    rows = "\n".join(f"| `{name}` | {url} | {license_} |" for name, url, license_ in FIXTURES)
    readme_path = out_dir / "README.md"
    readme_path.write_text(README_BODY.format(rows=rows) + "\n", encoding="utf-8")
    written.append(readme_path)
    return written


def main() -> None:
    """Fetch public fixtures; warn and exit 0 if network is unavailable."""
    repo_root = Path(__file__).resolve().parents[1]
    out_dir = repo_root / "tests" / "fixtures" / "public"

    try:
        paths = fetch_public_fixtures(out_dir)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"WARNING: Could not fetch public fixtures: {exc}", file=sys.stderr)
        raise SystemExit(0) from exc

    print(f"Fetched {len(paths) - 1} public fixtures into {out_dir}")


if __name__ == "__main__":
    main()
