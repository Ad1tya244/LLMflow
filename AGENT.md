# AGENT.md — LLMFlow Project Rules

Persistent source of truth for all development decisions. Read this file before starting any work. Update it whenever a new permanent rule or architectural constraint is established. If a requested change conflicts with a rule here, explain the conflict and ask for clarification instead of silently proceeding.

## 0. Project Summary

LLMFlow is a cloud-based, provider-agnostic LLM API gateway that cuts inference cost by routing each request to a suitable model based on task complexity, cost, latency and quality requirements. Features: unified API across providers, semantic response caching, token/cost tracking, budget enforcement, automatic provider fallback, and a web analytics dashboard. Integration into existing apps must need minimal code changes.

## 1. Mandatory Project Conditions

1. **₹0 budget.** Only genuinely free services, open-source tools and free-tier infrastructure. No paid APIs, subscriptions, hosting or dependencies. Nothing that requires a credit card that can auto-charge.
2. **Cloud-only inference.** Never download, host or execute LLMs locally. All inference goes through external cloud APIs with free-tier access. (Small embedding models for caching must also be cloud-hosted or a free hosted embedding API unless explicitly approved.)
3. **Free API usage.** Research and verify pricing, quotas and limits of each provider before integrating (record date and source in `docs/providers.md`). Handle rate limits, exhausted quotas and provider failures gracefully (retry with backoff, circuit breaking, fallback, clear errors).
4. **Research existing platforms** (LiteLLM, Portkey, OpenRouter, Helicone, RouteLLM, etc.) before implementation. Learn from architecture, routing, caching, observability, cost controls and DX. Do not copy implementations. Record findings and trade-offs in `docs/research/`.
5. **Best engineering practices.** Clean, modular, maintainable, secure, tested code; separation of concerns; strict typing; input validation; structured error handling; secrets only via environment/secret stores (never committed); consistent standards; no duplication, needless abstraction, or hacks.
6. **Testing and benchmarking.** Automated tests plus reproducible benchmarks comparing intelligent routing vs fixed-model vs cheapest-model on real cost, latency, quality, cache effectiveness and failure rate. Label every result clearly as **measured** or **simulated**.
7. **Free cloud deployment.** Design for free-tier limits: quotas, resource caps, sleeping instances/cold starts. Never incur charges.

## 2. Software Engineering Standards

- Prioritise clean architecture, modularity, maintainability, security, performance, scalability and testability.
- Research established solutions and proven patterns before implementing complex features; do not reinvent without reason.
- Test every change, review its impact on existing functionality, and update documentation when needed.
- Never take shortcuts that compromise quality. Production-minded, not demo-ready.
- Never claim a feature is complete without having tested it. Report failures and skipped steps honestly.
- Workflow: research → feasibility → stack selection → architecture/design → incremental implementation → verification of each major feature before moving on.
- Keep documentation, automated tests and code-quality checks (lint, type-check, format) running throughout.
- Dependencies: justify each one (license, maintenance, ₹0 cost, size). Prefer fewer.

## 3. Git and Commit Approval

- **NEVER create a Git commit without my explicit approval.**
- Allowed without asking: inspect history, create branches, modify files, run tests, review diffs.
- Before any commit: explain the changes, summarise test results, and show the proposed diff for approval.
- Do not commit, push, merge or publish without my explicit permission for that specific action. Approval for one commit does not carry over to the next.
- This rule remains in effect for the entire project.

## 4. Dashboard Design and User Experience

The dashboard must look like a professionally designed commercial product, not a typical AI-generated site. It should feel like a premium developer tool built by an experienced product design team; every visual and interaction decision must be intentional.

- Research and draw principles (not copy) from Apple, Linear, Stripe, Vercel and other high-quality SaaS: typography, spacing, hierarchy, navigation, layout, interaction, whitespace.
- Clean, modern, sophisticated, minimal visual language.
- Avoid: generic AI-site patterns, excessive gradients, glow effects, gratuitous glassmorphism, oversized rounded cards, repetitive dashboard layouts.
- Choose typography deliberately for the product's identity; prioritise readability and consistency.
- No emojis as icons. Use one consistent professional icon library or carefully designed SVGs.
- Build a coherent design system: typography, colour, spacing, components, borders, shadows, interaction states. Document it in `docs/design-system.md`.
- Prioritise information hierarchy, data readability, meaningful charts, responsive layout, accessibility (contrast, keyboard, focus, ARIA) and intuitive navigation.
- Every component needs a clear functional purpose; no decoration without value.
- Realistic data visualisation, and meaningful empty, loading, success and error states.
- Consistency across every page, component and interaction.

## 5. Research Before Implementation

Before designing or building major features, research relevant open-source projects, established gateways, technical docs and well-designed developer platforms. Document trade-offs, verify technical assumptions (especially free-tier quotas), and choose solutions that fit the ₹0 constraint.

## 6. Continuous Compliance

- Read this file before starting any development work and follow it throughout.
- Update it when permanent rules or architectural constraints are established.
- Do not silently ignore these instructions on later tasks.

## 7. Decisions Log

_Record permanent architectural decisions and constraints here as they are made (date, decision, rationale)._

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-10-13 | Project initialised; `AGENT.md` created. | Research phase comes first per §2 and §5. |
| 2026-10-13 | Stack: Python 3.13 + FastAPI + httpx + Pydantic v2 + SQLAlchemy 2 async (SQLite dev, Postgres/Neon prod); React/TS static dashboard; Render + Neon + Cloudflare Pages. User delegated stack approval to the agent. | See `docs/PLAN.md` §0. |
| 2026-10-13 | Providers are config-driven; one generic OpenAI-compatible adapter behind a neutral `Provider` protocol. Not limited to OpenAI; any provider with usable free quota. Excluded: Cerebras (card), GitHub Models (retired), HF Docker Spaces (paid). | `docs/providers.md` |
| 2026-10-13 | Real spend is ₹0; cost metrics are "shadow cost" (published paid price × tokens) plus quota consumption, always labelled measured/simulated. | Honest benchmarking (condition 6). |
| 2026-10-13 | Python tooling: `venv` + pip, `ruff`, `mypy --strict`, `pytest`. Backend in `backend/`. | Zero extra installs. |
| 2026-10-13 | Dashboard: Vite + React + TS static SPA, Geist Sans/Mono, lucide icons, hand-built SVG charts, design tokens in `docs/design-system.md`. Reads `/admin/*` endpoints with the gateway API key (sessionStorage). No demo data in UI code; synthetic data only via the dev seed script. | Static host, no cold start, AGENT.md §4. **(partly superseded 2026-10-14: no admin UI; workspace users sign in with email + password.)** |
| 2026-10-13 | Security baseline: separate client/admin key scopes (admin off by default), per-key rate limit + budgets, request size/shape limits, allow-listed upstream params, strict headers/CSP, no prompt storage. Any new endpoint must use `Principal`/`AdminPrincipal`; any new upstream-bound field must be added to `UPSTREAM_PARAMS` deliberately. Re-run bandit, pip-audit, npm audit before each release. | `docs/SECURITY.md` |
| 2026-10-13 | Dashboard never stores credentials in web storage: admin key -> HttpOnly cookie session + in-memory CSRF token (`/admin/session`). Dashboard calls only `/admin/*` (incl. `/admin/chat` for the playground). | `docs/SECURITY.md` **(partly superseded 2026-10-14: no admin UI; workspace users sign in with email + password.)** |
| 2026-10-13 | Ship Groq only. Gemini removed (project denied by Google); other providers removed until verified live. Provider-agnostic design retained (catalog-driven). | `docs/providers.md` |
| 2026-10-13 | Benchmarks are measured, deterministic-checked, resumable, and stored in `benchmarks/results/`; never present simulated numbers as measured. Catalog `quality:` priors must not be set from saturated suites. `qwen3.8-27b` disabled (`enabled: false`) as dominated. Deployment targets Render + Neon + Vercel (`render.yaml`, `docs/DEPLOY.md`); not yet exercised live. | `benchmarks/README.md` |
| 2026-10-14 | Multi-tenant BYOK: workspaces sign up (or are created by an admin), add their own provider keys (Fernet-encrypted with `LLMFLOW_MASTER_KEY`), and route only through them. Operator keys remain for the operator's own apps. Every new endpoint must declare its role (`ClientCaller` / `TenantPrincipal` / `AdminPrincipal`). | `docs/SECURITY.md` |
| 2026-10-14 | No admin web portal. Workspace users sign in with email+password (argon2id, lockout, recovery codes); apps use named revocable API keys that cannot manage the workspace; operators use `npm run ops` (Bearer admin key only). OpenAI catalog entries are unverified until someone with a key tests them. | `docs/SECURITY.md` |
| 2026-10-14 | TOTP MFA is optional per user; a correct password never issues a session when MFA is on. Next planned: email verification/reset, SSO, passkeys. Master key rotation via `npm run rotate-master-key`. | `docs/SECURITY.md` |
| 2026-10-14 | No model training or local model execution on the developer's machine (hard rule). Routing is evaluated by offline replay of measured outcomes; calibration is one-parameter counting. Documentation leads with measured positive results and claims only what is demonstrated: the router is described as rule-based with a quality dial, and is not described as learned/adaptive until a replay shows lift. Raw measurement files are never deleted or edited to change a verdict. | `benchmarks/README.md` |
| 2026-10-18 | Catalog models can be `auto_route: false` (selectable by name, never chosen by the router); `groq-qwen3.8-27b` ships that way because it benchmarked below both gpt-oss models at higher cost. Providers can set `stream_usage: false` when the API rejects `stream_options`. Gemini was added via its OpenAI-compatible endpoint and is UNVERIFIED until tested with a key. | `backend/config/catalog.d/gemini.yaml`, `backend/config/catalog.yaml` |
