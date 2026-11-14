"""Live API sweep: calls EVERY SDK method once against a real API and lists each
one the API rejects. This checks that the manifest's paths and parameter names
match what the server accepts; unit tests with a mock transport cannot see
that. Port of the Node SDK's scripts/live-sweep.mjs.

    LIFEASTRO_API_KEY=dv_live_... python scripts/live_sweep.py --base-url http://127.0.0.1:8080

Spends credits: one request per endpoint. There is no default base URL, so a
sweep never reaches production by accident; pass it explicitly.

Options (environment variable in brackets):
    --base-url URL   API base URL [LIFEASTRO_API_URL]
    --skip LIST      comma-separated path prefixes to leave out [LIFEASTRO_LIVE_SKIP].
                     Default "/v1/reports/" (composed reports cost 500-8000 credits
                     each). Pass "" to include them.
    --only LIST      comma-separated substrings; only matching paths run [LIFEASTRO_LIVE_ONLY]
    --lang CODE      language sent to every method that takes `lang` [LIFEASTRO_LIVE_LANG]
    --dump DIR       write each response to DIR/<group.method>.json [LIFEASTRO_LIVE_DUMP]
    --delay SECONDS  pause between calls, default 0.45 (per-minute rate limit)
    --async          use AsyncLifeAstro instead of LifeAstro
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from lifeastroapi import AsyncLifeAstro, LifeAstro, LifeAstroError

from samples import build_kwargs, has_param, iter_entries, resolve_method


def _split(value: str | None) -> list[str]:
    return [s for s in (value or "").split(",") if s]


def parse_args() -> argparse.Namespace:
    env = os.environ
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--base-url", default=env.get("LIFEASTRO_API_URL"))
    parser.add_argument("--skip", default=env.get("LIFEASTRO_LIVE_SKIP", "/v1/reports/"))
    parser.add_argument("--only", default=env.get("LIFEASTRO_LIVE_ONLY", ""))
    parser.add_argument("--lang", default=env.get("LIFEASTRO_LIVE_LANG"))
    parser.add_argument("--dump", default=env.get("LIFEASTRO_LIVE_DUMP"))
    parser.add_argument("--delay", type=float, default=0.45)
    parser.add_argument("--async", dest="use_async", action="store_true")
    return parser.parse_args()


def _describe(err: Exception) -> str:
    if isinstance(err, LifeAstroError):
        return f"{err.status} {err.code} {err.message}"
    return f"{type(err).__name__}: {err}"


def main() -> int:
    args = parse_args()
    api_key = os.environ.get("LIFEASTRO_API_KEY")
    if not api_key:
        print("LIFEASTRO_API_KEY is required.", file=sys.stderr)
        return 2
    if not args.base_url:
        print("--base-url (or LIFEASTRO_API_URL) is required.", file=sys.stderr)
        return 2
    dump = Path(args.dump) if args.dump else None
    if dump:
        dump.mkdir(parents=True, exist_ok=True)

    plan: list[tuple[dict[str, Any], dict[str, Any]]] = []
    failures: list[str] = []
    for entry in iter_entries(_split(args.skip), _split(args.only)):
        kwargs, missing = build_kwargs(entry)
        if missing:
            failures.append(f"FAIL {entry['py']}  ({entry['path']})\n     no sample for {missing}")
            continue
        if args.lang and has_param(entry, "lang"):
            kwargs["lang"] = args.lang
        plan.append((entry, kwargs))

    def record(
        entry: dict[str, Any], kwargs: dict[str, Any], result: Any, err: Exception | None
    ) -> None:
        if err is not None:
            failures.append(
                f"FAIL {entry['py']}  ({entry['path']})\n     {_describe(err)}\n"
                f"     input={json.dumps(kwargs, ensure_ascii=False)}"
            )
        elif dump:
            out = dump / f"{entry['py']}.json"
            out.write_text(json.dumps(result, indent=2, ensure_ascii=False))

    # A retried failure is still a failure worth seeing: max_retries=0.
    if args.use_async:

        async def run_all() -> None:
            async with AsyncLifeAstro(
                api_key, base_url=args.base_url, timeout=90, max_retries=0
            ) as client:
                for entry, kwargs in plan:
                    fn = resolve_method(client, entry)
                    try:
                        assert fn is not None, "method not found on the client"
                        record(entry, kwargs, await fn(**kwargs), None)
                    except Exception as err:
                        record(entry, kwargs, None, err)
                    await asyncio.sleep(args.delay)

        asyncio.run(run_all())
    else:
        with LifeAstro(api_key, base_url=args.base_url, timeout=90, max_retries=0) as client:
            for entry, kwargs in plan:
                fn = resolve_method(client, entry)
                try:
                    assert fn is not None, "method not found on the client"
                    record(entry, kwargs, fn(**kwargs), None)
                except Exception as err:
                    record(entry, kwargs, None, err)
                time.sleep(args.delay)

    for line in failures:
        print(line)
    print(f"\nlive sweep: {len(plan)} endpoints called, {len(failures)} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
