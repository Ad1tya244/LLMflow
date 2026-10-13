# LLMFlow Implementation Plan (HISTORICAL)

> **This is the original planning document from 2026-10-13 and is kept for context.** Several
> decisions below were later changed (Groq only, no admin portal, workspace accounts with BYOK keys,
> MFA). For the current state read [../README.md](../README.md), [SECURITY.md](SECURITY.md) and the
> decisions log in [../AGENT.md](../AGENT.md).

Status: **DRAFT 2026-10-13.** No code exists yet. Inputs: [providers.md](providers.md), [research/gateways.md](research/gateways.md). Rules: [../AGENT.md](../AGENT.md).

## 0. Senior-engineer review outcome (2026-10-13; supersedes conflicting text below)

The first draft was over-scoped and the provider list too thin. Changes:

| Finding | Change |
|---|---|
| Four bespoke provider adapters is waste: Groq, Gemini (`/v1beta/openai/`), Mistral, OpenRouter, NVIDIA NIM, SambaNova all expose OpenAI-style chat completions | **One generic `OpenAICompatibleProvider`, config-driven catalog.** The internal `Provider` protocol stays neutral, so a native adapter (Gemini/Cohere/Anthropic-style) can be added without touching the router. "OpenAI-compatible" is a wire format, not a vendor lock-in. |
| Thin quota: sum of free tiers is a few thousand req/day | Catalog expanded: **Groq, Gemini, NVIDIA NIM (~40 RPM, OpenAI-compatible, prototyping-grade, UNVERIFIED limits), Mistral, Cloudflare Workers AI, OpenRouter `:free`, SambaNova (20 RPD, last resort), Cohere trial (1K calls/month, non-commercial)**. All optional: a provider with no key is simply disabled. |
| Learned router (v2) and cascade are premature without data | **Deferred** until the benchmark harness has measured outcomes. Ship the heuristic router with a tier catalog whose quality estimates come from our own benchmark runs. |
| pgvector on Neon free unverified; Alembic + dual-dialect cost | SQLAlchemy 2 async, SQLite (dev/tests) and Postgres (prod). Semantic cache keeps a **bounded in-process vector index** hydrated from the DB; no pgvector dependency. Migrations: simple versioned SQL, no Alembic until schema churns. |
| Benchmark harness was phase 6; router tuning needs it first | **Harness moves before router tuning** (phase 5). |
| `uv` not installed | Plain `venv` + pip with `pyproject.toml` (zero extra tooling). |
| 512 MB Render instance | Minimal deps: fastapi, uvicorn, httpx, pydantic(-settings), sqlalchemy, aiosqlite/asyncpg, numpy only if needed. No ML frameworks. |
| Streaming | SSE passthrough; fallback only allowed **before the first byte** is sent. |

Revised phases: 1 scaffold+CI-ready gates → 2 provider layer + catalog + quota/cooldown → 3 OpenAI-compatible API + auth + usage store → 4 router v1 + fallback → 5 benchmark harness + first measured runs → 6 cache (exact + semantic) + budgets → 7 dashboard (design system first) → 8 deploy → 9 learned router if data supports it.

## 1. Honest feasibility summary

- **Feasible at ₹0:** an OpenAI-compatible gateway, routing, caching, fallback, tracking, dashboard, and deployment on Render + Neon + Cloudflare Pages.
- **Constraints that shape everything:** free LLM quotas are small and per-account (Groq ~1K RPD/200K TPD per model, OpenRouter free 50 RPD, Gemini limits only visible in AI Studio). Render sleeps after 15 min. Neon scales to zero.
- **"Cost saving" is shadow cost.** Real spend is ₹0. We report notional cost at published paid prices plus % of free quota used. Every figure is labeled `measured` or `simulated`.
- **Excluded for violating ₹0:** Cerebras (card needed), GitHub Models (retired), HF Docker Spaces (paid), Fly.io, Cloud Run.

## 2. Proposed stack

| Layer | Choice | Why |
|---|---|---|
| Language/API | Python 3.13, FastAPI, httpx (async), Pydantic v2 | Typed, async streaming, OpenAPI for free |
| Quality gates | ruff, mypy `--strict`, pytest, pytest-asyncio, respx, coverage | AGENT.md §2 |
| Packaging | `pyproject.toml`, `uv` or pip-tools (uv not installed: needs your OK to install, it's free) | Reproducible |
| DB | Neon Postgres via SQLAlchemy 2 async + Alembic | Free, relational analytics, optional pgvector |
| Cache | L1 in-process LRU (exact), L2 Postgres (exact persisted + semantic vectors) | No Redis needed; single instance |
| Embeddings | Cloudflare Workers AI `bge-small-en-v1.5` (primary), Gemini embedding (fallback) | Cloud-only, free, ~5M tokens/day |
| Dashboard | Vite + React + TypeScript, TanStack Query, uPlot/visx charts, Lucide icons, CSS variables design tokens | Static host, no cold start, light bundle |
| API host | Render free web service (Docker) | Verified 750 h/month, no card (to confirm at signup) |
| Dashboard host | Cloudflare Pages (or Vercel Hobby) | Free static hosting |
| CI | GitHub Actions free minutes | Lint, type-check, test on PR |

Decision records will go in `docs/adr/` and the summary log in AGENT.md §7 once you approve.

## 3. Architecture

```
Client (OpenAI SDK, base_url=LLMFlow)
  -> Auth (gateway API keys, hashed) -> Validation -> Budget guard
  -> Cache L1 exact -> L2 semantic (scoped)       [hit: return, log]
  -> Complexity analyser (features -> difficulty score + capabilities needed)
  -> Router: filter(health, quota, context, privacy, capability)
             -> choose cheapest tier whose expected quality >= threshold
             -> ordered fallback chain
  -> Executor: provider adapter, timeout, bounded retry w/ backoff + jitter,
               circuit breaker / cooldown, stream passthrough
  -> Usage recorder (tokens, latency, shadow cost, quota use, route reason)
  -> Response (OpenAI schema + x-llmflow-* headers)
```

Modules (`src/llmflow/`): `api/` (HTTP, schemas), `core/` (config, errors, logging), `providers/` (adapter protocol + Groq, Gemini, Cloudflare, OpenRouter), `routing/` (analyser, policy, fallback), `cache/`, `budget/`, `usage/`, `storage/` (models, repos), `bench/` (harness, shared with CLI).

Key behaviours:
- **Routing policy** is pure and deterministic given inputs, so it is unit-testable and explainable; each response records the *reason* for its route.
- **Quality dial:** `quality: low|balanced|high` (or numeric threshold) per request or key default. Request may also pin a model.
- **Quota awareness:** adapter reads provider rate-limit headers and keeps local RPM/RPD/TPD counters; router never picks an exhausted provider; 429 triggers cooldown honoring `retry-after`.
- **Budget:** per-key daily/monthly caps on shadow cost and on tokens; hard stop returns a structured 429/402-style error.
- **Cold-start tolerance:** `/healthz` fast path, DB connect retry, dashboard "waking service" state.
- **Secrets:** env vars only; gateway keys stored as SHA-256 + prefix; provider keys never logged; log redaction.
- **Privacy:** providers tagged `trains_on_data`; requests may set `privacy: strict` to exclude them.

## 4. Routing approach (the core differentiator)

1. **v1 — transparent heuristic scorer.** Features: prompt tokens, code/math presence, multi-step/reasoning cues, structured-output demand, conversation depth, requested max tokens. Output: difficulty ∈ [0,1] mapped to tiers (small / medium / large) using a configurable model catalog with per-tier expected quality.
2. **v2 — learned from our own measured outcomes.** Fit a tiny logistic/GBT model offline on benchmark results (which tier first achieved a passing score), ship coefficients as JSON. No runtime ML dependency, no local LLM.
3. **Optional cascade:** try the cheap tier, escalate on low-confidence/verifier failure; reported separately because it trades latency for cost.

Baselines in the benchmark: (A) always-strongest, (B) always-cheapest, (C) fixed mid-tier, (D) random, (E) LLMFlow routed (v1, v2, cascade).

## 5. Benchmark methodology

- **Datasets (open, small samples, seeded):** GSM8K (math, exact match), MMLU subset (multiple choice, exact match), HumanEval-style/MBPP subset (execute tests in sandboxed subprocess), a short-form QA/summary set (LLM-judge), plus synthetic duplicates/paraphrases for cache tests (with an adversarial near-miss set for false positives).
- **Metrics:** task accuracy (deterministic where possible), judge score (judge model ≠ candidate where feasible, biases documented), latency p50/p95, tokens, shadow cost, quota use, cache hit rate and false-positive rate, failure/fallback rate.
- **Budgeting:** harness tracks remaining quota, resumes across days, stores raw results in the repo (JSONL) so tables are reproducible without re-calling APIs.
- **Labeling:** every table states `MEASURED (n=…, date, models)` or `SIMULATED (assumptions)`. Simulated only for scale projections, never for quality.

## 6. Dashboard (to be designed with a research pass first, per AGENT.md §4)

Pages: Overview, Requests (searchable log + route reason), Models & Providers (health, quota gauges), Cache, Budgets & Keys, Benchmarks, Settings/Playground. Before any UI code: a short design-research note and `docs/design-system.md` (type scale, colour tokens light/dark, spacing, components, states) for your review.

## 7. Phases and exit criteria

| # | Phase | Exit criteria (verified, not claimed) |
|---|---|---|
| 0 | Research + plan (this) | You approve stack and plan |
| 1 | Repo scaffold, CI, config, logging, `/healthz`, ADRs | lint + mypy + tests green |
| 2 | Provider adapters + quota tracker (Groq, Gemini, Cloudflare, OpenRouter) | contract tests with mocked HTTP; 1 live smoke test per provider using your keys |
| 3 | OpenAI-compatible API, streaming, errors, auth, usage recording | OpenAI SDK works unmodified against it |
| 4 | Router v1 + fallback/cooldown/retry | unit tests for policy; fault-injection tests |
| 5 | Cache (exact + semantic) + budgets | hit/miss/scope tests; threshold backtest |
| 6 | Benchmark harness + first real runs | reproducible report with measured numbers |
| 7 | Router v2 (learned) + cascade, re-benchmark | measured improvement or documented null result |
| 8 | Dashboard (design system first) | accessibility + responsive review, real data |
| 9 | Deployment to Render/Neon/Pages, docs, runbook | live smoke test on free infra, no billing method attached |

Each phase ends with a diff summary and test results for your commit approval.

## 8. Risks

| Risk | Mitigation |
|---|---|
| Free quotas too small for statistically strong benchmarks | Small seeded samples, report confidence intervals, accumulate runs across days, state limits plainly |
| Provider changes/removes free tier (already happened with GitHub Models, Cerebras) | Config-driven catalog, adapter interface, ≥3 providers, tests don't hit live APIs |
| Gemini free tier trains on prompts | `privacy: strict` routing constraint, docs warning |
| Render sleep / Neon wake latency | Stateless design, retries, UI warm-up state, optional free external pinger |
| Semantic cache serves wrong answers | Conservative threshold, scoping, TTL, false-positive metric, opt-out per request |
| Routing quality can't be shown to beat baselines | Report honestly; cost-quality frontier plot shows where it does or doesn't |

## 9. Decisions needed from you

1. Approve the stack (Python/FastAPI + Neon + Render + React on Cloudflare Pages), or name alternatives.
2. Allow installing `uv` (free) for Python dependency management, or use plain `venv` + pip?
3. Accounts and keys (I cannot create accounts): Groq, Google AI Studio, Cloudflare (Workers AI), OpenRouter, Neon, Render, GitHub (for CI). Mistral optional. Are you comfortable with Gemini's free tier using prompts for training (only benchmark data would be sent)?
4. Repo layout: single monorepo with `backend/`, `dashboard/`, `docs/`, `benchmarks/`?
5. Dashboard dark/light preference and any brand constraints (name, colour)?
