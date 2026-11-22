"""The version in the User-Agent must be the packaged version."""

from __future__ import annotations

import re
from pathlib import Path
from typing import get_args

from lifeastroapi import HouseSystem, __version__


def test_version_matches_pyproject() -> None:
    text = (Path(__file__).parent.parent / "pyproject.toml").read_text()
    match = re.search(r'^version = "([^"]+)"', text, re.MULTILINE)
    assert match is not None
    assert __version__ == match.group(1)


def test_house_system_keeps_every_value_of_the_last_published_version() -> None:
    values = set(get_args(HouseSystem))
    published_0_2_0 = {
        "whole-sign",
        "equal",
        "placidus",
        "koch",
        "porphyry",
        "campanus",
        "regiomontanus",
    }
    assert published_0_2_0 | {"whole_sign"} <= values
