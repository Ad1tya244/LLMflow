"""Per-tenant routing scopes built from the tenant's own decrypted provider keys."""

from __future__ import annotations

import logging
import time
from collections import OrderedDict
from collections.abc import Callable

from llmflow.catalog import Catalog, ProviderSpec
from llmflow.providers.base import Provider
from llmflow.providers.quota import QuotaTracker
from llmflow.security.vault import KeyVault, VaultError
from llmflow.service import Scope
from llmflow.storage.tenants import TenantRepo

log = logging.getLogger(__name__)

ProviderFactory = Callable[[ProviderSpec, str], Provider]


class TenantScopes:
    """Builds and caches a ``Scope`` per tenant.

    Decrypted keys live only inside the provider objects held by cached scopes (bounded size,
    short TTL) and are dropped on update/delete/rotate via ``invalidate``. Quota counters
    survive invalidation so re-saving a key does not reset a tenant's local rate limiting.
    """

    def __init__(
        self,
        catalog: Catalog,
        repo: TenantRepo,
        vault: KeyVault,
        factory: ProviderFactory,
        *,
        ttl_s: float = 300.0,
        max_entries: int = 256,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._catalog = catalog
        self._repo = repo
        self._vault = vault
        self._factory = factory
        self._ttl = ttl_s
        self._max = max_entries
        self._clock = clock
        self._scopes: OrderedDict[str, tuple[float, Scope]] = OrderedDict()
        self._quotas: OrderedDict[str, QuotaTracker] = OrderedDict()

    def quota_for(self, tenant_id: str) -> QuotaTracker:
        return self._quota(tenant_id)

    def _quota(self, tenant_id: str) -> QuotaTracker:
        q = self._quotas.get(tenant_id)
        if q is None:
            q = self._quotas[tenant_id] = QuotaTracker()
            while len(self._quotas) > self._max * 4:
                self._quotas.popitem(last=False)
        self._quotas.move_to_end(tenant_id)
        return q

    def invalidate(self, tenant_id: str) -> None:
        self._scopes.pop(tenant_id, None)
        # a key was replaced or removed: clear provider-disabled flags from the old key
        self._quotas.pop(tenant_id, None)

    async def get(self, tenant_id: str) -> Scope:
        now = self._clock()
        cached = self._scopes.get(tenant_id)
        if cached and now - cached[0] < self._ttl:
            self._scopes.move_to_end(tenant_id)
            return cached[1]
        providers: dict[str, Provider] = {}
        for provider_id, (ciphertext, _last4) in (
            await self._repo.provider_keys(tenant_id)
        ).items():
            spec = self._catalog.providers.get(provider_id)
            if spec is None:
                continue  # provider removed from the catalog since the key was saved
            try:
                providers[provider_id] = self._factory(
                    spec, self._vault.decrypt(tenant_id, provider_id, ciphertext)
                )
            except VaultError:
                log.error("cannot decrypt %s key for tenant %s", provider_id, tenant_id)
        enabled = [
            m for m in self._catalog.models.values() if m.enabled and m.provider in providers
        ]
        scope = Scope(enabled=enabled, providers=providers, quota=self._quota(tenant_id))
        self._scopes[tenant_id] = (now, scope)
        while len(self._scopes) > self._max:
            self._scopes.popitem(last=False)
        return scope
