"""Live end-to-end smoke test against a running gateway (real provider calls, a few cents of
free-tier quota). Usage:

    PYTHONPATH=src .venv/bin/python scripts/smoke_test.py [--base-url URL] [--key KEY]

Defaults: http://localhost:8000 and the first key in backend/.env (LLMFLOW_API_KEYS).
Exit code is non-zero if any check fails.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Callable
from typing import Any

import httpx
from dotenv import dotenv_values

Check = Callable[[httpx.Client, dict[str, str]], str]
BASE = "http://localhost:8000"


def chat(c: httpx.Client, h: dict[str, str], **body: Any) -> httpx.Response:
    payload = {"model": "auto", "max_tokens": 400,
               "messages": [{"role": "user", "content": "What is the capital of France? One word."}]}  # fmt: skip
    return c.post("/v1/chat/completions", headers=h, json={**payload, **body})


def expect(cond: bool, msg: str) -> str:
    if not cond:
        raise AssertionError(msg)
    return msg


def t_health(c: httpx.Client, h: dict[str, str]) -> str:
    r = c.get("/healthz")
    return expect(r.status_code == 200 and r.json() == {"status": "ok"}, f"healthz {r.status_code}")


def t_auth(c: httpx.Client, h: dict[str, str]) -> str:
    r = c.post("/v1/chat/completions", json={"messages": [{"role": "user", "content": "x"}]})
    r2 = c.post("/v1/chat/completions", headers={"Authorization": "Bearer wrong-key-0000000000"},
                json={"messages": [{"role": "user", "content": "x"}]})  # fmt: skip
    return expect(
        (r.status_code, r2.status_code) == (401, 401),
        f"no key {r.status_code}, bad key {r2.status_code}",
    )


def t_models(c: httpx.Client, h: dict[str, str]) -> str:
    ids = [m["id"] for m in c.get("/v1/models", headers=h).json()["data"]]
    return expect("auto" in ids and len(ids) > 1, f"models: {ids}")


def t_easy(c: httpx.Client, h: dict[str, str]) -> str:
    r = chat(c, h)
    ok = r.status_code == 200 and "paris" in r.text.lower()
    return expect(ok, f"easy -> {r.headers.get('x-llmflow-model')} ({r.status_code})")


def t_quality(c: httpx.Client, h: dict[str, str]) -> str:
    hard = ("Analyze and compare optimistic vs pessimistic locking step by step, "
            "then debug:\n```python\ndef f(x): return x/0\n```")  # fmt: skip
    r = chat(c, h, max_tokens=1200, llmflow={"quality": "high"},
             messages=[{"role": "user", "content": hard}])  # fmt: skip
    return expect(
        r.status_code == 200, f"hard+high -> {r.headers.get('x-llmflow-model')} ({r.status_code})"
    )


def t_cache(c: httpx.Client, h: dict[str, str]) -> str:
    body = {
        "temperature": 0,
        "messages": [{"role": "user", "content": f"Say OK. nonce {time.time()}"}],
    }
    a, b = chat(c, h, **body), chat(c, h, **body)
    return expect(
        a.headers.get("x-llmflow-cache") == "miss" and b.headers.get("x-llmflow-cache") == "hit",
        f"cache {a.headers.get('x-llmflow-cache')} -> {b.headers.get('x-llmflow-cache')}",
    )


def t_stream(c: httpx.Client, h: dict[str, str]) -> str:
    chunks = 0
    with c.stream("POST", "/v1/chat/completions", headers=h,
                  json={"model": "auto", "stream": True, "max_tokens": 300,
                        "messages": [{"role": "user", "content": "Count from 1 to 5."}]}) as r:  # fmt: skip
        for line in r.iter_lines():
            chunks += line.startswith("data:")
        status = r.status_code
    return expect(status == 200 and chunks > 2, f"stream {status}, {chunks} chunks")


def t_validation(c: httpx.Client, h: dict[str, str]) -> str:
    r = c.post("/v1/chat/completions", headers=h, json={"messages": "SECRETTEXT"})
    return expect(
        r.status_code == 422 and "SECRETTEXT" not in r.text, f"validation {r.status_code}, no echo"
    )


def t_unknown_model(c: httpx.Client, h: dict[str, str]) -> str:
    r = chat(c, h, model="does-not-exist")
    return expect(r.status_code == 404, f"unknown model {r.status_code}")


def t_headers(c: httpx.Client, h: dict[str, str]) -> str:
    r = c.get("/v1/models", headers=h)
    need = {"x-content-type-options", "x-frame-options", "cache-control", "x-request-id"}
    return expect(need <= set(r.headers), f"security headers present: {sorted(need)}")


CHECKS: list[tuple[str, Check]] = [
    ("health", t_health), ("rejects missing/bad key", t_auth), ("model list", t_models),
    ("easy prompt routes and answers", t_easy), ("hard prompt, quality=high", t_quality),
    ("response cache miss then hit", t_cache), ("streaming", t_stream),
    ("validation does not echo input", t_validation), ("unknown model is 404", t_unknown_model),
    ("security headers", t_headers),
]  # fmt: skip


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--base-url", default=BASE)
    p.add_argument("--key", help="client API key (default: first LLMFLOW_API_KEYS in .env)")
    args = p.parse_args()
    key = args.key or (dotenv_values(".env").get("LLMFLOW_API_KEYS") or "").split(",")[0].strip()
    if not key:
        print("no API key: pass --key or set LLMFLOW_API_KEYS in backend/.env")
        return 2
    failed = 0
    with httpx.Client(base_url=args.base_url, timeout=90) as c:
        h = {"Authorization": f"Bearer {key}"}
        for name, fn in CHECKS:
            try:
                print(f"PASS  {name:<34} {fn(c, h)}")
            except Exception as exc:
                failed += 1
                print(f"FAIL  {name:<34} {type(exc).__name__}: {exc}")
    print(f"\n{len(CHECKS) - failed}/{len(CHECKS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
