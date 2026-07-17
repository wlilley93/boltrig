"""Dynamic adapter loading + hot reload + health (US-ADP-06, P1, NFR-MNT-02).

Adapters are loaded as live instances keyed by ``(tenant, adapter_id)``. A new
or updated adapter is registered (and its verbs re-registered) without a kernel
restart. A failed load never crashes the kernel - it is recorded as ``down``.
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import time

from boltrig.adapters.base import Adapter

log = logging.getLogger("boltrig.adapters")

# Bounds for adapter health probing (FR-OPS-05): one hung backend is recorded
# as ``down`` after PROBE_TIMEOUT_S instead of hanging the caller, and the
# cached posture is re-probed in the background at most once per
# REFRESH_INTERVAL_S (the Compose ``/healthz`` poll cadence).
PROBE_TIMEOUT_S = 2.5
REFRESH_INTERVAL_S = 30.0


class AdapterLoader:
    def __init__(self) -> None:
        self._live: dict[tuple[str, str], Adapter] = {}
        self._health: dict[tuple[str, str], str] = {}
        self._refresh_task: asyncio.Task[dict[tuple[str, str], str]] | None = None
        self._refreshed_at: float | None = None  # time.monotonic(); None = never

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

    async def refresh_health(
        self, *, probe_timeout_s: float = PROBE_TIMEOUT_S
    ) -> dict[tuple[str, str], str]:
        """Probe every live adapter, bounded per adapter: a slow or hung
        backend is recorded as ``down`` after ``probe_timeout_s`` rather than
        hanging the caller."""
        for key, adapter in list(self._live.items()):
            try:
                self._health[key] = await asyncio.wait_for(adapter.health(), probe_timeout_s)
            except Exception:
                self._health[key] = "down"
        self._refreshed_at = time.monotonic()
        return dict(self._health)

    def health_snapshot(self) -> dict[tuple[str, str], str]:
        """The cached posture, refreshed in the background when stale.

        Liveness (``/healthz``) reads this and must never await live adapter
        I/O: a slow or unreachable backend must not be able to make the probe
        slow or non-200 and flap a live kernel (FR-OPS-05). Staleness kicks a
        bounded refresh onto the running loop, off the request path."""
        last = self._refreshed_at
        stale = last is None or time.monotonic() - last >= REFRESH_INTERVAL_S
        task = self._refresh_task
        if stale and self._live and (task is None or task.done()):
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:  # no loop (sync caller): just serve the cache
                pass
            else:
                self._refresh_task = loop.create_task(self.refresh_health())
        return dict(self._health)

    def health_of(self, tenant_id: str, adapter_id: str) -> str:
        return self._health.get((tenant_id, adapter_id), "unknown")
