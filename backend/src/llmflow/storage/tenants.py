"""Workspaces, their users, API keys, provider keys, recovery codes and audit trail.

Everything secret is stored as a hash (passwords: argon2id; API keys and recovery codes:
SHA-256 of high-entropy values) or as Fernet ciphertext (provider keys)."""

from __future__ import annotations

import hashlib
import secrets
import time
from dataclasses import dataclass

from sqlalchemy import (
    Boolean,
    Float,
    Integer,
    String,
    Text,
    UniqueConstraint,
    delete,
    func,
    select,
    update,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Mapped, mapped_column

from llmflow.storage.usage import Base, RequestLog

KEY_PREFIX = "llmf_"
_LAST_USED_GRANULARITY_S = 60.0
_SETTINGS_TTL_S = 30.0


def hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def new_key() -> str:
    return KEY_PREFIX + secrets.token_urlsafe(32)


class EmailTaken(Exception):
    pass


# --- tables -----------------------------------------------------------------------------


class TenantRow(Base):
    __tablename__ = "tenant"

    id: Mapped[str] = mapped_column(String(24), primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[float] = mapped_column(Float)
    disabled: Mapped[bool] = mapped_column(Boolean, default=False)


class UserRow(Base):
    __tablename__ = "app_user"

    id: Mapped[str] = mapped_column(String(24), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(24), index=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[float] = mapped_column(Float)
    last_login_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[float] = mapped_column(Float, default=0.0)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    mfa_secret_ct: Mapped[str | None] = mapped_column(Text, nullable=True)  # Fernet ciphertext
    mfa_last_step: Mapped[int] = mapped_column(Integer, default=0)


class ApiKeyRow(Base):
    __tablename__ = "api_key"

    id: Mapped[str] = mapped_column(String(24), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(24), index=True)
    name: Mapped[str] = mapped_column(String(60))
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    last4: Mapped[str] = mapped_column(String(4))
    created_at: Mapped[float] = mapped_column(Float)
    last_used_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    revoked_at: Mapped[float | None] = mapped_column(Float, nullable=True)


class WorkspaceSettingsRow(Base):
    """Per-workspace defaults. A separate table (not columns on ``tenant``) so existing
    databases pick it up automatically without a migration."""

    __tablename__ = "workspace_settings"

    tenant_id: Mapped[str] = mapped_column(String(24), primary_key=True)
    cache_mode: Mapped[str] = mapped_column(String(8), default="auto")  # auto | always | off
    default_quality: Mapped[str] = mapped_column(String(8), default="balanced")
    daily_budget_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    daily_token_budget: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[float] = mapped_column(Float, default=0.0)


class ApiKeySecretRow(Base):
    """Encrypted copy of an application API key so its owner can view it again after
    re-authenticating. A separate table so older databases need no migration; keys created
    before this existed simply have no row and cannot be shown again."""

    __tablename__ = "api_key_secret"

    key_id: Mapped[str] = mapped_column(String(24), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(24), index=True)
    ciphertext: Mapped[str] = mapped_column(Text)


class RecoveryCodeRow(Base):
    __tablename__ = "recovery_code"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(24), index=True)
    code_hash: Mapped[str] = mapped_column(String(64))
    used_at: Mapped[float | None] = mapped_column(Float, nullable=True)


class AuditRow(Base):
    __tablename__ = "audit_event"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(24), index=True)
    ts: Mapped[float] = mapped_column(Float, index=True)
    actor: Mapped[str] = mapped_column(String(254))
    action: Mapped[str] = mapped_column(String(64))
    detail: Mapped[str] = mapped_column(String(300), default="")
    ip: Mapped[str] = mapped_column(String(45), default="")


class ProviderKeyRow(Base):
    __tablename__ = "tenant_provider_key"
    __table_args__ = (UniqueConstraint("tenant_id", "provider", name="uq_tenant_provider"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(24), index=True)
    provider: Mapped[str] = mapped_column(String(64))
    ciphertext: Mapped[str] = mapped_column(Text)
    last4: Mapped[str] = mapped_column(String(4))
    created_at: Mapped[float] = mapped_column(Float)


# --- value objects ------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class WorkspaceSettings:
    cache_mode: str = "auto"
    default_quality: str = "balanced"
    daily_budget_usd: float | None = None
    daily_token_budget: int | None = None


@dataclass(frozen=True, slots=True)
class Tenant:
    id: str
    name: str
    created_at: float
    disabled: bool


@dataclass(frozen=True, slots=True)
class User:
    id: str
    tenant_id: str
    email: str
    created_at: float
    last_login_at: float | None
    mfa_enabled: bool = False


@dataclass(frozen=True, slots=True)
class UserAuth:
    user: User
    password_hash: str
    failed_logins: int
    locked_until: float
    mfa_secret_ct: str | None = None
    mfa_last_step: int = 0


@dataclass(frozen=True, slots=True)
class ApiKey:
    id: str
    name: str
    last4: str
    created_at: float
    last_used_at: float | None
    revoked_at: float | None


@dataclass(frozen=True, slots=True)
class AuditEvent:
    ts: float
    actor: str
    action: str
    detail: str
    ip: str


def _tenant(r: TenantRow) -> Tenant:
    return Tenant(r.id, r.name, r.created_at, r.disabled)


def _user(r: UserRow) -> User:
    return User(r.id, r.tenant_id, r.email, r.created_at, r.last_login_at, bool(r.mfa_enabled))


def _key(r: ApiKeyRow) -> ApiKey:
    return ApiKey(r.id, r.name, r.last4, r.created_at, r.last_used_at, r.revoked_at)


class TenantRepo:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions
        self._settings_cache: dict[str, tuple[float, WorkspaceSettings]] = {}

    # --- workspaces and users -----------------------------------------------------------

    async def create_workspace(
        self, name: str, email: str, password_hash: str, recovery_hashes: list[str]
    ) -> tuple[Tenant, User]:
        now = time.time()
        tenant = TenantRow(
            id="t_" + secrets.token_hex(8), name=name, created_at=now, disabled=False
        )
        user = UserRow(
            id="u_" + secrets.token_hex(8), tenant_id=tenant.id, email=email,
            password_hash=password_hash, created_at=now,
        )  # fmt: skip
        async with self._sessions() as s:
            exists = (
                await s.execute(select(func.count(UserRow.id)).where(UserRow.email == email))
            ).scalar_one()
            if exists:
                raise EmailTaken
            s.add_all([tenant, user])
            s.add_all([RecoveryCodeRow(user_id=user.id, code_hash=h) for h in recovery_hashes])
            await s.commit()
        return _tenant(tenant), _user(user)

    async def get_tenant(self, tenant_id: str) -> Tenant | None:
        async with self._sessions() as s:
            row = await s.get(TenantRow, tenant_id)
        return _tenant(row) if row else None

    async def get_user(self, user_id: str) -> User | None:
        async with self._sessions() as s:
            row = await s.get(UserRow, user_id)
        return _user(row) if row else None

    async def user_auth(self, email: str) -> UserAuth | None:
        async with self._sessions() as s:
            row = (
                await s.execute(select(UserRow).where(UserRow.email == email))
            ).scalar_one_or_none()
        if row is None:
            return None
        return UserAuth(
            _user(row), row.password_hash, row.failed_logins, row.locked_until,
            row.mfa_secret_ct, row.mfa_last_step,
        )  # fmt: skip

    async def record_login_failure(self, user_id: str, max_failures: int, lock_s: float) -> None:
        async with self._sessions() as s:
            row = await s.get(UserRow, user_id)
            if row is None:
                return
            row.failed_logins += 1
            if row.failed_logins >= max_failures:
                row.locked_until = time.time() + lock_s
                row.failed_logins = 0
            await s.commit()

    async def record_login_success(self, user_id: str, new_hash: str | None = None) -> None:
        async with self._sessions() as s:
            row = await s.get(UserRow, user_id)
            if row is None:
                return
            row.failed_logins, row.locked_until, row.last_login_at = 0, 0.0, time.time()
            if new_hash:
                row.password_hash = new_hash
            await s.commit()

    async def set_password(self, user_id: str, password_hash: str) -> None:
        async with self._sessions() as s:
            await s.execute(
                update(UserRow)
                .where(UserRow.id == user_id)
                .values(password_hash=password_hash, failed_logins=0, locked_until=0.0)
            )
            await s.commit()

    async def user_auth_by_id(self, user_id: str) -> UserAuth | None:
        async with self._sessions() as s:
            row = await s.get(UserRow, user_id)
        if row is None:
            return None
        return UserAuth(
            _user(row), row.password_hash, row.failed_logins, row.locked_until,
            row.mfa_secret_ct, row.mfa_last_step,
        )  # fmt: skip

    async def set_mfa_pending(self, user_id: str, secret_ciphertext: str) -> None:
        """Stage a secret; MFA stays off until a code is confirmed with ``enable_mfa``."""
        async with self._sessions() as s:
            await s.execute(
                update(UserRow).where(UserRow.id == user_id)
                .values(mfa_secret_ct=secret_ciphertext, mfa_enabled=False, mfa_last_step=0)
            )  # fmt: skip
            await s.commit()

    async def enable_mfa(self, user_id: str, step: int) -> None:
        async with self._sessions() as s:
            await s.execute(
                update(UserRow)
                .where(UserRow.id == user_id)
                .values(mfa_enabled=True, mfa_last_step=step)
            )
            await s.commit()

    async def disable_mfa(self, user_id: str) -> None:
        async with self._sessions() as s:
            await s.execute(
                update(UserRow).where(UserRow.id == user_id)
                .values(mfa_enabled=False, mfa_secret_ct=None, mfa_last_step=0)
            )  # fmt: skip
            await s.commit()

    async def set_mfa_step(self, user_id: str, step: int) -> None:
        async with self._sessions() as s:
            await s.execute(update(UserRow).where(UserRow.id == user_id).values(mfa_last_step=step))
            await s.commit()

    async def list_workspaces(self) -> list[tuple[Tenant, str]]:
        """Workspaces with their owner's email (operator tooling)."""
        async with self._sessions() as s:
            rows = (
                await s.execute(
                    select(TenantRow, UserRow.email)
                    .join(UserRow, UserRow.tenant_id == TenantRow.id, isouter=True)
                    .order_by(TenantRow.created_at.desc())
                )
            ).all()
        return [(_tenant(t), email or "") for t, email in rows]

    async def set_disabled(self, tenant_id: str, disabled: bool) -> bool:
        async with self._sessions() as s:
            row = await s.get(TenantRow, tenant_id)
            if row is None:
                return False
            row.disabled = disabled
            await s.commit()
        return True

    async def delete_workspace(self, tenant_id: str) -> bool:
        async with self._sessions() as s:
            row = await s.get(TenantRow, tenant_id)
            if row is None:
                return False
            users = (
                await s.execute(select(UserRow.id).where(UserRow.tenant_id == tenant_id))
            ).scalars().all()  # fmt: skip
            if users:
                await s.execute(delete(RecoveryCodeRow).where(RecoveryCodeRow.user_id.in_(users)))
            for model in (
                UserRow,
                ApiKeyRow,
                ApiKeySecretRow,
                ProviderKeyRow,
                AuditRow,
                WorkspaceSettingsRow,
            ):
                await s.execute(delete(model).where(model.tenant_id == tenant_id))
            await s.execute(delete(RequestLog).where(RequestLog.key_id == tenant_id))
            await s.delete(row)
            await s.commit()
        self._settings_cache.pop(tenant_id, None)
        return True

    # --- workspace settings -------------------------------------------------------------

    async def get_settings(self, tenant_id: str) -> WorkspaceSettings:
        """Defaults for a workspace. Cached briefly because it is read on every request;
        ``put_settings`` refreshes the cache (single instance)."""
        now = time.monotonic()
        hit = self._settings_cache.get(tenant_id)
        if hit is not None and hit[0] > now:
            return hit[1]
        async with self._sessions() as s:
            row = await s.get(WorkspaceSettingsRow, tenant_id)
        value = (
            WorkspaceSettings()
            if row is None
            else WorkspaceSettings(
                row.cache_mode, row.default_quality, row.daily_budget_usd, row.daily_token_budget
            )
        )
        self._settings_cache[tenant_id] = (now + _SETTINGS_TTL_S, value)
        return value

    async def put_settings(self, tenant_id: str, value: WorkspaceSettings) -> None:
        async with self._sessions() as s:
            row = await s.get(WorkspaceSettingsRow, tenant_id)
            if row is None:
                row = WorkspaceSettingsRow(tenant_id=tenant_id)
                s.add(row)
            row.cache_mode = value.cache_mode
            row.default_quality = value.default_quality
            row.daily_budget_usd = value.daily_budget_usd
            row.daily_token_budget = value.daily_token_budget
            row.updated_at = time.time()
            await s.commit()
        self._settings_cache[tenant_id] = (time.monotonic() + _SETTINGS_TTL_S, value)

    # --- API keys (used by applications on /v1) ------------------------------------------

    async def create_api_key(self, tenant_id: str, name: str) -> tuple[ApiKey, str]:
        raw = new_key()
        row = ApiKeyRow(
            id="k_" + secrets.token_hex(8), tenant_id=tenant_id, name=name,
            key_hash=hash_key(raw), last4=raw[-4:], created_at=time.time(),
        )  # fmt: skip
        async with self._sessions() as s:
            s.add(row)
            await s.commit()
        return _key(row), raw

    async def list_api_keys(self, tenant_id: str) -> list[ApiKey]:
        async with self._sessions() as s:
            rows = (
                await s.execute(
                    select(ApiKeyRow)
                    .where(ApiKeyRow.tenant_id == tenant_id)
                    .order_by(ApiKeyRow.created_at.desc())
                )
            ).scalars()
            return [_key(r) for r in rows]

    async def revoke_api_key(self, tenant_id: str, key_id: str) -> bool:
        async with self._sessions() as s:
            row = (
                await s.execute(
                    select(ApiKeyRow).where(
                        ApiKeyRow.id == key_id, ApiKeyRow.tenant_id == tenant_id
                    )
                )
            ).scalar_one_or_none()
            if row is None or row.revoked_at is not None:
                return False
            row.revoked_at = time.time()
            await s.execute(delete(ApiKeySecretRow).where(ApiKeySecretRow.key_id == key_id))
            await s.commit()
        return True

    async def store_api_key_secret(self, tenant_id: str, key_id: str, ciphertext: str) -> None:
        async with self._sessions() as s:
            s.add(ApiKeySecretRow(key_id=key_id, tenant_id=tenant_id, ciphertext=ciphertext))
            await s.commit()

    async def api_key_secret(self, tenant_id: str, key_id: str) -> str | None:
        """Ciphertext for an active key of this tenant, else None."""
        async with self._sessions() as s:
            row = (
                await s.execute(
                    select(ApiKeySecretRow)
                    .join(ApiKeyRow, ApiKeyRow.id == ApiKeySecretRow.key_id)
                    .where(
                        ApiKeySecretRow.key_id == key_id,
                        ApiKeySecretRow.tenant_id == tenant_id,
                        ApiKeyRow.revoked_at.is_(None),
                    )
                )
            ).scalar_one_or_none()
            return None if row is None else row.ciphertext

    async def revealable_key_ids(self, tenant_id: str) -> set[str]:
        async with self._sessions() as s:
            rows = (
                await s.execute(
                    select(ApiKeySecretRow.key_id).where(ApiKeySecretRow.tenant_id == tenant_id)
                )
            ).scalars()
            return set(rows)

    async def tenant_for_api_key(self, raw: str) -> tuple[Tenant, ApiKey] | None:
        """Resolve a presented API key (by hash) to its workspace; revoked keys never match."""
        async with self._sessions() as s:
            row = (
                await s.execute(
                    select(ApiKeyRow).where(
                        ApiKeyRow.key_hash == hash_key(raw), ApiKeyRow.revoked_at.is_(None)
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                return None
            tenant = await s.get(TenantRow, row.tenant_id)
            if tenant is None:
                return None
            now = time.time()
            if row.last_used_at is None or now - row.last_used_at > _LAST_USED_GRANULARITY_S:
                row.last_used_at = now  # coarse, to avoid a write per request
                await s.commit()
            return _tenant(tenant), _key(row)

    # --- recovery codes --------------------------------------------------------------------

    async def replace_recovery_codes(self, user_id: str, hashes: list[str]) -> None:
        async with self._sessions() as s:
            await s.execute(delete(RecoveryCodeRow).where(RecoveryCodeRow.user_id == user_id))
            s.add_all([RecoveryCodeRow(user_id=user_id, code_hash=h) for h in hashes])
            await s.commit()

    async def consume_recovery_code(self, user_id: str, code_hash: str) -> bool:
        async with self._sessions() as s:
            row = (
                await s.execute(
                    select(RecoveryCodeRow).where(
                        RecoveryCodeRow.user_id == user_id,
                        RecoveryCodeRow.code_hash == code_hash,
                        RecoveryCodeRow.used_at.is_(None),
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                return False
            row.used_at = time.time()
            await s.commit()
        return True

    async def unused_recovery_codes(self, user_id: str) -> int:
        async with self._sessions() as s:
            return int(
                (
                    await s.execute(
                        select(func.count(RecoveryCodeRow.id)).where(
                            RecoveryCodeRow.user_id == user_id, RecoveryCodeRow.used_at.is_(None)
                        )
                    )
                ).scalar_one()
            )

    # --- audit -------------------------------------------------------------------------------

    async def audit(
        self, tenant_id: str, actor: str, action: str, detail: str = "", ip: str = ""
    ) -> None:
        async with self._sessions() as s:
            s.add(AuditRow(tenant_id=tenant_id, ts=time.time(), actor=actor[:254],
                           action=action[:64], detail=detail[:300], ip=ip[:45]))  # fmt: skip
            await s.commit()

    async def audit_log(self, tenant_id: str, limit: int = 100) -> list[AuditEvent]:
        async with self._sessions() as s:
            rows = (
                await s.execute(
                    select(AuditRow)
                    .where(AuditRow.tenant_id == tenant_id)
                    .order_by(AuditRow.ts.desc(), AuditRow.id.desc())
                    .limit(limit)
                )
            ).scalars()
            return [AuditEvent(r.ts, r.actor, r.action, r.detail, r.ip) for r in rows]

    # --- provider keys (ciphertext only; encryption happens in the caller) -------------------

    async def put_provider_key(
        self, tenant_id: str, provider: str, ciphertext: str, last4: str
    ) -> None:
        async with self._sessions() as s:
            row = (
                await s.execute(
                    select(ProviderKeyRow).where(
                        ProviderKeyRow.tenant_id == tenant_id, ProviderKeyRow.provider == provider
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                s.add(ProviderKeyRow(tenant_id=tenant_id, provider=provider, ciphertext=ciphertext,
                                     last4=last4, created_at=time.time()))  # fmt: skip
            else:
                row.ciphertext, row.last4, row.created_at = ciphertext, last4, time.time()
            await s.commit()

    async def delete_provider_key(self, tenant_id: str, provider: str) -> bool:
        async with self._sessions() as s:
            res = await s.execute(
                delete(ProviderKeyRow).where(
                    ProviderKeyRow.tenant_id == tenant_id, ProviderKeyRow.provider == provider
                )
            )
            await s.commit()
        return bool(res.rowcount)  # type: ignore[attr-defined]

    async def provider_keys(self, tenant_id: str) -> dict[str, tuple[str, str]]:
        """provider -> (ciphertext, last4)"""
        async with self._sessions() as s:
            rows = (
                await s.execute(select(ProviderKeyRow).where(ProviderKeyRow.tenant_id == tenant_id))
            ).scalars()
            return {r.provider: (r.ciphertext, r.last4) for r in rows}
