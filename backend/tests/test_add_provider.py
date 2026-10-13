from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from llmflow.catalog import load_catalog
from llmflow.tools.add_provider import ToolError, build_entry, main, parse_model, write_entry

MAIN = """
providers:
  groq: {base_url: "https://api.groq.com/openai/v1", api_key_env: GROQ_API_KEY}
models:
  - {id: g-small, provider: groq, upstream_model: m, tier: small, quality: 0.5,
     context_window: 1000, price_in: 0.1, price_out: 0.1}
"""


@pytest.mark.parametrize(
    ("spec", "upstream", "tier", "pin", "pout"),
    [
        ("gpt-4o-mini:medium", "gpt-4o-mini", "medium", 0.0, 0.0),
        ("gpt-4o-mini:medium:0.15:0.6", "gpt-4o-mini", "medium", 0.15, 0.6),
        (
            "meta-llama/llama-3.3-70b-instruct:free:large",
            "meta-llama/llama-3.3-70b-instruct:free",
            "large",
            0.0,
            0.0,
        ),
    ],
)
def test_parse_model(spec: str, upstream: str, tier: str, pin: float, pout: float) -> None:
    m = parse_model(spec, "p")
    assert (m["upstream_model"], m["tier"], m["price_in"], m["price_out"]) == (
        upstream,
        tier,
        pin,
        pout,
    )
    assert m["id"].startswith("p-")


@pytest.mark.parametrize("bad", ["justname", "x:huge", "x:small:1", "x:small:-1:2", ":small"])
def test_parse_model_rejects_bad_specs(bad: str) -> None:
    with pytest.raises(ToolError):
        parse_model(bad, "p")


def test_entry_validation() -> None:
    ok = dict(
        provider_id="or",
        base_url="https://openrouter.ai/api/v1",
        key_env="OR_KEY",
        models=["m:small"],
        trains_on_data=True,
    )
    assert build_entry(**ok)["providers"]["or"]["trains_on_data"] is True  # type: ignore[arg-type]
    for patch in (
        {"provider_id": "Bad Id"},
        {"key_env": "lowercase"},
        {"base_url": "http://remote.example.com/v1"},
        {"base_url": "https://u:p@x.example.com"},
        {"models": []},
    ):
        with pytest.raises(ToolError):
            build_entry(**{**ok, **patch})  # type: ignore[arg-type]
    assert build_entry(**{**ok, "base_url": "http://localhost:11434/v1"})  # type: ignore[arg-type]


def test_written_file_is_loaded_and_merged_by_catalog(tmp_path: Path) -> None:
    (tmp_path / "catalog.yaml").write_text(MAIN)
    entry = build_entry(
        "or", "https://openrouter.ai/api/v1", "OR_KEY", ["vendor/x:free:large"], False
    )
    target = write_entry(entry, tmp_path)
    assert target == tmp_path / "catalog.d" / "or.yaml"
    assert "OR_KEY" in target.read_text() and "sk-" not in target.read_text()
    cat = load_catalog(tmp_path / "catalog.yaml")
    assert set(cat.providers) == {"groq", "or"}
    assert "or-vendor-x-free" in cat.models
    with pytest.raises(ToolError):  # no silent overwrite
        write_entry(entry, tmp_path)


def test_duplicate_ids_across_files_are_rejected(tmp_path: Path) -> None:
    (tmp_path / "catalog.yaml").write_text(MAIN)
    d = tmp_path / "catalog.d"
    d.mkdir()
    (d / "dup.yaml").write_text(
        yaml.safe_dump({"providers": {"groq": {"base_url": "https://x", "api_key_env": "K"}}})
    )
    with pytest.raises(ValueError, match="duplicate provider"):
        load_catalog(tmp_path / "catalog.yaml")


def test_cli_add_writes_file_and_reports_errors(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(["add", "--id", "oa", "--base-url", "https://api.example.com/v1", "--key-env", "OA_KEY",
               "--model", "m1:small", "--config-dir", str(tmp_path)])  # fmt: skip
    assert rc == 0 and (tmp_path / "catalog.d" / "oa.yaml").exists()
    assert "OA_KEY" in capsys.readouterr().out
    assert main(["add", "--id", "oa", "--base-url", "http://evil.example.com", "--key-env", "OA_KEY",
                 "--model", "m1:small", "--config-dir", str(tmp_path)]) == 2  # fmt: skip
