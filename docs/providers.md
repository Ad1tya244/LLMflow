# Free-Tier Provider Research

Researched 2026-10-13. Sources are the providers' own docs where reachable; anything marked **UNVERIFIED** came only from third-party aggregators and must be confirmed in the provider console during account setup. Free-tier terms change often: the gateway must read limits from config, never hard-code them in logic, and must react to live `429`/rate-limit headers.

## LLM inference providers

| Provider | Free tier (verified) | Card needed | Verdict |
|---|---|---|---|
| **Groq** | Per-org limits. Docs show Developer-plan base table: `gpt-oss-120b` / `gpt-oss-20b` / `qwen3.8-27b` = 30 RPM, 1K RPD, 8K TPM, 200K TPD. The docs page did not render the Free-plan tab; the account Limits page is authoritative. Cached tokens don't count. Returns `429` + `retry-after`; sends `x-ratelimit-remaining-*` headers. Older third-party tables listed `llama-3.1-8b-instant` (14.4K RPD) and `llama-3.3-70b` (1K RPD, 100K TPD): **UNVERIFIED**, models may have changed. | No (UNVERIFIED) | **Use.** Fastest latency; token/day cap is the binding limit. |
| **Google Gemini API** | Official pricing page marks a free tier for Flash / Flash-Lite lines, 2.5 Pro, `gemini-embedding-2`, Gemma 4. Exact RPM/RPD are not published in docs; they are shown only inside AI Studio per project. Limits are **per project, not per key**; RPD resets midnight Pacific. Third-party figures range from 20 to 1,500 RPD: **UNVERIFIED**. **Free-tier content is used to improve Google products** (privacy caveat). | No | **Use**, with the data-usage caveat documented. Also gives a free embedding model. |
| **OpenRouter** | `:free` model IDs: 20 RPM; 50 RPD if < $10 credits ever bought, 1,000 RPD otherwise (buying credits is out of scope, so assume **50 RPD**). Per account, all keys. `GET /api/v1/key` reports `free_model_daily_requests`. | No | **Use as last-resort fallback only**: 50 RPD is tiny, but the breadth of models is useful for benchmarks. |
| **Cloudflare Workers AI** | 10,000 Neurons/day free, reset 00:00 UTC. Catalog includes `llama-3.3-70b-instruct-fp8-fast`, `gpt-oss-20b/120b`, `llama-3.1-8b`, `qwen3-30b`, plus embeddings (`bge-small-en-v1.5` = 1,841 Neurons per 1M tokens, so roughly 5M embedding tokens/day). Over-limit requests fail with an error. | No (UNVERIFIED for Workers AI specifically) | **Use** for embeddings (semantic cache) and as an extra chat provider. |
| **Mistral La Plateforme** | Free "Experiment" tier exists, but limits aren't published in docs; ~1B tokens/month is a third-party claim. Third parties say phone verification and training-data opt-in are required. | **UNVERIFIED** | **Evaluate at signup**; include only if console shows limits and no card. |
| **Cerebras** | Official docs: Free Trial gives $5 credit **only after adding a verified payment method**; credits expire in 30 days; API is inactive without it. | **Yes** | **Excluded.** Violates ₹0 / no-card-risk rule. |
| **GitHub Models** | Docs state "fully retired" as of 2026-07-30. | n/a | **Excluded.** |
| **Hugging Face Inference / Spaces** | Docker Spaces now require a paid plan. | n/a | **Excluded** for hosting. |

### Consequences for design

1. **The free quotas are small and per-account.** A realistic aggregate across Groq + Gemini + Cloudflare is on the order of a few thousand requests/day. Benchmarks must therefore be small, carefully budgeted, cached, and resumable.
2. **Real spend is always ₹0, so "cost saving" must be defined carefully.** The gateway will track (a) *shadow cost*: tokens × a published paid price for that model, which is what the same traffic would cost on paid plans, and (b) *quota consumption*: fraction of each provider's free allowance used. Reports must label shadow cost as computed, not paid.
3. **Quota state is first-class.** Every provider adapter exposes remaining RPM/RPD/TPD (from response headers where available, local counters otherwise). The router filters by it.
4. **Privacy.** Gemini free tier trains on content; the dashboard/docs must tell users not to send sensitive data via free-tier providers. Provider data-use flags become routing constraints.
5. **Sign-up is manual.** API keys require creating accounts at each provider; I cannot create accounts or enter credentials. The user must obtain keys and store them as environment secrets.

## Infrastructure (free)

| Need | Choice | Verified limits | Risk / mitigation |
|---|---|---|---|
| API hosting | **Render free web service** | 750 instance-hours/month per workspace (one always-on service fits), spins down after 15 min idle, ~1 min cold start, no persistent disk, single instance, may restart anytime | Cold start: dashboard shows warm-up state; optional external pinger. **Stateless service; all state in DB.** |
| Database | **Neon Postgres free** | 1 GB/project, 100 CU-hours/month, scales to zero after 5 min (non-configurable), pgvector available (UNVERIFIED on free) | Cold DB wake adds latency; use connection retry. Avoid **Render free Postgres** (expires after 30 days). |
| Alt. database | Supabase free | 500 MB, pauses after 1 week idle, 2 active projects | Fallback option only. |
| Rate-limit counters / hot cache | **In-process + Postgres** (no Redis) | Upstash free = 500K commands/month, 250 MB | Single instance means in-process state is correct; persist snapshots to DB. Keep Upstash as optional. |
| Dashboard hosting | **Cloudflare Pages** or Vercel Hobby (static SPA) | Workers free: 100K req/day; static assets free | Static, no cold starts. |
| Edge option | Cloudflare Workers | 10 ms CPU/request, 50 subrequests, 128 MB | Too tight for Python gateway; not chosen. |
| Rejected | Fly.io (no free tier for new accounts), Cloud Run (billing account/card required), HF Spaces (paid), Koyeb (conflicting reports, unverified) | | |

## Open verification items (must be resolved at account setup, before relying on them)

- Actual Free-plan limits shown in Groq console and Google AI Studio.
- Whether Mistral and Cloudflare Workers AI require a card.
- Whether pgvector is enabled on Neon free.
- Render free-tier RAM/CPU for chosen instance type.

## Live verification log (2026-10-13)

- **Groq:** key accepted. Available chat models: `openai/gpt-oss-20b`, `openai/gpt-oss-120b`, `qwen/qwen3.8-27b` (plus `allam-2-7b`, safety/audio models). `llama-3.1-8b-instant` and `llama-3.3-70b-versatile` are **no longer offered**; catalog updated. Real requests, streaming (first chunk ~0.4 s), caching and fallback verified through the gateway.
- **Gemini:** key accepted by the model-list endpoint, but chat calls failed: 2.5 family -> 404 "no longer available to new users"; 3.x family -> 403 "project has been denied access". This is account/project level, not a code problem. Fix: create a key inside a new Google Cloud project (or check the project in AI Studio). The gateway handled it correctly: fell back to Groq and disabled the provider after the 403.
- **Decision (2026-10-13): Groq only.** Gemini was removed from the catalog because Google denied the project (HTTP 403) even with a key from a fresh account. NVIDIA NIM and OpenRouter were also removed to keep the configuration honest: only providers that are verified live are shipped. The provider layer is unchanged; adding one back is a catalog edit.
- **Groq limits seen in practice (2026-10-13):** besides RPM/TPM/RPD/TPD, `qwen/qwen3.8-27b` enforces an *output tokens per minute* limit (reported as 1000 on this org), and `openai/gpt-oss-20b` returned 429 at 30 RPM. The gateway reacts to 429s with a per-model cooldown honouring `retry-after`; the benchmark harness retries pinned requests, so such waits show up as latency, not failures.
