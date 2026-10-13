"""Re-encrypt every stored provider key under a new master key.

Procedure (no downtime for reads, since the server accepts a list of keys):

  1. Generate a new key:
       python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
  2. Put it FIRST in LLMFLOW_MASTER_KEY, keeping the old one after a comma:
       LLMFLOW_MASTER_KEY=<new>,<old>
  3. Run this tool (add --dry-run first to see what would change):
       python -m llmflow.tools.rotate_master_key
  4. When it reports 0 failures, remove <old> from LLMFLOW_MASTER_KEY and restart.

If a master key was leaked, rotating it is not enough: the provider keys themselves may be
exposed, so also ask affected users to rotate their provider keys.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass

from sqlalchemy import select

from llmflow.core.config import Settings
from llmflow.security.vault import KeyVault, VaultError
from llmflow.storage.tenants import ProviderKeyRow
from llmflow.storage.usage import UsageRepo


@dataclass(slots=True)
class RotationReport:
    total: int = 0
    rotated: int = 0
    failed: int = 0


async def rotate_all(repo: UsageRepo, vault: KeyVault, *, dry_run: bool) -> RotationReport:
    report = RotationReport()
    async with repo.sessions() as session:
        rows = (await session.execute(select(ProviderKeyRow))).scalars().all()
        for row in rows:
            report.total += 1
            try:
                new_token = vault.rotate(row.ciphertext)
            except VaultError:
                report.failed += 1
                continue
            if not dry_run:
                row.ciphertext = new_token
            report.rotated += 1
        if not dry_run:
            await session.commit()
    return report


async def _main(dry_run: bool) -> int:
    settings = Settings()
    keys = settings.master_key_list
    if len(keys) < 2:
        print(
            "error: LLMFLOW_MASTER_KEY must list the NEW key first and the old key(s) after it",
            file=sys.stderr,
        )
        return 2
    repo = UsageRepo(settings.database_url)
    try:
        await repo.init()
        report = await rotate_all(repo, KeyVault(keys), dry_run=dry_run)
    finally:
        await repo.close()
    mode = "would re-encrypt" if dry_run else "re-encrypted"
    print(f"{mode} {report.rotated}/{report.total} provider keys; {report.failed} failed")
    if report.failed:
        print(
            "failures mean a key was encrypted under a master key not in the list", file=sys.stderr
        )
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--dry-run", action="store_true", help="report only; change nothing")
    args = p.parse_args(argv)
    return asyncio.run(_main(args.dry_run))


if __name__ == "__main__":
    sys.exit(main())
