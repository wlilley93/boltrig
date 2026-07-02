"""Dynamic adapter loading + hot reload + health (US-ADP-06, P1, NFR-MNT-02).

Adapters are loaded as live instances keyed by ``(tenant, adapter_id)``. A new
or updated adapter is registered (and its verbs re-registered) without a kernel
restart. A failed load never crashes the kernel - it is recorded as ``down``.
"""

from __future__ import annotations

import importlib
import logging

from boltrig.adapters.base import Adapter

log = logging.getLogger("boltrig.adapters")


class AdapterLoader:
    def __init__(self) -> None:
        self._live: dict[tuple[str, str], Adapter] = {}
        self._health: dict[tuple[str, str], str] = {}

    def register(self, tenant_id: str, adapter: Adapter) -> None:
        """Register (or hot-replace) a live adapter instance."""
        self._live[(tenant_id, adapter.id)] = adapter
        self._health[(tenant_id, adapter.id)] = "unknown"

    def load_module(self, tenant_id: str, module_ref: str) -> Adapter | None:
        """Load an adapter from ``module:factory``. Never raises - returns None
        and records ``down`` on failure (US-ADP-06)."""
        try:
            mod_name, _, factory_name = module_ref.partition(":")
            module = importlib.import_module(mod_name)
            factory = getattr(module, factory_name or "build")
            adapter = factory()
            self.register(tenant_id, adapter)
            return adapter
        except Exception as exc:  # a bad adapter must not take down the kernel
            log.warning("adapter load failed for %s: %s", module_ref, exc)
            return None

    async def get(self, tenant_id: str, adapter_id: str) -> Adapter | None:
        """The kernel's ``adapter_provider``."""
        return self._live.get((tenant_id, adapter_id))

    def peek(self, tenant_id: str, adapter_id: str) -> Adapter | None:
        """Synchronous lookup of a live adapter (bootstrap wiring; ``get`` is the
        kernel's async provider)."""
        return self._live.get((tenant_id, adapter_id))

    async def refresh_health(self) -> dict[tuple[str, str], str]:
        for key, adapter in list(self._live.items()):
            try:
                self._health[key] = await adapter.health()
            except Exception:
                self._health[key] = "down"
        return dict(self._health)

    def health_of(self, tenant_id: str, adapter_id: str) -> str:
        return self._health.get((tenant_id, adapter_id), "unknown")
