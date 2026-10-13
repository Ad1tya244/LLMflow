from __future__ import annotations

from pathlib import Path

import pytest

from llmflow.catalog import environment, load_catalog


def test_environment_overlays_dotenv_and_real_env_wins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = tmp_path / ".env"
    f.write_text("FROM_FILE=a\nBOTH=file\n")
    monkeypatch.setenv("BOTH", "env")
    env = environment(f)
    assert env["FROM_FILE"] == "a"
    assert env["BOTH"] == "env"


def test_missing_dotenv_is_fine(tmp_path: Path) -> None:
    assert isinstance(environment(tmp_path / "nope.env"), dict)


def test_shipped_catalog_is_valid() -> None:
    cat = load_catalog(Path(__file__).parents[1] / "config" / "catalog.yaml")
    assert cat.models and all(m.provider in cat.providers for m in cat.models.values())


def test_models_disabled_in_catalog_are_never_enabled() -> None:
    from llmflow.catalog import Catalog, Limits, ModelSpec, ProviderSpec, Tier

    def spec(mid: str, enabled: bool) -> ModelSpec:
        return ModelSpec(
            id=mid,
            provider="p",
            upstream_model=mid,
            tier=Tier.SMALL,
            quality=0.5,
            context_window=1000,
            price_in=0,
            price_out=0,
            limits=Limits(),
            enabled=enabled,
        )

    cat = Catalog(
        providers={"p": ProviderSpec(id="p", base_url="http://x", api_key_env="K")},
        models={"on": spec("on", True), "off": spec("off", False)},
    )
    assert [m.id for m in cat.enabled_models({"K": "secret"})] == ["on"]
