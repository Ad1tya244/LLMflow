# Benchmarks

Measured results of routing strategies on Groq's free tier, produced by `npm run bench`
(`backend/src/llmflow/bench`). Raw per-item rows are in `results/*.jsonl`, summaries in
`results/*.report.md|json`, and the dashboard's **Benchmarks** page renders them.

## What was run (2026-10-13)

| Run | Suite | Items | Strategies |
|---|---|---|---|
| `groq-20261013` | `core44` (math, multiple choice, facts, JSON extraction, formatting constraints; easy/medium/hard) | 44 | always-large, always-cheapest, always-medium, routed-balanced, routed-high |
| `groq-20261013-hard21` | `hard21` (multi-step math/combinatorics, tricky formatting) | 21 | same |

Every request went through the real gateway stack (router, quota tracker, fallback, usage log)
with real Groq calls, `temperature=0`, cache off. Scoring is deterministic (numeric/letter/JSON/regex
checks); there is **no LLM judge**. All results are **measured**; nothing here is simulated.

## What the data shows

1. **Routing cut shadow cost by about 41-45% against always-large at no measured accuracy loss**
   (routed-balanced: 100% on both suites, same as always-large).
2. **`gpt-oss-20b` was already perfect on both suites** (65/65), so routed-balanced and
   always-cheapest are indistinguishable here: the router sent everything to the small model, which
   was the right call on this data. The suites are too easy to show a case where the cheap model fails
   and the router correctly escalates. That claim is **not** established by this benchmark.
3. **`qwen3.8-27b` is dominated.** Lower accuracy than both gpt-oss models (95% / 95%), higher
   shadow cost (+11% and +33% vs gpt-oss-120b, partly because it spends more tokens), and slower
   p50. It is disabled in `catalog.yaml` (`enabled: false`) with this reason; re-enable to re-test.
4. **`routed-high` cost more than always-large** (+8% / +10%) because it used the medium model for
   about half of the requests. With qwen disabled that no longer happens.

## Limits you should keep in mind

- n=44 and n=21: 95% intervals are about 8-15 points wide on the low end. Treat differences under 15
  points as noise.
- Single provider, single day, free-tier latency. Latency includes quota waiting and Groq queueing.
- Shadow cost uses list prices from `catalog.yaml`; qwen's price is an approximation (none published),
  which affects conclusion 3's magnitude but not the accuracy and latency evidence.
- One checker bug was found and fixed after the first run (`fact-06` rejected "Newton (N)"); the
  affected verdict was re-scored from stored responses and is flagged in the report notes. Re-scoring
  skips truncated responses so it can never judge a partial answer.
- The suite was written by the project author, not drawn from a public benchmark, and models may have
  seen similar problems in training.

## To make routing's value measurable

Add items where a 20B model plausibly fails: long-context retrieval, obscure factual recall,
multi-constraint instructions, and 5+ step proofs. Use `--suite path.jsonl` (same JSONL schema as
`suite/core44.jsonl`). Then use the by-difficulty accuracies to set the catalog `quality:` priors.
Do not copy the current 100% values into the priors: a saturated suite would make the router
always pick the cheapest model.
