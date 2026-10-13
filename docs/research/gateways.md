# Existing Gateway Research

Researched 2026-10-13 from LiteLLM docs, OpenRouter docs, Portkey docs/blog, RouteLLM paper/blog, and the MeanCache paper. Secondary sources are flagged.

## What each project teaches

### LiteLLM (SDK + proxy)
- **Router** groups deployments under one `model_name`; per-request pipeline: pre-call filters (context window, region, session affinity) → routing strategy → cooldown tracking → retries → order/model fallbacks.
- Strategies: `simple-shuffle` (default, recommended in prod), `least-busy`, `latency-based`, `usage-based` (Redis; docs advise against it in prod due to latency), `cost-based`, custom.
- **Cooldowns**: deployment-level, default 3 allowed fails / 5 s; triggered by 429, >50% failure/min, 401/404/408.
- **Retries**: exponential backoff for rate-limit errors; provider SDK `max_retries` pinned to 0 so retries don't multiply (good detail to copy).
- **Lesson:** reliability machinery (cooldown, fallback chain, retry policy per error class) is mature and worth reproducing in small form. LiteLLM's strategies pick a *deployment*, not a model by *query difficulty*. That is the gap LLMFlow fills.
- **Weakness for us:** large surface area, Redis-dependent features, heavy to run on a 512 MB free instance. We should not depend on it as a library (keeps the dependency tree small and the routing logic ours), but it is the reference for behaviour.

### OpenRouter
- One OpenAI-compatible API, many models/providers. Provider sorting by `price | throughput | latency`, `order/only/ignore`, `allow_fallbacks`, performance thresholds (`preferred_max_latency`), `:floor` / `:nitro` suffix shortcuts.
- Providers with recent outages are deprioritised automatically.
- **Lesson:** expose routing intent through simple request-level preferences, not only static config. `:free` models are also the benchmark substrate for us, subject to 50 RPD.

### Portkey
- Config-driven gateway: fallbacks, load balancing, conditional routing, guardrails, caching.
- **Caching:** exact-match first, semantic only on miss; default similarity 0.95; model and generation parameters must match exactly; system prompt excluded from matching; recommends backtesting threshold and tracking false positives; warns that once false positives pass ~3-5% the embedding model, not the threshold, is the problem.
- **Lesson:** two-layer cache, scoped keys, measurable false-positive rate.

### RouteLLM (LMSYS)
- Learns, from preference data, whether a query needs the strong or weak model; reported >85% cost reduction on MT-Bench, 45% MMLU, 35% GSM8K at ~95% of GPT-4 quality (paper numbers: verify against the paper before quoting; secondary summaries differ). Routers: similarity-weighted ranking, matrix factorization (recommended), BERT classifier, causal LLM.
- **Lesson:** a *threshold-controlled* cost/quality dial is the right abstraction. Training such a router needs preference data and ML infra that don't fit the free tier directly. We'll start with a transparent feature-based scorer and a threshold dial, then optionally fit a tiny logistic model on our own measured outcomes.

### Semantic caching (GPTCache, MeanCache study, Portkey)
- Default similarity thresholds like GPTCache's 0.7 performed poorly in the MeanCache evaluation; best cutoffs depended on embedding model (0.78–0.83 in that study).
- Failure example (secondary source): "left arm hurts" vs "right arm hurts" can score ~0.91.
- **Lesson:** conservative threshold, cache scoping, TTL, and an explicit false-positive evaluation set in our benchmarks.

### Helicone (secondary sources only; not verified)
- Observability-first logging proxy. Lesson: structured per-request logs with tokens, latency, cost, cache status are the core of the dashboard.

## Where LLMFlow can be simpler and better

| Gap in existing tools | LLMFlow approach |
|---|---|
| Routing by deployment health/cost, not query difficulty | Difficulty-aware tiering with a user-visible quality/cost dial |
| Need Redis/Postgres/ops to run | Single stateless service + one Postgres; fits free tier |
| Cost shown as paid-plan dollars only | Shadow cost *and* free-quota consumption per provider |
| Benchmarks are marketing claims | Reproducible harness in-repo comparing routing vs fixed vs cheapest, measured vs simulated labeled |
| Caches hide false positives | Cache hit audit trail + false-positive rate in benchmark |

## Design decisions drawn from the research
1. OpenAI-compatible `/v1/chat/completions` as the primary API (minimal integration change: swap base URL and key).
2. Provider adapter interface with per-provider quota tracker and cooldown.
3. Routing = filter (capability, context, quota, health, privacy) → score (difficulty vs tier quality) → pick (cheapest tier meeting threshold) → fallback chain.
4. Retry only at the gateway, never inside provider clients.
5. Exact-match cache then semantic cache, scoped by model-family/params/tenant, with TTL and similarity threshold ≥ 0.9 until measured otherwise.
