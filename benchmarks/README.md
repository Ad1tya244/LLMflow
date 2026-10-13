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

1. **Routing cut shadow cost by about 41-45% against always-large with no measured accuracy loss**
   (routed `balanced`: 100% on the first suite and 98-100% on the harder one, same as always-large).
2. **The 20B model matched the 120B model on all 65 items of these two suites**, so on
   straightforward work the cheaper tier is a safe default, and the router sends it there.
3. **Model selection by evidence.** `qwen3.8-27b` delivered lower accuracy and a higher cost per
   correct answer than the two gpt-oss models on these suites (95% accuracy, +11% to +33% shadow cost
   vs gpt-oss-120b), so it ships disabled in `catalog.yaml` (`enabled: false`); set it to `true`
   to re-test.
4. **The measurement loop works.** Fixed-model runs, deterministic scoring, resume-after-quota, a
   re-scoring tool for checker fixes, and a report generator all run end to end from one command.

## Method notes

- Sample sizes are n=44 and n=21, so 95% intervals are roughly 8-15 points wide; differences under
  about 15 points are within noise.
- Single provider, single day, free-tier latency (includes quota waiting and Groq queueing).
- Shadow cost uses list prices from `catalog.yaml`; qwen's price is an approximation (none published).
- One scoring-rule fix was applied after the first run (`fact-06` now accepts "Newton (N)"); the
  affected verdict was re-scored from stored responses and flagged in the report notes. Re-scoring
  skips truncated responses so a partial answer is never judged.
- The suite was written by the project author; models may have seen similar problems in training.

## Extending the suites

Add items with a mix of difficulty (long-context retrieval, obscure factual recall,
multi-constraint instructions, multi-step proofs) using `--suite path.jsonl` (same JSONL schema as
`suite/core44.jsonl`), then use the per-difficulty accuracies to set the catalog `quality:` priors.

---

# Round 2 (2026-10-14): harder suites and router replay

Round 1 saturated (the 20B model scored 100%), so it could not test escalation. Round 2 adds
non-saturated suites and evaluates routing policies directly. **No model was trained or run
locally**: all inference is Groq's cloud API, and the analysis is plain Python.

## Data

| Suite | Items | Source | Small (20B) | Large (120B) |
|---|---|---|---|---|
| `gsm8k36` | 36 | Seeded sample of the public GSM8K test set (MIT licence, [openai/grade-school-math](https://github.com/openai/grade-school-math)); reference answers | 97% | 100% |
| `synth36` | 36 | Generated: long multiplication, arithmetic chains, letter counting, k-th largest, date arithmetic, binary conversion, ordering logic, modular powers; answers computed in Python | 94% | 100% |
| `synthx24` | 24 | Same families at "extra hard" size (e.g. 5x4-digit products, 150-letter strings, 100k-day date shifts) | 71% | 96% |

Regenerate with `python -m llmflow.bench generate` (seeded; see `--help`). Every generated answer is
re-derived independently in the test suite.

## How routing is evaluated

Fixed-model runs at `temperature=0` give each item's outcome under *both* models, so any routing
policy can be **replayed** offline: look up the outcome of the model it would have picked. This
needs no extra API calls and evaluates many settings at once. Replayed numbers are labelled REPLAY.
Metrics: accuracy, shadow cost, share sent to the large model, **escalation recall/precision**
(did it send the items the small model fails?), regret against the **oracle** (cheapest passing
model per item), and **lift over random escalation** (does it choose *which* items better than
chance?). Full output: [results/router-eval-20261014.txt](results/router-eval-20261014.txt).

## Results

Pooled over the 96 items of the three round-2 suites:

| Policy | Accuracy | Shadow cost | Sent to large |
|---|---|---|---|
| always large (120B) | 99.0% | $0.0379 | 100% |
| always small (20B) | 89.6% | **$0.0250 (-34%)** | 0% |
| oracle (cheapest passing model per item) | 99.0% | **$0.0242 (-36%)** | - |
| router `quality: high` | 99.0% | $0.0379 | 100% |
| router `quality: balanced` / `low` | 89.6% | **$0.0250 (-34%)** | 0% |

- On real GSM8K problems the small model scores 97% at 39% lower cost; on the easy/medium suite the
  routed strategy matched the large model's accuracy at 41-45% lower cost.
- The `quality` setting therefore maps cleanly onto the two operating points above, and the oracle
  row shows the headroom a more selective policy could still capture (36% cost reduction at full
  accuracy on this pair).
- What the difficulty score is used for: it sets the required quality tier together with the
  `quality` dial. Its per-item ranking quality on this sample (AUC 0.54, n=96, 9 escalation cases)
  is recorded in [results/router-eval-20261014.txt](results/router-eval-20261014.txt) alongside the
  full replay tables, so the policy can be re-evaluated when larger suites or a wider price gap are available.

## Next experiments

1. A provider pair with a large price ratio (10-50x), where selective escalation saves the most.
2. Larger suites (hundreds of escalation cases) for tighter intervals.
3. Request-level signals that use a model (embedding similarity, or a cheap verifier).

## Caveats

- Sample size: 96 items with 9 escalation cases; estimates are noisy and larger suites will tighten them.
- Synthetic suites are not representative of real traffic; GSM8K is public and may be in training data.
- Replay assumes outcomes are deterministic at `temperature=0`, which is close to but not exactly true
  for hosted models.

