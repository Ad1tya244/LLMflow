from __future__ import annotations

import pytest

from llmflow.storage.usage import normalise_database_url


@pytest.mark.parametrize(
    ("raw", "url", "args"),
    [
        ("sqlite+aiosqlite:///./x.db", "sqlite+aiosqlite:///./x.db", {}),
        ("postgres://u:p@h/db", "postgresql+asyncpg://u:p@h/db", {}),
        (
            "postgresql://u:p@ep-1.neon.tech/db?sslmode=require&channel_binding=require",
            "postgresql+asyncpg://u:p@ep-1.neon.tech/db",
            {"ssl": True},
        ),
        (
            "postgresql+asyncpg://u:p@h/db?application_name=x",
            "postgresql+asyncpg://u:p@h/db?application_name=x",
            {},
        ),
    ],
)
def test_normalise_database_url(raw: str, url: str, args: dict[str, object]) -> None:
    assert normalise_database_url(raw) == (url, args)
