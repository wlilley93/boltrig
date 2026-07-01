"""The delegation pump: the org goes live (Beat 4; US-FLT-06, US-EXE-06).

The pump is the serving loop that makes the permanent tier real: it claims a
PENDING work item from the store (the Beat 3 lease, US-FLT-05), asks the Chief
of Staff to route it, hands it to the routed Department Head to decompose and
fan out, joins the children onto the parent, and walks the item's status. It
retries transient failures up to a cap (US-EXE-06) and parks BLOCKED / cap-breach
/ convergent-degraded work for a human (D6) instead of pretending it is done.

Two-lane policy (D5): chat keeps its DIRECT-SPAWN fast lane so an interactive
turn never waits on a queue; delegated work - channel intake, filed items, and
a chat turn's ``new_work_items`` follow-ons - flows through the pump. The lanes
share the spawner, the caps, and the audit trail; only the entry differs.

Execution rides the durable seam (US-EXE-02/05): under a durable executor the
claimed item is enqueued as the registered ``boltrig-work-item`` task; offline
the same body runs directly. One body, two carriages.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import TYPE_CHECKING, Any

from boltrig.models import (
    HITLType,
    InvocationContext,
    Urgency,
    WorkItem,
    WorkStatus,
)
from boltrig.work import normalise

from .chief_of_staff import ChiefOfStaff, Department
from .department_head import DepartmentHead, tree_root_id

if TYPE_CHECKING:  # type-only seams (fleet imports stay kernel-free)
    from boltrig.config.manifest import FleetManifest

    from .spawn import Spawner

log = logging.getLogger("boltrig.fleet.pump")

# The durable task name the pump registers / enqueues (US-EXE-02).
WORK_ITEM_TASK = "boltrig-work-item"

# Sane policy defaults (the manifest carries no pump policy section yet; these
# are the documented defaults until one exists).
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_LEASE_SECONDS = 300
DEFAULT_SPAWN_BUDGET = 32


async def persist_new_work_items(
    store: Any, parent: WorkItem, new_items: list[Any] | None, *, source: str
) -> list[WorkItem]:
    """Persist a step's discovered follow-on work as PENDING children (D7).

    Each entry becomes a normalised PENDING :class:`WorkItem` parented to the
    step's item (owner/department unset - the org lane routes it), so the pump
    picks it up on a later cycle instead of the follow-on being dropped.
    """
    created: list[WorkItem] = []
    for raw in new_items or []:
        payload = dict(raw) if isinstance(raw, dict) else {"intent": str(raw)}
        child = normalise(payload, source, parent.tenant_id)
        child.parent_id = parent.id
        child.depth = parent.depth + 1
        child.on_behalf_of = parent.on_behalf_of
        await store.create_work_item(child)
        created.append(child)
    return created


class WorkPump:
    """Claim -> route -> decompose -> join -> transition, forever (US-FLT-06)."""

    def __init__(
        self,
        kernel_or_store: Any,
        spawner: Spawner | Any,
        chief_of_staff: ChiefOfStaff,
        heads: dict[str, DepartmentHead | Any],
        executor: Any = None,
        *,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
        worker_id: str | None = None,
    ) -> None:
        self._store = getattr(kernel_or_store, "store", kernel_or_store)
        hitl = getattr(kernel_or_store, "hitl", None)
        if hitl is None:  # bare store: build the manager lazily (no kernel import cost)
            from boltrig.kernel.hitl import HITLManager

            hitl = HITLManager(self._store)
        self._hitl = hitl
        self._spawner = spawner
        self._cos = chief_of_staff
        self.heads = dict(heads)
        self._executor = executor
        self.max_attempts = max_attempts
        self.lease_seconds = lease_seconds
        self.worker_id = worker_id or f"pump-{uuid.uuid4().hex[:8]}"
        # One body, two carriages (US-EXE-05): the durable engine and the direct
        # path both run _run_item_payload; registering it here is what lets a
        # durable executor enqueue by name.
        register = getattr(executor, "register_task", None)
        if register is not None:
            register(WORK_ITEM_TASK, self._run_item_payload)

    # --- the serving loop -------------------------------------------------------
    async def run_once(self, tenant_id: str) -> bool:
        """Claim and process at most one work item. Returns whether one was claimed."""
        item = await self._store.claim_work_item(
            tenant_id, self.worker_id, self.lease_seconds
        )
        if item is None:
            return False
        payload = {"tenant_id": tenant_id, "item_id": item.id}
        if self._executor is not None and getattr(self._executor, "durable", False):
            # durable lane: the engine re-runs the registered body on a crash.
            await self._executor.enqueue(WORK_ITEM_TASK, payload)
        else:
            await self._run_item_payload(payload)
        return True

    async def run_forever(self, tenant_id: str, interval: float = 2.0) -> None:
        """Loop :meth:`run_once` with a short idle sleep; cancellable (P9)."""
        while True:
            try:
                busy = await self.run_once(tenant_id)
            except asyncio.CancelledError:
                raise
            except Exception:  # a bad cycle never kills the pump (P9)
                log.exception("pump cycle failed; continuing")
                busy = False
            if not busy:
                await asyncio.sleep(interval)

    # --- one item, end to end -----------------------------------------------------
    async def handle_claimed_item(self, item: WorkItem) -> WorkItem:
        """Route -> head.handle -> aggregate -> transition (US-FLT-06, D6)."""
        store = self._store
        tenant = item.tenant_id
        run_id = item.hatchet_run_id or item.id

        if item.status == WorkStatus.BLOCKED:  # blocked work is a human's, not a retry's
            await self._park(
                item, run_id,
                reason="blocked",
                detail="the item is blocked; a human must unblock or re-queue it",
            )
            return item

        ctx = await self._context_for(item, run_id)
        await store.upsert_checkpoint(tenant, run_id, "route", "started")
        department = await self._cos.route(item, ctx)
        head = self._head_for(department)
        item.owner_member = head.name
        await store.update_work_item(item)
        await store.upsert_checkpoint(
            tenant, run_id, "route", "done", output={"department": department}
        )

        await store.upsert_checkpoint(tenant, run_id, "execute", "started")
        tree_id = await tree_root_id(store, item)
        outcome = await head.handle(item, ctx, tree_id=tree_id)

        # Join the step onto the parent: the aggregate is the item's result and
        # the degraded flag is any child's degradation (US-FLT-07).
        children = list(outcome.get("children") or [])
        item.result = outcome
        item.degraded = any(bool(c.get("degraded")) for c in children)
        await persist_new_work_items(
            store, item, outcome.get("new_work_items"), source="internal"
        )

        if outcome.get("status") == "escalated":
            # cap breach: the head already filed the HITL escalation (US-EXE-04).
            await self._await_human(item, run_id, outcome.get("hitl_request_id"))
            return item
        if item.convergent and item.degraded:
            # D6: a convergent item whose aggregate is degraded is never DONE.
            await self._park(
                item, run_id,
                reason="convergent_degraded",
                detail="a convergent item's aggregate is degraded; it needs a human",
            )
            return item

        item.status = WorkStatus.DONE  # degraded=true is carried, never hidden
        await store.update_work_item(item)
        await store.upsert_checkpoint(
            tenant, run_id, "execute", "done",
            output={"spawned": outcome.get("spawned", 0), "degraded": item.degraded},
        )
        return item

    async def requeue(self, tenant_id: str, item_id: str) -> WorkItem | None:
        """Re-queue a parked (AWAITING_HUMAN / BLOCKED) item to PENDING.

        The pump-side half of the HITL answer loop: Beat 5 wires the HITL answer
        seam to call this; until then the console / an operator calls it. A
        human re-queue resets ``attempts`` - intervention restores the retry
        budget (US-EXE-06).
        """
        item = await self._store.get_work_item(tenant_id, item_id)
        if item is None or item.status not in (
            WorkStatus.AWAITING_HUMAN, WorkStatus.BLOCKED,
        ):
            return None
        item.status = WorkStatus.PENDING
        item.attempts = 0
        item.lease_owner = None
        item.lease_expires_at = None
        await self._store.update_work_item(item)
        return item

    # --- internals ------------------------------------------------------------
    async def _run_item_payload(self, payload: dict) -> None:
        """The one task body both lanes run: process a claimed item by id."""
        item = await self._store.get_work_item(payload["tenant_id"], payload["item_id"])
        if item is None:  # claimed then deleted; nothing to do
            return
        try:
            await self.handle_claimed_item(item)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # transient failure: retry or fail (US-EXE-06)
            await self._record_failure(item, exc)

    async def _record_failure(self, item: WorkItem, exc: Exception) -> None:
        """Retry while attempts < max_attempts, else FAILED with the error (US-EXE-06).

        ``attempts`` already incremented on claim, so re-queueing to PENDING is
        the whole retry: the next claim picks the item up and counts again.
        """
        run_id = item.hatchet_run_id or item.id
        will_retry = item.attempts < self.max_attempts
        if will_retry:
            item.status = WorkStatus.PENDING
            item.lease_owner = None
            item.lease_expires_at = None
        else:
            item.status = WorkStatus.FAILED
            item.result = {
                "error": type(exc).__name__,
                "detail": str(exc),
                "attempts": item.attempts,
            }
        await self._store.update_work_item(item)
        await self._store.upsert_checkpoint(
            item.tenant_id, run_id, "execute", "failed",
            output={"error": type(exc).__name__, "will_retry": will_retry},
        )

    def _head_for(self, department: str) -> Any:
        head = self.heads.get(department)
        if head is not None:
            return head
        if not self.heads:
            raise RuntimeError("no department heads configured")
        return self.heads[min(self.heads)]  # deterministic fallback head

    async def _context_for(self, item: WorkItem, run_id: str) -> InvocationContext:
        perms = await self._store.get_tenant_permissions(item.tenant_id)
        return InvocationContext(
            tenant_id=item.tenant_id,
            run_id=run_id,
            grants=perms.grants,
            actor="chief-of-staff",
            actor_tier="tier1",
            on_behalf_of=item.on_behalf_of,
        )

    async def _park(self, item: WorkItem, run_id: str, *, reason: str, detail: str) -> None:
        """File a HITL escalation and put the item in AWAITING_HUMAN (D6)."""
        request = await self._hitl.create(
            tenant_id=item.tenant_id,
            run_id=run_id,
            type=HITLType.ESCALATION,
            question=f"work item {item.id} needs a human ({reason}).",
            context=detail,
            urgency=Urgency.ASYNC,
            work_item_id=item.id,
        )
        await self._await_human(item, run_id, request.id)

    async def _await_human(
        self, item: WorkItem, run_id: str, hitl_request_id: str | None
    ) -> None:
        item.status = WorkStatus.AWAITING_HUMAN
        await self._store.update_work_item(item)
        await self._store.upsert_checkpoint(
            item.tenant_id, run_id, "execute", "awaiting_human",
            hitl_request_id=hitl_request_id,
        )


# --- the org factory ----------------------------------------------------------
def build_org(
    kernel: Any,
    spawner: Spawner | Any,
    manifest: FleetManifest | None = None,
    *,
    executor: Any = None,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
) -> WorkPump:
    """Build the live org (CoS + heads + pump) from the manifest hierarchy (P7).

    Each ``hierarchy.tier2`` entry becomes a routable Department and a
    DepartmentHead sharing the kernel's store (the fan-out CAS seam, US-EXE-07).
    Wildcard ``supported_skills`` patterns describe capabilities, not loadable
    skill ids, so only concrete entries become the head's ``domain_skills``.
    No hierarchy (or no manifest) degrades to a minimal default org - one CoS
    over one general head - never a crash (P9).
    """
    departments: list[Department] = []
    heads: dict[str, Any] = {}
    tiers = manifest.hierarchy.tier2 if manifest is not None else ()
    for tier in tiers:
        name = tier.department or tier.name
        skills = [s for s in tier.supported_skills if "*" not in s]
        departments.append(
            Department(name=name, domain_skills=skills, intent_keywords=[name])
        )
        heads[name] = DepartmentHead(
            name,
            skills,
            [],
            DEFAULT_SPAWN_BUDGET,
            spawner=spawner,
            store=kernel.store,
        )
    if not heads:  # P9: no hierarchy -> the minimal default org, never a crash
        departments = [Department(name="general")]
        heads["general"] = DepartmentHead(
            "general", [], [], DEFAULT_SPAWN_BUDGET,
            spawner=spawner, store=kernel.store,
        )
    chief = ChiefOfStaff(kernel, departments)
    return WorkPump(
        kernel, spawner, chief, heads, executor,
        max_attempts=max_attempts, lease_seconds=lease_seconds,
    )
