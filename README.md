# LLMFlow

**An OpenAI-compatible LLM gateway that routes each request to the cheapest model likely to answer
it well, using each user's own provider keys.**

Point any app that speaks the OpenAI API at LLMFlow, add your own Groq (or other OpenAI-compatible)
key once, and LLMFlow picks a model per request, falls back when a provider is rate-limited or down,
caches deterministic requests, enforces budgets, and shows you what it did and what it cost.

```
 your app  ──(LLMFlow API key)──▶  LLMFlow  ──(your provider key)──▶  Groq / OpenAI / ...
 (OpenAI SDK)                        │ picks the model per request
                                     │ fallback · cache · budgets · audit log
```

> Status: working and tested locally against Groq. Not yet deployed to hosted infrastructure; the
> deployment files are provided but unexercised. See [Limitations](#limitations).

## Features

- **Drop-in OpenAI API**: `POST /v1/chat/completions` (including streaming) and `GET /v1/models`.
  Change `base_url` and `api_key`; nothing else.
- **Per-request routing**: a transparent difficulty score picks the cheapest model that meets a
  quality bar; every response carries `x-llmflow-*` headers explaining the decision.
- **Bring your own keys**: each workspace adds its own provider keys, encrypted at rest, never shown
  again, used only for that workspace's requests.
- **Resilience**: per-model quota tracking, cooldowns that honour `Retry-After`, bounded fallback
  across models, streaming fallback before the first byte.
- **Cost controls**: exact-match response cache, per-workspace rate limits, daily token/cost budgets.
- **Observability**: usage, latency, tier mix and "shadow cost" (what the same tokens would cost at
  paid list prices), request log with routing reasons, per-workspace security audit log.
- **Security-first accounts**: email + password (argon2id), lockout, one-time recovery codes,
  optional TOTP two-factor, named and revocable API keys that cannot manage the workspace.
- **Reproducible benchmark**: routed vs. fixed-model strategies, measured on real calls
  ([results](benchmarks/README.md)).

## Quick start

Requirements: Node 20+ and Python 3.12+. No paid services are needed.

```bash
git clone <this repo> && cd llmflow
npm run dev
```

On first run this creates a virtualenv, installs dependencies, and generates local keys in
`backend/.env`. Then:

1. Open <http://localhost:5173> and choose **Create a workspace**.
2. Save the API key and recovery codes shown (once).
3. **Providers**: paste your own Groq key (get a free one at <https://console.groq.com>).
4. **Connect**: copy the snippet into your app, or try the **Playground**.

Prefer to see it work first? `npm run demo` starts everything and runs a scripted tour through the
official OpenAI SDK (set `GROQ_API_KEY` in `backend/.env` first).

## Using it from your code

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:8000/v1", api_key="<your LLMFlow API key>")

reply = client.chat.completions.create(
    model="auto",                                   # let LLMFlow choose, or pin a model id
    messages=[{"role": "user", "content": "Hello!"}],
    extra_body={"llmflow": {"quality": "balanced"}},  # optional: low | balanced | high
)
print(reply.choices[0].message.content)
```

Or with no code changes at all:

```bash
export OPENAI_BASE_URL=http://localhost:8000/v1
export OPENAI_API_KEY=<your LLMFlow API key>
```

Per-request options go in an `llmflow` object:

| Field | Values | Effect |
|---|---|---|
| `quality` | `low` / `balanced` / `high` | raises or lowers the model bar (and cost) |
| `privacy` | `standard` / `strict` | `strict` excludes providers flagged as training on prompts |
| `fallback` | `true` / `false` | `false` = fail rather than try another model |
| `cache` | `auto` / `on` / `off` | `auto` caches only `temperature: 0` requests |

> LLMFlow works with clients that let you set an API base URL (SDKs, LangChain, Open WebUI,
> LibreChat, Cursor-style tools). The ChatGPT website/app has no such setting and cannot be pointed
> at it.

## How routing works (and what it cannot do)

1. The request is scored from cheap, inspectable features (length, code, maths, reasoning cues,
   structured-output demands, conversation depth).
2. The score plus the `quality` setting give a required quality level.
3. Models of the providers you connected are filtered by context window, remaining quota, health,
   and privacy, then the cheapest one that meets the bar is chosen, with the rest as a fallback chain.

This is a heuristic, **not** an understanding of the request. In our benchmark it cut shadow cost by
roughly 40-45% versus always using the largest model with no measured accuracy loss, but the test
suites were easy enough that the smallest model also scored perfectly, so **escalation on genuinely
hard tasks is not yet demonstrated**. Details and caveats: [benchmarks/README.md](benchmarks/README.md).

## Security model

| Concern | Approach |
|---|---|
| People vs. apps | Humans use email + password sessions; apps use API keys. An API key cannot manage the workspace. |
| Provider keys | Verified on save, encrypted at rest (Fernet) under `LLMFLOW_MASTER_KEY`, bound to tenant and provider, never returned (last four only). |
| Passwords / keys | argon2id passwords; API keys and recovery codes stored only as hashes. |
| Sessions | HttpOnly cookie + per-session CSRF token; idle and absolute timeouts; revoked on password change. |
| Abuse | Per-IP and per-account throttling, request size/shape limits, parameter allow-list for upstream calls. |
| Visibility | Per-workspace audit log; no prompts or secrets are logged or stored. |

Full threat model, controls, residual risks and operator duties: [docs/SECURITY.md](docs/SECURITY.md).
**Back up `LLMFLOW_MASTER_KEY`**: without it, stored provider keys cannot be recovered.

Found a vulnerability? Please report it privately rather than opening a public issue.

## Configuration

All settings are environment variables (see [`backend/.env.example`](backend/.env.example)). The
essentials:

| Variable | Default | Purpose |
|---|---|---|
| `GROQ_API_KEY` | none | Operator provider key for your own apps (workspaces bring their own) |
| `LLMFLOW_API_KEYS` | none | Operator keys for `/v1/*` (comma separated, 16+ chars) |
| `LLMFLOW_ADMIN_API_KEYS` | none | Operator tooling only (`npm run ops`); must differ from the above |
| `LLMFLOW_MASTER_KEY` | none | Fernet key(s) encrypting workspace provider keys; empty disables workspaces |
| `LLMFLOW_SIGNUP_ENABLED` / `LLMFLOW_SIGNUP_CODE` | `false` / none | Self-service sign-up and optional invite code |
| `LLMFLOW_DATABASE_URL` | local SQLite | SQLite for dev, Postgres (e.g. Neon) for production |
| `LLMFLOW_CORS_ORIGINS` | `http://localhost:5173` | Exact dashboard origin(s) |
| `LLMFLOW_SESSION_COOKIE_SAMESITE` | `lax` | `none` (HTTPS only) when dashboard and API are on different sites |
| `LLMFLOW_TRUST_FORWARDED_FOR` | `false` | Set `true` behind exactly one trusted proxy |
| `LLMFLOW_RATE_LIMIT_RPM`, `LLMFLOW_DAILY_TOKEN_BUDGET`, `LLMFLOW_DAILY_BUDGET_USD` | 60 / unset / unset | Per-key limits |
| `LLMFLOW_CACHE_TTL_S` | `3600` | `0` disables the response cache |
| `LLMFLOW_ENABLE_DOCS` | `false` | Expose `/docs` and `/openapi.json` |

Models and providers live in [`backend/config/catalog.yaml`](backend/config/catalog.yaml) and
`backend/config/catalog.d/*.yaml`. Add a provider without editing YAML by hand:

```bash
npm run provider -- list --base-url https://openrouter.ai/api/v1 --key-env OPENROUTER_API_KEY
npm run provider -- add --id openrouter --base-url https://openrouter.ai/api/v1 \
    --key-env OPENROUTER_API_KEY --model "meta-llama/llama-3.3-70b-instruct:free:large"
```

## Commands

| Command | Purpose |
|---|---|
| `npm run dev` | Run API (:8000) and dashboard (:5173) with first-run setup and auto-reload |
| `npm run demo` | Scripted tour through the OpenAI SDK against the running gateway |
| `npm run smoke` | 10 live end-to-end checks |
| `npm test` | Backend (pytest) and dashboard (vitest) tests |
| `npm run check` | ruff, mypy `--strict`, TypeScript |
| `npm run bench` | Routing benchmark (real calls, paced to provider quotas, resumable) |
| `npm run ops -- workspaces\|disable\|enable\|delete <id>` | Operator tooling (Bearer admin key; no web portal) |
| `npm run provider` | List or add providers |
| `npm run rotate-master-key` | Re-encrypt stored provider keys under a new master key |
| `npm run build` | Production build of the dashboard |

## Project layout

```
backend/      FastAPI gateway (api, providers, routing, security, storage, tools, bench)
dashboard/    React + TypeScript SPA for workspace users
benchmarks/   Benchmark suites and measured results
docs/         Security model, deployment, testing guide, design system, research notes
examples/     OpenAI SDK quickstart
scripts/      Dev runner, demo, operator CLI
render.yaml   Render blueprint (API); dashboard targets any static host
AGENT.md      Project rules and decisions log
```

## Deployment

Free-tier-friendly target: Render (API) + Neon (Postgres) + Cloudflare Pages (dashboard). Steps and
a checklist are in [docs/DEPLOY.md](docs/DEPLOY.md). It has not been exercised on live
infrastructure yet; the repository includes CI (`.github/workflows/ci.yml`) that runs lint, type
checks, tests, `bandit`, `pip-audit` and `npm audit`.

## Limitations

- **One provider verified live** (Groq). OpenAI catalog entries are included but untested; check model
  ids and prices on your account.
- **Routing quality is a heuristic.** Benchmarks show cost savings; they do not yet show correct
  escalation on hard tasks. Catalog `quality` values are placeholders, not measurements.
- **Single instance.** Rate limits, cooldowns, cache and sessions are process-local.
- **No email verification, SSO or team roles yet.** Account recovery uses one-time codes.
- **Hosted trust model.** Prompts and decrypted provider keys pass through the server's memory.
- **Free tiers change.** Provider quotas in the catalog are configured values; confirm them in each
  provider's console.

## Documentation

[Security](docs/SECURITY.md) · [Testing guide](docs/TESTING.md) · [Deployment](docs/DEPLOY.md) ·
[Providers research](docs/providers.md) · [Benchmarks](benchmarks/README.md) ·
[Design system](docs/design-system.md) · [Project rules](AGENT.md)

## License

No license has been chosen yet. Until one is added, all rights are reserved by the author.
