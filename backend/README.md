# LLMFlow backend

FastAPI gateway: OpenAI-compatible `/v1/*`, workspace accounts and BYOK provider keys, routing,
cache, budgets, audit log, and operator endpoints under `/admin/*` (Bearer admin key only).

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev,postgres]"
cp .env.example .env            # set keys; see the table in ../README.md
PYTHONPATH=src .venv/bin/uvicorn --factory llmflow.api.app:create_app --port 8000
```

Most people should run everything from the repository root with `npm run dev`.

Quality gates: `ruff check . && ruff format --check . && mypy src && pytest && bandit -r src`.

Layout: `api/` HTTP layer and auth, `providers/` upstream adapters and quota tracking, `routing/`
difficulty analysis and policy, `security/` vault, passwords, TOTP, `storage/` SQLAlchemy models,
`tools/` operator CLIs (add a provider, rotate the master key), `bench/` benchmark harness.
