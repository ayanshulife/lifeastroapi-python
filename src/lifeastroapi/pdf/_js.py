"""The JavaScript semantics the report templates rely on.

The templates in ``_templates/`` are generated from the Node SDK's TypeScript
(``scripts/generate_pdf.mjs``) and must give byte-identical HTML. These helpers
supply what differs between the two languages: ``undefined`` next to ``null``,
truthiness, number to string, ``toFixed``, ``Object.keys`` order, string lengths
in UTF-16 units, and the JavaScript meaning of ``\\s`` and ``$`` in patterns.
None of them looks at the process locale or time zone.
"""

from __future__ import annotations

import contextlib
import math
import re
from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Context, Decimal
from typing import Any, Callable, Final


class Undefined:
    """JavaScript's ``undefined``: a key that is absent. JSON ``null`` is ``None``."""

    __slots__ = ()

    def __bool__(self) -> bool:
        return False

    def __repr__(self) -> str:
        return "undefined"


UNDEF: Final = Undefined()

#: The characters of JavaScript's ``\s`` and ``String.prototype.trim``.
_SPACE = (
    "\t\n\v\f\r \u00a0\u1680"
    + "".join(chr(c) for c in range(0x2000, 0x200B))
    + "\u2028\u2029\u202f\u205f\u3000\ufeff"
)
_SPACE_CLASS = "".join(f"\\u{ord(c):04x}" for c in _SPACE)
_ASTRAL = re.compile("[\U00010000-\U0010ffff]")
_MAX_SAFE_INTEGER = 2**53

# -- types and truthiness ----------------------------------------------------


def truthy(v: Any) -> bool:
    if v is None or v is UNDEF:
        return False
    if isinstance(v, str):
        return len(v) > 0
    if isinstance(v, (int, float)):
        return not (v == 0 or v != v)
    return True  # every array and object, empty ones too


def defined(v: Any) -> bool:
    """False for ``null`` and ``undefined`` (what ``??`` tests)."""
    return v is not None and v is not UNDEF


def or_(a: Any, b: Any) -> Any:
    return a if truthy(a) else b


def nullish(a: Any, b: Any) -> Any:
    return b if a is None or a is UNDEF else a


def type_of(v: Any) -> str:
    if v is UNDEF:
        return "undefined"
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, str):
        return "string"
    if isinstance(v, (int, float)):
        return "number"
    return "function" if callable(v) else "object"


def is_array(v: Any) -> bool:
    return isinstance(v, (list, tuple))


def same(a: Any, b: Any) -> bool:
    """``a === b``."""
    if a is b:
        return not (isinstance(a, float) and a != a)
    kind = type_of(a)
    if kind != type_of(b) or kind not in ("string", "number", "boolean"):
        return False
    return bool(a == b)


# -- strings and numbers -----------------------------------------------------


def number_to_string(n: float) -> str:
    if n != n:
        return "NaN"
    if n in (math.inf, -math.inf):
        return "Infinity" if n > 0 else "-Infinity"
    if n == 0:
        return "0"
    if isinstance(n, int) and abs(n) <= _MAX_SAFE_INTEGER:
        return str(int(n))
    x = float(n)
    shortest = float.__repr__(x)
    if "e" not in shortest:
        if abs(x) < 1e21:
            return shortest[:-2] if shortest.endswith(".0") else shortest
        return shortest
    mantissa, exponent = shortest.split("e")
    power = int(exponent)
    if mantissa.endswith(".0"):
        mantissa = mantissa[:-2]
    if -7 < power < 21:  # JavaScript writes these without an exponent
        return format(Decimal(shortest), "f")
    return f"{mantissa}e{'+' if power > 0 else '-'}{abs(power)}"


def s(v: Any) -> str:
    """``String(v)``, which is also a template literal's ``${v}``."""
    if isinstance(v, str):
        return v
    if v is UNDEF:
        return "undefined"
    if v is None:
        return "null"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, (int, float)):
        return number_to_string(v)
    if isinstance(v, (list, tuple)):
        return join(v, ",")
    return "[object Object]"


_NUMBER = re.compile(r"[+-]?(?:Infinity|(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)", re.ASCII)


def to_number(v: Any) -> float:
    """``Number(v)``."""
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, float)):
        return v
    if v is None:
        return 0
    if isinstance(v, (list, tuple)):
        v = s(v)
    if isinstance(v, str):
        text = v.strip(_SPACE)
        if not text:
            return 0
        if _NUMBER.fullmatch(text):
            return float(text)
    return math.nan


def to_fixed(v: Any, digits: int) -> str:
    """``v.toFixed(digits)``: the exact binary value, rounded half up."""
    if type_of(v) != "number":
        raise TypeError(f"expected a number in the report JSON, got {s(v)[:60]!r}")
    x = float(v)
    if x != x or abs(x) >= 1e21:
        return number_to_string(x)
    # An explicit context, so the caller's decimal context cannot change the output.
    exact = Decimal(x).quantize(Decimal(1).scaleb(-digits), ROUND_HALF_UP, Context(prec=80))
    if x == 0:
        exact = exact.copy_abs()
    return format(exact, "f")


def add(a: Any, b: Any) -> Any:
    if isinstance(a, str) or isinstance(b, str):
        return s(a) + s(b)
    if isinstance(a, (list, tuple, dict)) or isinstance(b, (list, tuple, dict)):
        return s(a) + s(b)
    return to_number(a) + to_number(b)


def sub(a: Any, b: Any) -> float:
    return to_number(a) - to_number(b)


def mul(a: Any, b: Any) -> float:
    return to_number(a) * to_number(b)


def div(a: Any, b: Any) -> float:
    x, y = to_number(a), to_number(b)
    if y:
        return x / y
    return math.nan if not x or x != x else math.copysign(math.inf, x)


def mod(a: Any, b: Any) -> float:
    """``a % b``, which takes the sign of ``a``."""
    x, y = to_number(a), to_number(b)
    if not y or x != x or x in (math.inf, -math.inf):
        return math.nan
    if isinstance(x, int) and isinstance(y, int):
        rest = abs(x) % abs(y)
        return -rest if x < 0 else rest
    return math.fmod(x, y)


def neg(v: Any) -> float:
    return -to_number(v)


def _utf16(v: str) -> bytes:
    return v.encode("utf-16-be", "surrogatepass")


def lt(a: Any, b: Any) -> bool:
    if isinstance(a, str) and isinstance(b, str):
        return _utf16(a) < _utf16(b)
    return to_number(a) < to_number(b)


def le(a: Any, b: Any) -> bool:
    if isinstance(a, str) and isinstance(b, str):
        return _utf16(a) <= _utf16(b)
    return to_number(a) <= to_number(b)


def gt(a: Any, b: Any) -> bool:
    return lt(b, a)


def ge(a: Any, b: Any) -> bool:
    return le(b, a)


def cos(v: Any) -> float:
    return math.cos(to_number(v))


def sin(v: Any) -> float:
    return math.sin(to_number(v))


PI = math.pi


def round_(v: Any) -> float:
    """``Math.round``: halves go up, towards +infinity (Python's ``round`` takes them to even)."""
    x = to_number(v)
    if x != x or x in (math.inf, -math.inf):
        return x
    below = math.floor(x)
    # Not floor(x + 0.5): that sum itself rounds up for 0.49999999999999994.
    return below + 1 if x - below >= 0.5 else below


def floor(v: Any) -> float:
    x = to_number(v)
    return x if x != x or x in (math.inf, -math.inf) else math.floor(x)


def sqrt(v: Any) -> float:
    x = to_number(v)
    return math.nan if x < 0 else math.sqrt(x)


def pow_(a: Any, b: Any) -> float:
    """``Math.pow``: always a double, NaN instead of a complex number or an error."""
    try:
        return math.pow(to_number(a), to_number(b))
    except ValueError:
        return math.nan
    except OverflowError:
        return math.inf


def min_(*values: Any) -> float:
    """``Math.min``, which is NaN when any argument is."""
    numbers = [to_number(v) for v in values]
    return math.nan if any(n != n for n in numbers) else min(numbers)


def max_(*values: Any) -> float:
    """``Math.max``, which is NaN when any argument is."""
    numbers = [to_number(v) for v in values]
    return math.nan if any(n != n for n in numbers) else max(numbers)


def is_nan(v: Any) -> bool:
    """``Number.isNaN(v)``."""
    return isinstance(v, float) and v != v


# -- property access ---------------------------------------------------------


def length(v: Any) -> Any:
    if isinstance(v, str):
        return utf16_length(v)
    if isinstance(v, (list, tuple)):
        return len(v)
    return get(v, "length")


def get(obj: Any, key: Any) -> Any:
    """``obj[key]``, with UNDEF for a missing key."""
    if isinstance(obj, dict):
        return obj.get(key if isinstance(key, str) else s(key), UNDEF)
    if obj is None or obj is UNDEF:
        raise TypeError(
            f"cannot read {s(key)!r} of {s(obj)}: "
            "the report JSON does not have the shape this renderer expects"
        )
    if isinstance(obj, (str, list, tuple)):
        if key == "length":
            return length(obj)
        text = s(key)
        if text.isascii() and text.isdigit() and (text == "0" or text[0] != "0"):
            index = int(text)
            if isinstance(obj, str):
                return slice_(obj, index, index + 1) if index < utf16_length(obj) else UNDEF
            if index < len(obj):
                return obj[index]
        return UNDEF
    if isinstance(obj, Mapping):
        return obj.get(key if isinstance(key, str) else s(key), UNDEF)
    return UNDEF


_OBJECT_PROTOTYPE = frozenset(
    (
        "__defineGetter__",
        "__defineSetter__",
        "__lookupGetter__",
        "__lookupSetter__",
        "__proto__",
        "constructor",
        "hasOwnProperty",
        "isPrototypeOf",
        "propertyIsEnumerable",
        "toLocaleString",
        "toString",
        "valueOf",
    )
)


def in_object_prototype(key: Any) -> bool:
    """``key in Object.prototype``: a name every JavaScript object has."""
    return s(key) in _OBJECT_PROTOTYPE


def has_own(obj: Any, key: Any) -> bool:
    """``Object.prototype.hasOwnProperty.call(obj, key)``."""
    if isinstance(obj, Mapping):
        return (key if isinstance(key, str) else s(key)) in obj
    if isinstance(obj, (str, list, tuple)):
        return s(key) == "length" or get(obj, key) is not UNDEF
    return False


def get_optional(obj: Any, key: Any) -> Any:
    """``obj?.[key]``."""
    return UNDEF if obj is None or obj is UNDEF else get(obj, key)


def put(obj: dict[str, Any], key: Any, value: Any) -> Any:
    obj[s(key)] = value
    return value


def keys(obj: Any) -> list[str]:
    """``Object.keys``: integer-like keys first, ascending, then in insertion order."""
    if obj is None or obj is UNDEF:
        raise TypeError("cannot list the keys of null or undefined")
    if isinstance(obj, (str, list, tuple)):
        return [str(i) for i in range(len(obj))]
    if not isinstance(obj, Mapping):
        return []
    numbers: list[int] = []
    others: list[str] = []
    for key in obj:
        text = s(key)
        if (
            len(text) <= 10
            and text.isascii()
            and text.isdigit()
            and (text == "0" or text[0] != "0")
            and int(text) < 2**32 - 1
        ):
            numbers.append(int(text))
        else:
            others.append(text)
    return [str(n) for n in sorted(numbers)] + others


def values(obj: Any) -> list[Any]:
    return [get(obj, key) for key in keys(obj)]


def entries(obj: Any) -> list[list[Any]]:
    return [[key, get(obj, key)] for key in keys(obj)]


def unpack(v: Any, count: int) -> list[Any]:
    """The right-hand side of ``const [a, b] = v``."""
    items = list(iterate(v))[:count]
    return items + [UNDEF] * (count - len(items))


# -- arrays and maps ---------------------------------------------------------


class Map:
    """The part of JavaScript's ``Map`` the templates use."""

    def __init__(self, pairs: Iterable[Any] = ()) -> None:
        self._items: dict[Any, tuple[Any, Any]] = {}
        for pair in pairs:
            self.set(get(pair, 0), get(pair, 1))

    @staticmethod
    def _slot(key: Any) -> Any:
        # To Python True == 1 and every NaN differs; to JavaScript it is the other way round.
        if isinstance(key, bool):
            return ("boolean", key)
        if is_nan(key):
            return ("NaN",)
        if isinstance(key, (dict, list, tuple)):
            return ("object", id(key))
        return key

    def get(self, key: Any) -> Any:
        found = self._items.get(self._slot(key))
        return UNDEF if found is None else found[1]

    def set(self, key: Any, value: Any) -> None:
        self._items[self._slot(key)] = (key, value)

    def items(self) -> list[list[Any]]:
        return [[key, value] for key, value in self._items.values()]


def iterate(v: Any) -> Iterable[Any]:
    if isinstance(v, (list, tuple, str)):
        return v
    if isinstance(v, Map):
        return v.items()
    raise TypeError(f"expected an array in the report JSON, got {s(v)[:60]!r}")


def _array(v: Any) -> Any:
    if isinstance(v, (list, tuple)):
        return v
    raise TypeError(f"expected an array in the report JSON, got {s(v)[:60]!r}")


def map_(v: Any, fn: Callable[[Any], Any]) -> list[Any]:
    return [fn(item) for item in _array(v)]


def map_indexed(v: Any, fn: Callable[[Any, int], Any]) -> list[Any]:
    return [fn(item, i) for i, item in enumerate(_array(v))]


def filter_(v: Any, fn: Callable[[Any], Any]) -> list[Any]:
    return [item for item in _array(v) if truthy(fn(item))]


def find(v: Any, fn: Callable[[Any], Any]) -> Any:
    for item in _array(v):
        if truthy(fn(item)):
            return item
    return UNDEF


def some(v: Any, fn: Callable[[Any], Any]) -> bool:
    return any(truthy(fn(item)) for item in _array(v))


def some_indexed(v: Any, fn: Callable[[Any, int], Any]) -> bool:
    return any(truthy(fn(item, i)) for i, item in enumerate(_array(v)))


def for_each_indexed(v: Any, fn: Callable[[Any, int], Any]) -> None:
    for i, item in enumerate(_array(v)):
        fn(item, i)


def array_from(count: Any, fn: Callable[[Any, int], Any]) -> list[Any]:
    """``Array.from({ length: count }, fn)``."""
    return [fn(UNDEF, i) for i in range(int(count))]


def join(v: Any, separator: str) -> str:
    return separator.join(
        "" if item is None or item is UNDEF else (item if isinstance(item, str) else s(item))
        for item in _array(v)
    )


def includes(v: Any, item: Any) -> bool:
    if isinstance(v, str):
        return s(item) in v
    return any(same(x, item) or (is_nan(x) and is_nan(item)) for x in _array(v))


def index_of(v: Any, item: Any) -> int:
    if isinstance(v, str):
        at = v.find(s(item))
        return at if at <= 0 else utf16_length(v[:at])
    for i, x in enumerate(_array(v)):
        if same(x, item):
            return i
    return -1


# -- strings -----------------------------------------------------------------


def _string(v: Any) -> str:
    if isinstance(v, str):
        return v
    raise TypeError(f"expected a string in the report JSON, got {s(v)[:60]!r}")


def utf16_length(v: str) -> int:
    if v.isascii() or _ASTRAL.search(v) is None:
        return len(v)
    return len(_utf16(v)) // 2


def slice_(v: Any, start: Any, end: Any = UNDEF) -> Any:
    first = int(to_number(start))
    last = None if end is UNDEF else int(to_number(end))
    if not isinstance(v, str):
        return list(_array(v)[first:last])
    if v.isascii() or _ASTRAL.search(v) is None:
        return v[first:last]
    units = _utf16(v)
    pairs = [units[i : i + 2] for i in range(0, len(units), 2)][first:last]
    return b"".join(pairs).decode("utf-16-be", "surrogatepass")


def trim(v: Any) -> str:
    return _string(v).strip(_SPACE)


def lower(v: Any) -> str:
    return _string(v).lower()


def upper(v: Any) -> str:
    """``toUpperCase``: no locale, so Turkish hosts still get ``I`` from ``i``."""
    return _string(v).upper()


def ends_with(v: Any, suffix: str) -> bool:
    return _string(v).endswith(suffix)


def char_at(v: Any, index: int) -> str:
    return str(slice_(_string(v), index, index + 1))


def code_points(v: Any) -> list[str]:
    """``Array.from(v)`` of a string: code points, not UTF-16 units."""
    text = _string(v)
    if not text.isascii():
        text = _utf16(text).decode("utf-16-be", "surrogatepass")  # joins split surrogate pairs
    return list(text)


_HEX_PREFIX = re.compile(r"[+-]?[0-9a-fA-F]+")


def parse_hex(v: Any) -> float:
    """``parseInt(v, 16)``."""
    found = _HEX_PREFIX.match(s(v).strip(_SPACE))
    return int(found.group(0), 16) if found else math.nan


def starts_with(v: Any, prefix: str) -> bool:
    return _string(v).startswith(prefix)


def pad_start(v: Any, width: int, fill: str) -> str:
    text = _string(v)
    return fill * (width - utf16_length(text)) + text


def char_code_at(v: Any, index: int) -> float:
    units = _utf16(_string(v))[2 * index : 2 * index + 2]
    return int.from_bytes(units, "big") if units else math.nan


def to_hex(v: Any) -> str:
    return format(int(v), "x")


# -- regular expressions -----------------------------------------------------


class Regex:
    """A JavaScript pattern, already translated to Python syntax by the generator.

    ``re.ASCII`` gives JavaScript's ASCII ``\\d``, ``\\w``, ``\\b`` and case folding; the
    generator writes out ``.`` and ``$`` in full, and ``<WS>`` for the inside of ``\\s``.
    """

    __slots__ = ("count", "pattern")

    def __init__(self, source: str, *, ignore_case: bool = False, all_: bool = False) -> None:
        source = source.replace("<WS>", _SPACE_CLASS)
        self.pattern = re.compile(source, re.ASCII | (re.IGNORECASE if ignore_case else 0))
        self.count = 0 if all_ else 1


def _as_units(v: str) -> str:
    """JavaScript patterns match UTF-16 units, so an emoji is two characters to them."""
    units = _utf16(v)
    return "".join(chr(units[i] << 8 | units[i + 1]) for i in range(0, len(units), 2))


def _as_text(units: str) -> str:
    return _utf16(units).decode("utf-16-be", "surrogatepass")


def replace(v: Any, rx: Regex, replacement: str) -> str:
    text = _string(v)
    if text.isascii() or _ASTRAL.search(text) is None:
        return rx.pattern.sub(replacement, text, count=rx.count)
    return _as_text(rx.pattern.sub(replacement, _as_units(text), count=rx.count))


def replace_text(v: Any, old: str, new: str) -> str:
    """``v.replace("old", "new")``, which replaces the first one only."""
    return _string(v).replace(old, new, 1)


def replace_with(v: Any, rx: Regex, fn: Callable[..., Any], params: int) -> str:
    """``v.replace(rx, fn)``, for an ``fn`` that takes ``params`` parameters."""

    def substitute(match: re.Match[str]) -> str:
        args = _groups(match, split)
        return s(fn(*args[:params]))

    text = _string(v)
    split = not text.isascii() and _ASTRAL.search(text) is not None
    out = rx.pattern.sub(substitute, _as_units(text) if split else text, count=rx.count)
    return _as_text(out) if split else out


def _groups(match: re.Match[str], split: bool) -> list[Any]:
    found = [match.group(0), *match.groups()]
    return [UNDEF if g is None else _as_text(g) if split else g for g in found]


def split_text(v: Any, rx: Regex) -> list[str]:
    """``v.split(rx)``, for a pattern without groups."""
    return rx.pattern.split(_string(v))


def test(rx: Regex, v: Any) -> bool:
    text = s(v)
    if not text.isascii() and _ASTRAL.search(text) is not None:
        text = _as_units(text)
    return rx.pattern.search(text) is not None


def exec_(rx: Regex, v: Any) -> list[Any] | None:
    text = s(v)
    split = not text.isascii() and _ASTRAL.search(text) is not None
    match = rx.pattern.search(_as_units(text) if split else text)
    return None if match is None else _groups(match, split)


# -- dates -------------------------------------------------------------------

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_ISO_DATE = re.compile(
    r"(\d{4})-(\d\d)-(\d\d)"
    r"(?:[T ](\d\d):(\d\d)(?::(\d\d)(?:\.(\d+))?)?)?"
    r"(?:(Z)|([+-])(\d\d):?(\d\d))?",
    re.ASCII | re.IGNORECASE,
)


class Date:
    """``new Date(iso)`` for the ISO 8601 strings the API sends.

    A value without an offset is read as UTC, so the host's time zone never matters.
    """

    __slots__ = ("_at",)

    def __init__(self, iso: Any) -> None:
        self._at: datetime | None = None
        if isinstance(iso, (int, float)):  # a number is milliseconds since 1970
            with contextlib.suppress(ValueError, OverflowError):
                self._at = _EPOCH + timedelta(milliseconds=int(iso))
            return
        found = _ISO_DATE.fullmatch(s(iso))
        if found is None:
            return
        year, month, day, hour, minute, second, fraction, _z, sign, off_h, off_m = found.groups()
        clock = (int(hour or 0), int(minute or 0), int(second or 0))
        millis = int((fraction or "0")[:3].ljust(3, "0"))
        # JavaScript takes any day up to 31 (30 February is 2 March), and 24:00 as the next day.
        if not 1 <= int(day) <= 31 or clock[1] > 59 or clock[2] > 59:
            return
        if clock[0] > 23 and (clock != (24, 0, 0) or millis):
            return
        try:
            at = datetime(int(year), int(month), 1, tzinfo=timezone.utc) + timedelta(
                days=int(day) - 1,
                hours=clock[0],
                minutes=clock[1],
                seconds=clock[2],
                milliseconds=millis,
            )
            if sign:
                offset = timedelta(hours=int(off_h), minutes=int(off_m))
                at = at - offset if sign == "+" else at + offset
        except (ValueError, OverflowError):
            return
        self._at = at

    def _field(self, name: str) -> float:
        return math.nan if self._at is None else int(getattr(self._at, name))

    def get_time(self) -> float:
        return math.nan if self._at is None else int(self._at.timestamp() * 1000)

    def utc_year(self) -> float:
        return self._field("year")

    def utc_month(self) -> float:
        return self._field("month") - 1

    def utc_date(self) -> float:
        return self._field("day")

    def utc_hours(self) -> float:
        return self._field("hour")

    def utc_minutes(self) -> float:
        return self._field("minute")
