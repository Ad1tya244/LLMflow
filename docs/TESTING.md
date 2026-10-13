# Manual testing guide

Everything below runs against your local stack. Start it once and leave it running:

```bash
npm run dev          # API :8000, dashboard :5173 (auto signed in)
```

### Create an account

1. Open http://localhost:5173 and choose **Create a workspace**.
2. Save the **API key** and **recovery codes** shown once, then continue.
3. **Providers**: paste your own Groq key (verified live, then stored encrypted).
4. Use the API key from step 2 in your app (Connect page has snippets).

Operator keys in `backend/.env` (`LLMFLOW_API_KEYS`) still work for your own apps and the examples
below; `LLMFLOW_ADMIN_API_KEYS` is only for `npm run ops`.

Shell shortcut for the examples below:

```bash
export LLMFLOW_KEY=$(grep ^LLMFLOW_API_KEYS backend/.env | cut -d= -f2 | cut -d, -f1)
```

## 1. Fastest check: the built-in smoke test

```bash
npm run smoke
```

Runs 10 live checks (auth, routing, quality dial, cache, streaming, validation, headers) and exits non-zero on any failure.

## 2. Plain curl

```bash
# routed ("auto" lets the gateway pick a model)
curl -s http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer $LLMFLOW_KEY" -H "Content-Type: application/json" \
  -d '{"model":"auto","messages":[{"role":"user","content":"Capital of Japan?"}]}'

# see HOW it was routed: response headers
curl -si http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer $LLMFLOW_KEY" -H "Content-Type: application/json" \
  -d '{"model":"auto","messages":[{"role":"user","content":"hi"}]}' | grep -i x-llmflow
```

Headers: `x-llmflow-model`, `x-llmflow-provider`, `x-llmflow-attempts`, `x-llmflow-route-reason`, `x-llmflow-shadow-cost-usd`, `x-llmflow-cache`.

## 3. Use it from the OpenAI SDK (the real integration)

LLMFlow is OpenAI-compatible, so an existing app only changes `base_url` and `api_key`.

```python
# pip install openai
from openai import OpenAI

client = OpenAI(base_url="http://localhost:8000/v1", api_key="<LLMFLOW_API_KEYS value>")

r = client.chat.completions.create(
    model="auto",                                   # or a catalog id, e.g. "groq-gpt-oss-120b"
    messages=[{"role": "user", "content": "Explain TCP slow start in 2 sentences."}],
    max_tokens=400,
    extra_body={"llmflow": {"quality": "high"}},    # optional per-request routing controls
)
print(r.choices[0].message.content)
```

Streaming works unchanged (`stream=True`). Node:

```js
import OpenAI from "openai";
const client = new OpenAI({ baseURL: "http://localhost:8000/v1", apiKey: process.env.LLMFLOW_KEY });
const r = await client.chat.completions.create({ model: "auto", messages: [{ role: "user", content: "hi" }] });
```

Anything that speaks the OpenAI API (LangChain `ChatOpenAI`, LlamaIndex, Cursor-style tools, `curl`) works the same way.

### Per-request options (`llmflow` object)

| Field | Values | Effect |
|---|---|---|
| `quality` | `low` / `balanced` / `high` | raises or lowers the model bar (and cost) |
| `privacy` | `standard` / `strict` | `strict` excludes providers flagged `trains_on_data` |
| `fallback` | `true` / `false` | `false` = fail instead of trying another model |
| `cache` | `auto` / `on` / `off` | `auto` caches only `temperature: 0` requests |

## 4. Connecting providers

**Groq (already configured):** key in `backend/.env` as `GROQ_API_KEY`; edit and save, the API restarts itself.

**Any OpenAI-compatible provider** (OpenRouter, Together, Mistral, OpenAI, a local server, ...):

```bash
# what does it offer? (needs the key in backend/.env or the environment)
npm run provider -- list --base-url https://api.together.xyz/v1 --key-env TOGETHER_API_KEY

# register models; tier is small|medium|large; optional prices are USD per 1M tokens (shadow cost)
npm run provider -- add --id together --base-url https://api.together.xyz/v1 \
    --key-env TOGETHER_API_KEY --model "meta-llama/Llama-3.3-70B-Instruct-Turbo:large:0.88:0.88"
```

This writes `backend/config/catalog.d/together.yaml` (never a key). Put `TOGETHER_API_KEY=...` in
`backend/.env`; the Providers page then shows it as Ready. Quality priors start as placeholders
(small 0.45, medium 0.65, large 0.8): run `npm run bench` before trusting routing across providers.

Note: OpenAI has **no free API tier**, so adding it breaks this project's ₹0 rule. Providers with a
non-OpenAI wire format (Anthropic native, Gemini native) would need a small adapter implementing
`llmflow.providers.base.Provider`; the router does not change.

## 5. Scenarios to try by hand

| Scenario | How | Expect |
|---|---|---|
| Routing by difficulty | Send "capital of France?" then a long code-debugging prompt with `quality: high` | small model, then large model; `x-llmflow-route-reason` explains it |
| Cache | Send the same request twice with `"temperature": 0` | second has `x-llmflow-cache: hit`, attempts 0, cost 0 |
| Streaming | `"stream": true` with curl `-N` | `data:` chunks arrive incrementally |
| Fallback | Pin a model, then make it fail: set `GROQ_API_KEY=bad` in `.env` and send a request | `503 all_providers_failed`; Providers page shows "Auth failed" |
| Rate limit | `LLMFLOW_RATE_LIMIT_RPM=3` in `.env`, send 4 quick requests | 4th is `429` with `Retry-After` |
| Budget | `LLMFLOW_DAILY_TOKEN_BUDGET=500` in `.env`, send a few requests | `429 budget_exceeded` |
| Oversize / abuse | send a 600 kB body; `max_tokens: 99999`; `n: 3` | `413` / `422` / `422` |
| Key separation | `curl -H "Authorization: Bearer <workspace API key>" localhost:8000/account` | `403` (API keys cannot manage a workspace) |
| Operator surface | `curl -H "Authorization: Bearer $LLMFLOW_KEY" localhost:8000/admin/tenants` | `401` (only the admin key works there) |
| Brute force | 25 requests with a wrong key | `401`s then `429` |

Then open the dashboard: **Overview** (traffic, cost vs. largest model, cache rate), **Requests** (each routing decision), **Providers** (your keys), **API keys**, **Connect**, **Playground**, **Benchmarks**, and **Account** (password, two-factor, security activity).

## 6. Automated tests and the benchmark

```bash
npm test             # backend (pytest) + dashboard (vitest)
npm run check        # ruff, mypy --strict, tsc
npm run bench        # round-1 suite: 220 real calls, paced to Groq's limits; resumable
# round 2 (harder suites + router evaluation): see benchmarks/README.md
#   python -m llmflow.bench generate | run --suite ... | eval-router --lift [--calibrate]
```

Bench results appear on the dashboard's **Benchmarks** page and in `benchmarks/results/*.report.md`.
