"""Every generated method, checked against the manifest and against the
website's verified examples (tests/fixtures/examples.json): each method is
called once through a mock transport and must send every parameter the API
marks as required for that endpoint."""

from __future__ import annotations

import asyncio
import inspect
import json
import re
from pathlib import Path
from typing import Any

import pytest

from lifeastroapi.resources import AsyncResources, Resources

from conftest import Recorder, make_async_client, make_client
from samples import build_kwargs, has_param, load_manifest, resolve_method

MANIFEST = load_manifest()
EXAMPLES: dict[str, Any] = json.loads(
    (Path(__file__).parent / "fixtures" / "examples.json").read_text()
)
#: Same number of methods as the Node SDK 0.8.0 (and the Dart SDK).
NODE_METHOD_COUNT = 322

#: Params the examples list as required that the SDK leaves out on purpose.
NOT_REALLY_REQUIRED = {
    # The handler reads `tz` only together with `date` (the transit moment);
    # like the Node SDK, transit.sade_sati sends the natal chart only.
    "/v1/transit/sade-sati": {"tz"},
}


def _norm(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "{}", path)


EXAMPLES_BY_TEMPLATE = {_norm(k): v for k, v in EXAMPLES.items()}


def _public_methods(group: object) -> list[str]:
    names = []
    for name, value in inspect.getmembers(type(group)):
        if name.startswith("_"):
            continue
        if inspect.isfunction(value):
            names.append(name)
    return names


def _count(resources: object) -> int:
    total = 0
    for attr in vars(resources):
        if attr.startswith("_"):
            continue
        group = getattr(resources, attr)
        total += len(_public_methods(group))
        for sub in vars(group):
            if not sub.startswith("_"):
                total += len(_public_methods(getattr(group, sub)))
    return total


def test_one_method_per_manifest_entry() -> None:
    assert len(MANIFEST) == NODE_METHOD_COUNT
    assert len({e["key"] for e in MANIFEST}) == len(MANIFEST)
    assert len({e["py"] for e in MANIFEST}) == len(MANIFEST)
    sync = make_client(Recorder())
    asyn = make_async_client(Recorder())
    for entry in MANIFEST:
        fn = resolve_method(sync, entry)
        afn = resolve_method(asyn, entry)
        assert fn is not None, entry["py"]
        assert afn is not None and inspect.iscoroutinefunction(afn), entry["py"]


def test_resource_groups_hold_exactly_the_manifest_methods() -> None:
    sync = Resources(make_client(Recorder()))
    asyn = AsyncResources(make_async_client(Recorder()))
    assert _count(sync) == NODE_METHOD_COUNT
    assert _count(asyn) == NODE_METHOD_COUNT


def test_sync_and_async_signatures_match() -> None:
    sync = make_client(Recorder())
    asyn = make_async_client(Recorder())
    for entry in MANIFEST:
        fn, afn = resolve_method(sync, entry), resolve_method(asyn, entry)
        assert fn is not None and afn is not None
        assert list(inspect.signature(fn).parameters) == list(inspect.signature(afn).parameters)


def test_every_method_has_a_docstring_with_its_cost_and_path() -> None:
    client = make_client(Recorder())
    for entry in MANIFEST:
        doc = inspect.getdoc(resolve_method(client, entry)) or ""
        assert f"``GET {entry['path']}``" in doc, entry["py"]
        assert entry["cost"] is not None, entry["path"]
        assert f"Cost: {entry['cost']} credit" in doc, entry["py"]


def test_english_only_products_and_data_endpoints_take_no_lang() -> None:
    english_only = ("/v1/western/", "/v1/tarot/", "/v1/geo/", "/v1/meta/")
    for entry in MANIFEST:
        if entry["path"].startswith(english_only) and not entry["path"].startswith(
            "/v1/western/narrative/"
        ):
            assert not has_param(entry, "lang"), entry["key"]
    for key in [
        "panchang.rahuKaal",
        "panchang.sunriseSunset",
        "chart.yogas",
        "chart.doshas",
        "transit.windows",
        "milan.overlay",
    ]:
        entry = next(e for e in MANIFEST if e["key"] == key)
        assert not has_param(entry, "lang"), key


def test_every_vedic_lang_is_sent_as_lang_and_typed_locale() -> None:
    for entry in MANIFEST:
        for p in entry["params"]:
            if p["name"] == "lang":
                assert "lang" in p["wires"], entry["key"]
                assert p["type"] == "Locale", entry["key"]


def test_only_the_no_lang_list_of_vedic_methods_lacks_lang() -> None:
    english_only = ("/v1/western/", "/v1/tarot/", "/v1/geo/", "/v1/meta/")
    vedic = [e for e in MANIFEST if not e["path"].startswith(english_only)]
    without = [e["key"] for e in vedic if not has_param(e, "lang")]
    # manifest.mjs NO_LANG: 25 Vedic endpoints that return only times, numbers or ids.
    assert len(without) == 25, without
    assert len(vedic) - len(without) == 189


def _example_for(path: str) -> dict[str, Any] | None:
    found: dict[str, Any] | None = EXAMPLES.get(path) or EXAMPLES_BY_TEMPLATE.get(_norm(path))
    if found is None:  # a literal path of a template, e.g. /v1/chart/divisional/D9
        for template, example in EXAMPLES.items():
            pattern = "^" + "[^/]+".join(map(re.escape, re.split(r"\{[^}]+\}", template))) + "$"
            if "{" in template and re.match(pattern, path):
                return dict(example)
    return found


@pytest.mark.parametrize("entry", MANIFEST, ids=[e["key"] for e in MANIFEST])
def test_sends_the_required_params(entry: dict[str, Any]) -> None:
    kwargs, missing = build_kwargs(entry)
    assert not missing, f"no sample value for {missing}"
    rec = Recorder()
    fn = resolve_method(make_client(rec), entry)
    assert fn is not None
    fn(**kwargs)
    url = rec.last.url
    template = "^" + "[^/]+".join(map(re.escape, re.split(r"\{[^}]+\}", entry["path"]))) + "$"
    assert re.match(template, url.path), url.path

    example = _example_for(entry["path"])
    if example is None:
        return
    sent = set(url.params.keys())
    skip = NOT_REALLY_REQUIRED.get(entry["path"], set())
    for name in example["required"]:
        if "{" + name + "}" in entry["path"] or name in skip:
            continue
        assert name in sent, f"{entry['py']} ({entry['path']}) must send {name!r}; sent {sent}"


def test_async_client_sends_the_same_query_for_every_method() -> None:
    sync_rec, async_rec = Recorder(), Recorder()
    sync = make_client(sync_rec)
    asyn = make_async_client(async_rec)

    async def call_all() -> None:
        for entry in MANIFEST:
            kwargs, _ = build_kwargs(entry)
            afn = resolve_method(asyn, entry)
            assert afn is not None
            await afn(**kwargs)

    for entry in MANIFEST:
        kwargs, _ = build_kwargs(entry)
        fn = resolve_method(sync, entry)
        assert fn is not None
        fn(**kwargs)
    asyncio.run(call_all())
    assert len(sync_rec.requests) == len(async_rec.requests) == NODE_METHOD_COUNT
    for a, b in zip(sync_rec.requests, async_rec.requests):
        if "date" in a.url.params and a.url.params["date"] != b.url.params.get("date"):
            continue  # a "today" default can roll over at midnight between the two runs
        assert str(a.url) == str(b.url)


def test_lang_reaches_the_wire_for_every_vedic_method() -> None:
    rec = Recorder()
    client = make_client(rec)
    for entry in MANIFEST:
        if not has_param(entry, "lang") or entry["path"].startswith("/v1/western/"):
            continue
        kwargs, _ = build_kwargs(entry)
        fn = resolve_method(client, entry)
        assert fn is not None
        fn(**kwargs, lang="bn")
        assert rec.params()["lang"] == "bn", entry["py"]
