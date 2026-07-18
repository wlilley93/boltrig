"""The kernel composition root.

Wires the store and the dispatch components into one object. It implements
policy nowhere itself - it delegates to the dispatcher, grant checker, rate
limiter, credential resolver, audit writer, HITL manager and cost accountant
(thin core, P1). The fleet attaches its agent invoker via
``set_agent_invoker`` so reasoning-bound verbs can dispatch to a child agent
without the kernel importing the fleet (no cycle).
"""

from __future__ import annotations

from typing import Any

from boltrig.adapters.base import Adapter
from boltrig.models import InvocationContext
from boltrig.store import Store

from .audit import AuditWriter
from .cost import AlertFn, CostAccountant
from .security_events import AuditAnchorer, SecurityWriter
from .credentials import CredentialResolver, SecretStore
from .dispatch import AgentInvoker, Dispatcher
from .grants import GrantChecker
from .hitl import HITLManager
from .ratelimit import Counter, RateLimiter
from .registry import KernelRegistry

__all__ = ["Kernel"]


class Kernel:
    def __init__(
        self,
        store: Store,
        *,
        secret_store: SecretStore | None = None,
        counter: Counter | None = None,
        blocking_verbs: set[str] | None = None,
        alert: AlertFn | None = None,
    ) -> None:
        self.store = store
        self.grants = GrantChecker()
        self.rate_limiter = RateLimiter(counter)
        self.credentials = CredentialResolver(store, secret_store)
        self.audit = AuditWriter(store)
        # [2026] VJS-COUNTY 9: the distinct, tamper-evident security-signal stream
        # (D3) and the audit rollup anchorer (D4). Both are thin over the store; the
        # security writer records fail-safe so a signal never breaks a guarded path.
        self.security = SecurityWriter(store)
        self.anchorer = AuditAnchorer(store)
        self.hitl = HITLManager(store)
        self.cost = CostAccountant(store, alert)
        self.registry = KernelRegistry(store)
        self._blocking_verbs = blocking_verbs or set()

        from boltrig.adapters.loader import AdapterLoader
        from boltrig.observability.orb_presence import build_event_relay

        from .mcp import McpFace

        self.loader = AdapterLoader()
        # MCP server face: granted verbs as MCP tools, every call via the chokepoint.
        self.mcp = McpFace(self)
        # Event relay: run/conversation event streams for the conversational layer. The factory
        # upgrades it to the desktop-orb presence relay when orbctl exists (see orb_presence.py);
        # everywhere else it is the plain EventRelay.
        self.events = build_event_relay()
        self.dispatcher = Dispatcher(
            store,
            grants=self.grants,
            rate_limiter=self.rate_limiter,
            credentials=self.credentials,
            audit=self.audit,
            hitl=self.hitl,
            cost=self.cost,
            adapter_provider=self.loader.get,
            agent_invoker=None,
            blocking_verbs=self._blocking_verbs,
            events=self.events,
            security=self.security,
        )

    # --- wiring ---
    def set_agent_invoker(self, invoker: AgentInvoker) -> None:
        """Attach the fleet's reasoning-verb invoker (US-KER-02)."""
        self.dispatcher._agent_invoker = invoker

    async def register_adapter(self, tenant_id: str, adapter: Adapter) -> list[str]:
        """Load an adapter and register its verbs as data (P1). Returns verb ids."""
        from boltrig.models import AdapterHealth, AdapterRecord

        self.loader.register(tenant_id, adapter)
        await self.store.upsert_adapter(
            AdapterRecord(
                id=adapter.id,
                tenant_id=tenant_id,
                version=getattr(adapter, "version", "0"),
                runtime=getattr(adapter, "runtime", "script"),
                source=getattr(adapter, "source", "builtin"),
                module_ref=type(adapter).__module__,
                health=AdapterHealth.UNKNOWN,
                activated=getattr(adapter, "activated", True),
            )
        )
        return await self.registry.register_adapter_verbs(tenant_id, adapter)

    # --- the dispatch chokepoint (P2) ---
    async def invoke(
        self,
        noun: str,
        verb: str,
        params: dict[str, Any],
        context: InvocationContext,
        *,
        idempotency_key: str | None = None,
        approval_id: str | None = None,
    ) -> dict[str, Any]:
        return await self.dispatcher.invoke(
            noun, verb, params, context,
            idempotency_key=idempotency_key, approval_id=approval_id,
        )

    async def discover(
        self,
        tenant_id: str,
        context: InvocationContext | None = None,
        noun_id: str | None = None,
    ) -> dict[str, Any]:
        perms = await self.store.get_tenant_permissions(tenant_id)
        result = await self.registry.discover(tenant_id, perms, context, noun_id)
        # enrich each verb with live adapter health for the Router panel (US-UI-03)
        for v in result.get("verbs", []):
            binding = v.get("binding")
            if binding and binding["target_type"] == "adapter":
                v["health"] = self.loader.health_of(tenant_id, binding["target_ref"])
        return result

    async def list_work(
        self,
        tenant_id: str,
        *,
        departments: list[str] | None = None,
        status: Any = None,
        workspace_id: str | None = None,
        enforce_workspace: bool = False,
    ) -> list[Any]:
        """List work items, row-scoped by department at the store (US-IAM-02).

        ``departments=None`` is unrestricted (org-admin); a list restricts to work
        owned by those departments. Scoping is enforced in the store, never in the
        HTTP handler, so no caller can widen it."""
        return await self.store.list_work_items(
            tenant_id,
            status,
            departments=departments,
            workspace_id=workspace_id,
            enforce_workspace=enforce_workspace,
        )
