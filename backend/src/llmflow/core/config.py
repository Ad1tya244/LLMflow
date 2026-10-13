"""Process configuration, read from environment variables (prefix ``LLMFLOW_``)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _split(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LLMFLOW_", env_file=".env", extra="ignore")

    # --- authentication -------------------------------------------------------
    api_keys: str = Field(default="", description="Comma-separated client API keys.")
    admin_api_keys: str = Field(
        default="",
        description="Comma-separated keys allowed to call /admin/*. Empty disables admin.",
    )
    session_idle_s: int = Field(default=1800, ge=60, description="Admin session idle timeout.")
    session_max_age_s: int = Field(default=43_200, ge=300, description="Admin session lifetime.")
    session_cookie_samesite: Literal["lax", "strict", "none"] = Field(
        default="lax",
        description="Use 'none' (requires HTTPS) when dashboard and API are on different sites.",
    )
    auth_disabled: bool = Field(default=False, description="Development only.")
    min_key_length: int = Field(
        default=16, ge=1, description="Reject shorter keys (the key id is a hash prefix)."
    )
    auth_fail_limit_per_min: int = Field(default=20, ge=1, description="Per client IP.")
    trust_forwarded_for: bool = Field(
        default=False, description="Use the last X-Forwarded-For hop (set when behind one proxy)."
    )

    # --- multi-tenant (bring-your-own provider keys) ----------------------------
    master_key: str = Field(
        default="",
        description="Fernet key(s), comma separated (first encrypts). Empty disables tenants.",
    )
    signup_enabled: bool = Field(default=False, description="Allow POST /signup.")
    signup_code: str = Field(default="", description="If set, required to sign up.")
    signup_limit_per_hour: int = Field(default=5, ge=1, description="Per client IP.")
    login_max_failures: int = Field(default=5, ge=1, description="Before an account locks.")
    login_lock_s: int = Field(default=900, ge=30, description="Account lock duration.")

    # --- infrastructure -------------------------------------------------------
    database_url: str = "sqlite+aiosqlite:///./llmflow.db"
    catalog_path: Path = Path("config/catalog.yaml")
    routing_config_path: Path = Path("config/routing.json")
    benchmarks_dir: Path = Field(
        default=Path("../benchmarks/results"), description="Where *.report.json files live."
    )
    request_timeout_s: float = 60.0
    max_attempts: int = Field(default=3, ge=1, le=10)
    log_level: str = "INFO"
    cors_origins: str = Field(
        default="http://localhost:5173", description="Comma-separated allowed dashboard origins."
    )
    enable_docs: bool = Field(default=False, description="Expose /docs and /openapi.json.")

    # --- abuse protection -----------------------------------------------------
    rate_limit_rpm: int = Field(default=60, ge=1, description="Requests per minute per client key.")
    max_body_bytes: int = Field(default=512_000, ge=1_000)
    max_messages: int = Field(default=200, ge=1)
    max_prompt_chars: int = Field(default=200_000, ge=100)
    max_tokens_cap: int = Field(default=8192, ge=1)

    # --- budgets (per client key, per UTC day; unset = unlimited) -------------
    daily_budget_usd: float | None = Field(default=None, gt=0)
    daily_token_budget: int | None = Field(default=None, gt=0)

    # --- response cache -------------------------------------------------------
    cache_ttl_s: int = Field(default=3600, ge=0, description="0 disables the cache.")
    cache_max_entries: int = Field(default=500, ge=1)

    @property
    def key_list(self) -> list[str]:
        return _split(self.api_keys)

    @property
    def admin_key_list(self) -> list[str]:
        return _split(self.admin_api_keys)

    @property
    def master_key_list(self) -> list[str]:
        return _split(self.master_key)

    @property
    def cors_list(self) -> list[str]:
        return _split(self.cors_origins)
