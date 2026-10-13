"""Add an OpenAI-compatible provider to the gateway without editing YAML by hand.

    # 1. see which models a provider offers (uses the key from backend/.env or the environment)
    python -m llmflow.tools.add_provider list --base-url https://openrouter.ai/api/v1 --key-env OPENROUTER_API_KEY

    # 2. register the ones you want (writes config/catalog.d/<id>.yaml; never writes keys)
    python -m llmflow.tools.add_provider add --id openrouter \
        --base-url https://openrouter.ai/api/v1 --key-env OPENROUTER_API_KEY \
        --model meta-llama/llama-3.3-70b-instruct:free:large --trains-on-data

``--model`` is ``<provider model id>:<tier>`` or ``...:<tier>:<price_in>:<price_out>`` where tier
is small|medium|large and prices are USD per 1M tokens (shadow cost; 0 for free models).
Then put the key in backend/.env under the --key-env name. The API restarts and picks it up.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
import yaml
from dotenv import dotenv_values

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,40}$")
_ENV_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,60}$")
_QUALITY = {"small": 0.45, "medium": 0.65, "large": 0.8}
_LOCAL = {"localhost", "127.0.0.1", "::1"}


class ToolError(ValueError):
    pass


def validate_base_url(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ToolError("--base-url must be a full http(s) URL")
    if parts.scheme == "http" and parts.hostname not in _LOCAL:
        raise ToolError("use https for remote providers so API keys are encrypted in transit")
    if parts.username or parts.password:
        raise ToolError("do not embed credentials in --base-url")
    return url.rstrip("/")


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "model"


def parse_model(spec: str, provider_id: str) -> dict[str, Any]:
    """``upstream[:tier[:price_in:price_out]]`` where upstream may itself contain colons
    (e.g. ``vendor/model:free``): the tier is found by scanning from the right."""
    parts = spec.split(":")
    tail: list[str] = []
    while parts and (parts[-1] in _QUALITY or _is_number(parts[-1])) and len(tail) < 3:
        tail.insert(0, parts.pop())
    upstream = ":".join(parts)
    if not upstream or not tail or tail[0] not in _QUALITY:
        raise ToolError(
            f"--model {spec!r}: expected <model id>:<small|medium|large>[:<price_in>:<price_out>]"
        )
    tier = tail[0]
    prices = tail[1:]
    if len(prices) not in (0, 2):
        raise ToolError(f"--model {spec!r}: give both prices or neither")
    price_in, price_out = (float(prices[0]), float(prices[1])) if prices else (0.0, 0.0)
    if price_in < 0 or price_out < 0:
        raise ToolError("prices must be >= 0")
    return {
        "id": f"{provider_id}-{slug(upstream)}",
        "provider": provider_id,
        "upstream_model": upstream,
        "tier": tier,
        "quality": _QUALITY[tier],
        "context_window": 128000,
        "price_in": price_in,
        "price_out": price_out,
    }


def _is_number(text: str) -> bool:
    try:
        float(text)
    except ValueError:
        return False
    return True


def build_entry(
    provider_id: str, base_url: str, key_env: str, models: list[str], trains_on_data: bool
) -> dict[str, Any]:
    if not _ID_RE.match(provider_id):
        raise ToolError("--id must be lowercase letters, digits, - or _ (max 41 chars)")
    if not _ENV_RE.match(key_env):
        raise ToolError("--key-env must look like MY_PROVIDER_API_KEY")
    if not models:
        raise ToolError("give at least one --model")
    parsed = [parse_model(m, provider_id) for m in models]
    if len({m["id"] for m in parsed}) != len(parsed):
        raise ToolError("two --model values map to the same id")
    return {
        "providers": {
            provider_id: {
                "base_url": validate_base_url(base_url),
                "api_key_env": key_env,
                "trains_on_data": trains_on_data,
            }
        },
        "models": parsed,
    }


def write_entry(entry: dict[str, Any], catalog_dir: Path, *, force: bool = False) -> Path:
    (provider_id,) = entry["providers"]
    target = catalog_dir / "catalog.d" / f"{provider_id}.yaml"
    if target.exists() and not force:
        raise ToolError(f"{target} exists; pass --force to overwrite")
    target.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "# Added by `python -m llmflow.tools.add_provider`. Quality priors are placeholders:\n"
        "# run the benchmark (npm run bench) before trusting them. Set the key in backend/.env.\n"
    )
    target.write_text(header + yaml.safe_dump(entry, sort_keys=False), encoding="utf-8")
    return target


def list_models(base_url: str, key_env: str) -> list[str]:
    key = os.environ.get(key_env) or (dotenv_values(".env").get(key_env) or "")
    if not key.strip():
        raise ToolError(f"{key_env} is not set (environment or backend/.env)")
    try:
        r = httpx.get(
            f"{validate_base_url(base_url)}/models",
            headers={"Authorization": f"Bearer {key.strip()}"},
            timeout=20,
        )
    except httpx.HTTPError as exc:
        raise ToolError(f"request failed: {type(exc).__name__}") from exc
    if r.status_code != 200:
        raise ToolError(f"provider answered HTTP {r.status_code}; check the key and base URL")
    data = r.json().get("data", [])
    return sorted(str(m.get("id")) for m in data if isinstance(m, dict) and m.get("id"))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="add_provider", description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    ls = sub.add_parser("list", help="show the models a provider offers")
    ls.add_argument("--base-url", required=True)
    ls.add_argument("--key-env", required=True)
    add = sub.add_parser("add", help="register a provider and models")
    add.add_argument("--id", required=True)
    add.add_argument("--base-url", required=True)
    add.add_argument("--key-env", required=True)
    add.add_argument(
        "--model", action="append", default=[], help="<id>:<tier>[:<in>:<out>], repeatable"
    )
    add.add_argument("--trains-on-data", action="store_true", help="provider may train on prompts")
    add.add_argument("--force", action="store_true")
    add.add_argument("--config-dir", type=Path, default=Path("config"))
    args = p.parse_args(argv)
    try:
        if args.cmd == "list":
            for m in list_models(args.base_url, args.key_env):
                print(m)
            return 0
        entry = build_entry(args.id, args.base_url, args.key_env, args.model, args.trains_on_data)
        target = write_entry(entry, args.config_dir, force=args.force)
    except ToolError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"wrote {target}")
    print(f"next: put {args.key_env}=<key> in backend/.env (the API restarts automatically)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
