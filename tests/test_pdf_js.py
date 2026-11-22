"""The JavaScript semantics of the generated templates (``lifeastroapi.pdf._js``)."""

from __future__ import annotations

import math

import pytest

from lifeastroapi.pdf import _js as js

from pdf_support import fixture


def test_number_formatting_matches_node() -> None:
    for row in fixture("numbers"):
        n = row["n"]
        assert js.s(n) == row["text"], n
        assert [js.to_fixed(n, digits) for digits in (0, 1, 2)] == row["fixed"], n
    assert js.s(1.0) == "1"
    assert js.s(-0.0) == "0"
    assert js.to_fixed(-0.0, 2) == "0.00"
    assert js.s(math.nan) == "NaN"
    assert js.s(-math.inf) == "-Infinity"


def test_rounding_matches_node() -> None:
    for row in fixture("numbers"):
        n = row["n"]
        rounded = [js.s(js.round_(n)), js.s(js.div(js.round_(js.mul(n, 10)), 10))]
        assert rounded == row["rounded"], n
    # Halves go up, not to even and not away from zero.
    assert [js.s(js.round_(n)) for n in (0.5, 1.5, 2.5, -0.5, -2.5)] == ["1", "2", "3", "0", "-2"]


def test_min_is_javascript() -> None:
    assert js.min_(3, 2) == 2
    assert js.is_nan(js.min_(3, js.UNDEF))


def test_only_the_first_text_match_is_replaced() -> None:
    assert js.replace_text("a-a-a", "a", "b") == "b-a-a"


def test_truthiness_is_javascript() -> None:
    for falsy in (None, js.UNDEF, False, 0, -0.0, math.nan, ""):
        assert not js.truthy(falsy), falsy
    values: list[object] = [[], {}, "0", " ", -1, True]
    for value in values:
        assert js.truthy(value), value
    assert js.or_(0, "x") == "x"
    assert js.nullish(0, "x") == 0
    assert js.nullish(js.UNDEF, "x") == "x"


def test_null_undefined_and_join() -> None:
    assert js.s(None) == "null"
    assert js.s(js.UNDEF) == "undefined"
    assert js.join(["a", None, js.UNDEF, 1.0], ",") == "a,,,1"
    assert js.s([1, True, [2.5]]) == "1,true,2.5"
    assert js.s({}) == "[object Object]"


def test_equality_keeps_types() -> None:
    assert js.same(1, 1.0)
    assert not js.same(True, 1)
    assert not js.same("1", 1)
    assert not js.same(math.nan, math.nan)
    assert not js.same([], [])
    found = js.Map([[1, "one"], [True, "yes"]])
    assert (found.get(1), found.get(True), found.get(1.0)) == ("one", "yes", "one")


def test_object_keys_order() -> None:
    assert js.keys({"b": 1, "10": 1, "2": 1, "01": 1, "a": 1}) == ["2", "10", "b", "01", "a"]


def test_strings_count_utf16_units() -> None:
    assert js.length("a\U0001f600b") == 4
    assert js.slice_("a\U0001f600b", 3) == "b"
    assert js.slice_("a\U0001f600b", 1, 3) == "\U0001f600"
    assert js.index_of("\U0001f600>", ">") == 2
    assert js.pad_start("7", 2, "0") == "07"


def test_whitespace_is_javascript() -> None:
    assert js.trim("\ufeff\u00a0 x\u2028") == "x"
    assert js.trim("\u0085x\u001f") == "\u0085x\u001f"
    space = js.Regex("[<WS>]")
    assert js.test(space, "\ufeff")
    assert not js.test(space, "\u0085")


@pytest.mark.parametrize(
    ("iso", "expected"),
    [
        ("2026-11-22T11:12:01.123456789+05:30", (2026, 10, 22, 5, 42)),
        ("2026-11-22T05:12:00", (2026, 10, 22, 5, 12)),
        ("2026-02-30", (2026, 2, 2, 0, 0)),
        ("0001-01-01T00:00:00Z", (1, 0, 1, 0, 0)),
        ("2026-11-22T24:00:00Z", (2026, 10, 23, 0, 0)),
    ],
)
def test_dates_read_as_utc(iso: str, expected: tuple[int, ...]) -> None:
    date = js.Date(iso)
    fields = (
        date.utc_year(),
        date.utc_month(),
        date.utc_date(),
        date.utc_hours(),
        date.utc_minutes(),
    )
    assert fields == expected


@pytest.mark.parametrize(
    "iso", ["", "soon", "2026-13-01", "2026-04-32", "2026-11-22T23:59:60Z", "2026-11-22T24:01:00Z"]
)
def test_unreadable_dates_are_nan(iso: str) -> None:
    assert js.is_nan(js.Date(iso).get_time())


def test_missing_data_is_a_clear_error() -> None:
    with pytest.raises(TypeError, match="cannot read 'sign' of null"):
        js.get(None, "sign")
    assert js.get_optional(None, "sign") is js.UNDEF
