"""Request log persistence (SQLAlchemy async; SQLite in dev, Postgres in prod)."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy import Float, Integer, String, func, inspect, select, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class RequestLog(Base):
    __tablename__ = "request_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[float] = mapped_column(Float, index=True)
    key_id: Mapped[str] = mapped_column(String(32))
    requested_model: Mapped[str] = mapped_column(String(128))
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16))  # ok | error
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    shadow_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    route_reason: Mapped[str] = mapped_column(String(512), default="")
    cache_status: Mapped[str] = mapped_column(String(8), default="none")  # none | miss | hit


@dataclass(frozen=True, slots=True)
class UsageSummary:
    requests: int
    errors: int
    prompt_tokens: int
    completion_tokens: int
    shadow_cost_usd: float


def _drop_legacy_tenant_table(sync_conn: Any) -> None:
    """The first BYOK schema stored a key hash on ``tenant``. Workspaces now have users and
    API keys in their own tables; replace the old (never-released) table when it is empty."""
    insp = inspect(sync_conn)
    if "tenant" not in insp.get_table_names():
        return
    if "key_hash" not in {c["name"] for c in insp.get_columns("tenant")}:
        return
    if sync_conn.execute(text("SELECT COUNT(*) FROM tenant")).scalar_one():
        raise RuntimeError(
            "legacy 'tenant' table has rows from an earlier schema; export or delete them first"
        )
    sync_conn.execute(text("DROP TABLE tenant"))


def _add_missing_columns(sync_conn: Any) -> None:
    """Minimal forward-only migration: add columns introduced after a table was created.
    Only additive changes are supported (new nullable or defaulted columns)."""
    insp = inspect(sync_conn)
    existing_tables = set(insp.get_table_names())
    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue
        have = {c["name"] for c in insp.get_columns(table.name)}
        for col in table.columns:
            if col.name in have:
                continue
            ddl = col.type.compile(dialect=sync_conn.dialect)
            if col.nullable:
                default = "NULL"
            elif isinstance(col.type, String):
                default = "'none'" if col.name == "cache_status" else "''"
            else:
                default = "0"
            sync_conn.execute(
                text(f'ALTER TABLE {table.name} ADD COLUMN "{col.name}" {ddl} DEFAULT {default}')
            )


def normalise_database_url(url: str) -> tuple[str, dict[str, Any]]:
    """Accept provider-style Postgres URLs (Neon, Render) and return an asyncpg URL plus
    ``connect_args``. ``sslmode=require`` becomes asyncpg's ``ssl`` argument; libpq-only
    parameters that asyncpg rejects are dropped."""
    parts = urlsplit(url)
    scheme = parts.scheme
    if scheme in ("postgres", "postgresql"):
        scheme = "postgresql+asyncpg"
    elif not scheme.startswith("postgresql+asyncpg"):
        return url, {}
    query = dict(parse_qsl(parts.query))
    sslmode = query.pop("sslmode", None)
    query.pop("channel_binding", None)
    connect_args: dict[str, Any] = {}
    if sslmode in ("require", "verify-ca", "verify-full"):
        connect_args["ssl"] = True
    cleaned = urlunsplit((scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
    return cleaned, connect_args


_AWAKE_FOR_S = 120.0  # trust a successful connection for this long before re-checking


class UsageRepo:
    def __init__(self, database_url: str) -> None:
        url, connect_args = normalise_database_url(database_url)
        kwargs: dict[str, Any] = {"connect_args": connect_args} if connect_args else {}
        if not url.startswith("sqlite"):
            # Hosted Postgres (e.g. Neon) suspends idle connections; verify before use.
            kwargs.update(pool_pre_ping=True, pool_recycle=300)
            # A suspended Neon compute can take several seconds to resume.
            connect_args.setdefault("timeout", 30)
            kwargs["connect_args"] = connect_args
        self._engine: AsyncEngine = create_async_engine(url, **kwargs)
        self._sessions = async_sessionmaker(self._engine, expire_on_commit=False)
        self._last_ok = float("-inf")

    @property
    def sessions(self) -> async_sessionmaker[AsyncSession]:
        return self._sessions

    async def init(self) -> None:
        async with self._engine.begin() as conn:
            await conn.run_sync(_drop_legacy_tenant_table)
            await conn.run_sync(Base.metadata.create_all)
            await conn.run_sync(_add_missing_columns)

    async def daily_totals(self, since: float) -> dict[str, tuple[int, float]]:
        """Per key id: (tokens, shadow cost) of successful requests since ``since``."""
        async with self._sessions() as session:
            rows = await session.execute(
                select(
                    RequestLog.key_id,
                    func.coalesce(
                        func.sum(RequestLog.prompt_tokens + RequestLog.completion_tokens), 0
                    ),
                    func.coalesce(func.sum(RequestLog.shadow_cost_usd), 0.0),
                )
                .where(RequestLog.ts >= since, RequestLog.status == "ok")
                .group_by(RequestLog.key_id)
            )
            return {k: (int(t), float(c)) for k, t, c in rows.all()}

    async def ping(self, attempts: int = 4, delay_s: float = 1.5) -> bool:
        """Open a connection and run ``SELECT 1``, retrying while a suspended hosted database
        (Neon) resumes. Returns False instead of raising."""
        for attempt in range(attempts):
            try:
                async with self._engine.connect() as conn:
                    await conn.execute(text("SELECT 1"))
                self._last_ok = time.monotonic()
                return True
            except Exception:  # any connect failure just means "not yet"
                if attempt + 1 < attempts:
                    await asyncio.sleep(delay_s * (attempt + 1))
        return False

    async def ensure_awake(self) -> bool:
        """True when the database answered recently or answers now. Free while it is warm, so
        callers can use it on every request that is about to need the database."""
        if time.monotonic() - self._last_ok < _AWAKE_FOR_S:
            return True
        return await self.ping()

    async def close(self) -> None:
        await self._engine.dispose()

    async def record(self, entry: RequestLog) -> None:
        entry.ts = entry.ts or time.time()
        async with self._sessions() as session:
            session.add(entry)
            await session.commit()

    async def since(
        self, ts: float, limit: int = 20_000, key_id: str | None = None
    ) -> list[RequestLog]:
        """Rows newer than ``ts``, oldest first (optionally for one key id). Bounded."""
        query = select(RequestLog).where(RequestLog.ts >= ts)
        if key_id is not None:
            query = query.where(RequestLog.key_id == key_id)
        async with self._sessions() as session:
            result = await session.execute(query.order_by(RequestLog.ts.desc()).limit(limit))
            return list(reversed(result.scalars().all()))

    async def page(
        self, limit: int, offset: int, status: str | None = None, key_id: str | None = None
    ) -> tuple[list[RequestLog], int]:
        query = select(RequestLog)
        count = select(func.count(RequestLog.id))
        if key_id is not None:
            query = query.where(RequestLog.key_id == key_id)
            count = count.where(RequestLog.key_id == key_id)
        if status:
            query = query.where(RequestLog.status == status)
            count = count.where(RequestLog.status == status)
        async with self._sessions() as session:
            rows = await session.execute(
                query.order_by(RequestLog.ts.desc()).limit(limit).offset(offset)
            )
            total = (await session.execute(count)).scalar_one()
        return list(rows.scalars().all()), int(total)

    async def summary(self) -> UsageSummary:
        async with self._sessions() as session:
            row = (
                await session.execute(
                    select(
                        func.count(RequestLog.id),
                        func.coalesce(func.sum(RequestLog.status != "ok"), 0),
                        func.coalesce(func.sum(RequestLog.prompt_tokens), 0),
                        func.coalesce(func.sum(RequestLog.completion_tokens), 0),
                        func.coalesce(func.sum(RequestLog.shadow_cost_usd), 0.0),
                    )
                )
            ).one()
        return UsageSummary(int(row[0]), int(row[1]), int(row[2]), int(row[3]), float(row[4]))
