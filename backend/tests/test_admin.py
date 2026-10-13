from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from llmflow.api.admin import percentile
from llmflow.api.app import create_app
from llmflow.catalog import Catalog
from llmflow.core.config import Settings
from llmflow.storage.usage import RequestLog, UsageRepo

from .conftest import FakeProvider

AUTH = {"Authorization": "Bearer adm"}


@pytest.fixture
def client(catalog: Catalog):  # type: ignore[no-untyped-def]
    settings = Settings(
        _env_file=None,
        api_keys="k",
        admin_api_keys="adm",
        min_key_length=1,
        database_url="sqlite+aiosqlite:///:memory:",
    )
    app = create_app(
        settings,
        catalog=catalog,
        providers={"p1": FakeProvider(), "p2": FakeProvider()},
        env={"K1": "x", "K2": "y"},
    )
    with TestClient(app) as c:
        yield c


def seed(c: TestClient, rows: list[RequestLog]) -> None:
    repo: UsageRepo = c.app.state.usage  # type: ignore[attr-defined]

    async def go() -> None:
        for r in rows:
            await repo.record(r)

    c.portal.call(go)  # type: ignore[union-attr]


def row(model: str, status: str = "ok", cost: float = 0.001, lat: float = 100.0) -> RequestLog:
    return RequestLog(
        ts=time.time() - 60,
        key_id="k",
        requested_model="auto",
        model=model if status == "ok" else None,
        provider="p1",
        status=status,
        prompt_tokens=100,
        completion_tokens=50,
        latency_ms=lat,
        shadow_cost_usd=cost,
        attempts=1,
        route_reason="r",
    )


def test_admin_requires_auth(client: TestClient) -> None:
    assert client.get("/admin/overview").status_code == 401
    # a client key is not an admin key
    assert client.get("/admin/overview", headers={"Authorization": "Bearer k"}).status_code == 401


def test_percentile_edges() -> None:
    assert percentile([], 50) is None
    assert percentile([5.0], 95) == 5.0
    assert percentile([1, 2, 3, 4, 5], 50) == 3


def test_overview_empty_window_is_well_formed(client: TestClient) -> None:
    data = client.get("/admin/overview?range=1h", headers=AUTH).json()
    assert data["totals"]["requests"] == 0
    assert data["totals"]["p50_latency_ms"] is None
    assert len(data["series"]) == 60


def test_overview_aggregates_and_computes_savings(client: TestClient) -> None:
    seed(client, [row("small", lat=50), row("small", lat=150), row("large"), row("x", "error")])
    t = client.get("/admin/overview?range=24h", headers=AUTH).json()["totals"]
    assert t["requests"] == 4 and t["errors"] == 1
    assert t["error_rate"] == 0.25
    assert t["tokens"] == 3 * 150
    assert t["reference_model"] == "large"  # highest quality prior among enabled
    # reference price 1.0 USD/1M in and out: 150 tokens * 3 ok rows
    assert t["reference_cost_usd"] == pytest.approx(450 / 1_000_000)
    assert t["saved_vs_reference_usd"] == pytest.approx(t["reference_cost_usd"] - 0.003)


def test_overview_by_model_and_tier_series(client: TestClient) -> None:
    seed(client, [row("small"), row("small"), row("medium")])
    d = client.get("/admin/overview?range=24h", headers=AUTH).json()
    assert [m["model"] for m in d["by_model"]] == ["small", "medium"]
    assert sum(p["small"] for p in d["series"]) == 2
    assert sum(p["medium"] for p in d["series"]) == 1


def test_requests_pagination_and_status_filter(client: TestClient) -> None:
    seed(client, [row("small"), row("medium"), row("x", "error")])
    page = client.get("/admin/requests?limit=2&offset=0", headers=AUTH).json()
    assert page["total"] == 3 and len(page["items"]) == 2
    errs = client.get("/admin/requests?status=error", headers=AUTH).json()
    assert errs["total"] == 1 and errs["items"][0]["status"] == "error"
    assert client.get("/admin/requests?limit=1000", headers=AUTH).status_code == 422


def test_providers_lists_all_models_with_quota_state(client: TestClient) -> None:
    d = client.get("/admin/providers", headers=AUTH).json()
    assert {m["id"] for m in d["models"]} == {"small", "medium", "large"}
    assert all(m["enabled"] and m["headroom"] == 1.0 for m in d["models"])
    assert {p["id"]: p["trains_on_data"] for p in d["providers"]} == {"p1": False, "p2": True}


def test_benchmarks_endpoint_serves_reports_and_ignores_path_tricks(
    client: TestClient, tmp_path: Path
) -> None:
    import json

    d = tmp_path / "bench"
    d.mkdir()
    (d / "a.report.json").write_text(json.dumps({"label": "MEASURED", "suite": "a"}))
    (tmp_path / "secret.report.json").write_text(json.dumps({"label": "SECRET"}))
    client.app.state.settings.benchmarks_dir = d  # type: ignore[attr-defined]
    data = client.get("/admin/benchmarks", headers=AUTH).json()
    assert data["available"] == ["a"] and data["report"]["suite"] == "a"
    evil = client.get("/admin/benchmarks?name=../secret", headers=AUTH).json()
    assert evil["selected"] == "a" and "SECRET" not in json.dumps(evil)


def test_benchmarks_empty_directory(client: TestClient, tmp_path: Path) -> None:
    client.app.state.settings.benchmarks_dir = tmp_path  # type: ignore[attr-defined]
    data = client.get("/admin/benchmarks", headers=AUTH).json()
    assert data == {"available": [], "selected": None, "report": None}
