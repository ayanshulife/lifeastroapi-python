"""The version in the User-Agent must be the packaged version."""

from __future__ import annotations

import re
from pathlib import Path

from lifeastroapi import __version__


def test_version_matches_pyproject() -> None:
    text = (Path(__file__).parent.parent / "pyproject.toml").read_text()
    match = re.search(r'^version = "([^"]+)"', text, re.MULTILINE)
    assert match is not None
    assert __version__ == match.group(1)
