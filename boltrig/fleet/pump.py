"""The delegation pump: the org goes live (Beat 4; US-FLT-06, US-EXE-06).

The pump is the serving loop that makes the permanent tier real: it claims a PENDING
work item from the store (the Beat 3 lease, US-FLT-05), asks the Chief of Staff to route
it, hands it to the routed Department Head to decompose and fan out, joins the children
onto the parent, and walks the item's status. It retries transient failures up to a cap
(US-EXE-06) and parks BLOCKED / cap-breach / convergent-degraded work for a human (D6)
instead of pretending it is done.

Two-lane policy (D5): chat keeps its DIRECT-SPAWN fast lane so an interactive turn never
waits on a queue; delegated work - channel intake, filed items, and a chat turn's
``new_work_items`` follow-ons - flows through the pump. The lanes share the spawner, the
caps, and the audit trail; only the entry differs.

Execution rides the durable seam (US-EXE-02/05): under a durable executor the claimed
item is enqueued as the registered ``boltrig-work-item`` task; offline the same body runs
directly. One body, two carriages.
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from typing import TYPE_CHECKING, Any

from boltrig.models import (
    ActionType,
    AuditEvent,
    HITLType,
    InvocationContext,
    Urgency,
    WorkflowSource,
    WorkItem,
    WorkStatus,
    utcnow,
)
from boltrig.work import normalise
from boltrig.workflows.generator import learn_from_success

from .authority import context_for, reflection_context, route_to_head
from .chief_of_staff import ChiefOfStaff, Department
from .department_head import DepartmentHead, tree_root_id

if TYPE_CHECKING:  # type-only seams (fleet imports stay kernel-free)
    from boltrig.api.codex_execution import CodexExecutionStack
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

# The key under which a step's outcome may carry a synthesised workflow to learn
# from (Phase 3, US-WFL-03): today the pump learns from any outcome that already
# carries a GENERATED definition (proven by the wiring test).
GENERATED_WORKFLOW_KEY = "generated_workflow"


def outcome_score(terminal_status: str, degraded: bool) -> dict[str, Any]:
    """A deterministic outcome score for a terminal work item (Phase 3, US-WFL-06).

    DONE + not degraded is a clean success (1.0); DONE + degraded is a half win
    (0.5); FAILED is 0.0; anything else (AWAITING_HUMAN, CANCELLED) is neutral
    (``None``) - not a success and not a failure ([2026] VJS-COUNTY 6, D1). The
    sub-dict is stashed on ``WorkItem.result['outcome']`` (JSONB); a first-class
    column is a follow-on (it needs a schema change to persist).
    """
    if terminal_status == WorkStatus.DONE.value:
        score: float | None = 0.5 if degraded else 1.0
    elif terminal_status == WorkStatus.FAILED.value:
        score = 0.0
    else:
        score = None  # AWAITING_HUMAN / CANCELLED / any other non-success: neutral
    return {
        "score": score,
        "terminal_status": terminal_status,
        "degraded": bool(degraded),
    }


def reflection_lesson(item: WorkItem, terminal_status: str, outcome: dict) -> str:
    """A short, deterministic lesson distilled from an outcome (Phase 3, US-WFL-07).

    Deliberately a fixed template, not a model call, so reflection is cheap and
    reproducible. The content is bland by construction so it clears the memory
    adapter's secret / injection screen, and it is stored THROUGH the chokepoint,
    so that screen still runs on it (it is never bypassed)."""
    score = outcome.get("score")
    return (
        f"Lesson from work item {item.id} ({item.source}): the task "
        f"'{item.intent}' reached {terminal_status} with outcome score {score} "
        f"(degraded={bool(item.degraded)})."
    )


async def persist_new_work_items(
    store: Any, parent: WorkItem, new_items: list[Any] | None, *, source: str
) -> list[WorkItem]:
    """Persist a step's discovered follow-on work as PENDING children (D7).

    Each entry becomes a normalised PENDING :class:`WorkItem` parented to the step's item
    (owner/department unset - the org lane routes it), so the pump picks it up on a later
    cycle instead of the follow-on being dropped."""
    created: list[WorkItem] = []
    for raw in new_items or []:
        payload = dict(raw) if isinstance(raw, dict) else {"intent": str(raw)}
        child = normalise(payload, source, parent.tenant_id)
        child.parent_id = parent.id
        child.depth = parent.depth + 1
        child.on_behalf_of, child.workspace_id = parent.on_behalf_of, parent.workspace_id
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
        reflect: bool | None = None,
        codex_execution: CodexExecutionStack | None = None,
    ) -> None:
        self._store = getattr(kernel_or_store, "store", kernel_or_store)
        # Post-run reflection (Phase 3, US-WFL-07) goes through the kernel chokepoint,
        # so it needs the kernel, not just its store. A bare store has no ``invoke``:
        # reflection is then simply unavailable (P9).
        self._kernel = kernel_or_store if hasattr(kernel_or_store, "invoke") else None
        # OFF by default: deterministic (no model call) but still a governed write per
        # item, so it must be asked for. ``reflect=True`` overrides the env for tests.
        self._reflect_enabled = (
            reflect if reflect is not None else os.getenv("BOLTRIG_REFLECT") == "1"
        )
        hitl = getattr(kernel_or_store, "hitl", None)
        if hitl is None:  # bare store: build the manager lazily (no kernel import cost)
            from boltrig.kernel.hitl import HITLManager

            hitl = HITLManager(self._store)
        self._hitl = hitl
        # A cancel transition emits one audit row ([2026] VJS-COUNTY 6, D4). Prefer the
        # kernel's shared writer (one hash chain); a bare store builds one lazily,
        # mirroring the HITL manager above.
        audit = getattr(kernel_or_store, "audit", None)
        if audit is None:
            from boltrig.kernel.audit import AuditWriter

            audit = AuditWriter(self._store)
        self._audit = audit
        self._spawner = spawner
        self._cos = chief_of_staff
        self.heads = dict(heads)
        self._executor = executor
        self.max_attempts = max_attempts
        self.lease_seconds = lease_seconds
        self.worker_id = worker_id or f"pump-{uuid.uuid4().hex[:8]}"
        self._codex_execution = codex_execution  # SEC-172 shadow root admission; None=off
        # One body, two carriages (US-EXE-05): the durable engine and the direct path
        # both run _run_item_payload; registering it lets a durable executor enqueue
        # it by name.
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
        # Shadow Codex root admission (SEC-172): a ROOT (parent_id is None) records one
        # execution-neutral decision; None=off => no-op, fail-open. Replay-safe (insert-once).
        if self._codex_execution is not None and item.parent_id is None:
            await self._codex_execution.shadow_admit(item.tenant_id, item.workspace_id, item.id)

        if item.status == WorkStatus.BLOCKED:  # blocked work is a human's, not a retry's
            await self._park(
                item, run_id, reason="blocked",
                detail="the item is blocked; a human must unblock or re-queue it",
            )
            return item

        # Cooperative server-side cancel ([2026] VJS-COUNTY 6, D3/D4): consulted at every step
        # boundary; CANCELLED is written in the `finally`, durable even if a later step raises.
        cancelled = await self._store.is_run_cancel_requested(tenant, run_id)
        try:
            if cancelled:  # boundary 0: before any dispatch, nothing has run yet
                return item

            ctx = await self._context_for(item, run_id)
            head = await route_to_head(self._cos, self.heads, store, item, run_id, ctx)
            if head is None:  # SEC-165: unroutable parks; it never mis-routes
                await self._park(
                    item, run_id, reason="unroutable_department",
                    detail="the routed department has no head; a human must route it",
                )
                return item

            # boundary 1: the chokepoint before dispatching the execute verb. If a
            # cancel arrived while routing, head.handle (the dispatch) never runs.
            cancelled = await self._store.is_run_cancel_requested(tenant, run_id)
            if cancelled:
                return item
            ctx = await self._context_for(item, run_id)
            await store.upsert_checkpoint(tenant, run_id, "execute", "started")
            tree_id = await tree_root_id(store, item)
            # In-flight adapter call: a cancel requested DURING this never interrupts
            # it - it runs to completion and cancellation takes effect (if any) only
            # at the next cooperative point (D3, FORBIDDEN: no mid-step hard kill).
            outcome = await head.handle(item, ctx, tree_id=tree_id)

            # Join the step onto the parent: the aggregate is the item's result and
            # the degraded flag is any child's degradation (US-FLT-07). The completed
            # step's own record is kept even under a cancel - it really ran (SEC-166).
            children = list(outcome.get("children") or [])
            item.result = outcome
            item.degraded = any(bool(c.get("degraded")) for c in children)

            # boundary 2 (SEC-166): the next cooperative point AFTER the step. The step was
            # never interrupted; re-reading here is what stops a cancel going unseen for the
            # whole of its duration, so no DOWNSTREAM effect BEGINS - no follow-on work
            # items, no learning - and the `finally` settles the refreshed marker.
            cancelled = await self._store.is_run_cancel_requested(tenant, run_id)
            if cancelled:
                return item

            await persist_new_work_items(
                store, item, outcome.get("new_work_items"), source="internal"
            )
            return await self._settle(item, run_id, outcome)
        finally:
            if cancelled:
                await self._cancel(item, run_id)

    async def _settle(self, item: WorkItem, run_id: str, outcome: dict) -> WorkItem:
        """Walk a joined, uncancelled item to its terminal state (US-FLT-06, D6)."""
        if outcome.get("status") == "escalated":
            # cap breach: the head already filed the HITL escalation (US-EXE-04).
            await self._await_human(item, run_id, outcome.get("hitl_request_id"))
            return item
        if item.convergent and item.degraded:
            # D6: a convergent item whose aggregate is degraded is never DONE.
            await self._park(
                item, run_id, reason="convergent_degraded",
                detail="a convergent item's aggregate is degraded; it needs a human",
            )
            return item

        item.status = WorkStatus.DONE  # degraded=true is carried, never hidden
        self._stamp_outcome(item, WorkStatus.DONE.value)
        # flywheel: a clean success that carries a synthesised workflow is learned
        # so the library can reuse it next time (US-WFL-03).
        await self._maybe_learn(item, outcome)
        await self._store.update_work_item(item)
        await self._store.upsert_checkpoint(
            item.tenant_id, run_id, "execute", "done",
            output={"spawned": outcome.get("spawned", 0), "degraded": item.degraded},
        )
        await self._reflect(item, run_id, WorkStatus.DONE.value)
        return item

    async def requeue(self, tenant_id: str, item_id: str) -> WorkItem | None:
        """Re-queue a parked (AWAITING_HUMAN / BLOCKED) item to PENDING.

        The pump-side half of the HITL answer loop: the answer bridge
        (``bootstrap.wire_hitl_resume``) calls this on a HITL answer; the console or an
        operator may also call it directly. A human re-queue resets ``attempts`` -
        intervention restores the retry budget (US-EXE-06).
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

        ``attempts`` already incremented on claim, so re-queueing to PENDING is the whole
        retry: the next claim picks the item up and counts again.
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
            self._stamp_outcome(item, WorkStatus.FAILED.value)
        await self._store.update_work_item(item)
        await self._store.upsert_checkpoint(
            item.tenant_id, run_id, "execute", "failed",
            output={"error": type(exc).__name__, "will_retry": will_retry},
        )
        if not will_retry:  # reflect only on the terminal failure, not each retry
            await self._reflect(item, run_id, WorkStatus.FAILED.value)

    async def _context_for(self, item: WorkItem, run_id: str) -> InvocationContext:
        """The item's execution context, capped to the requesting principal (SEC-164)."""
        return await context_for(self._store, item, run_id)

    async def _park(self, item: WorkItem, run_id: str, *, reason: str, detail: str) -> None:
        """File a HITL escalation and put the item in AWAITING_HUMAN (D6)."""
        request = await self._hitl.create(
            tenant_id=item.tenant_id,
            run_id=run_id,
            type=HITLType.ESCALATION,
            question=f"work item {item.id} needs a human ({reason}).",
            context=detail,
            urgency=Urgency.ASYNC,
            work_item_id=item.id, requested_by="chief-of-staff", requested_on_behalf_of=item.on_behalf_of, workspace_id=item.workspace_id, department_scope=[item.owner_member] if item.owner_member else None,
        )
        await self._await_human(item, run_id, request.id)

    async def _await_human(
        self, item: WorkItem, run_id: str, hitl_request_id: str | None
    ) -> None:
        item.status = WorkStatus.AWAITING_HUMAN
        self._stamp_outcome(item, WorkStatus.AWAITING_HUMAN.value)
        await self._store.update_work_item(item)
        await self._store.upsert_checkpoint(
            item.tenant_id, run_id, "execute", "awaiting_human",
            hitl_request_id=hitl_request_id,
        )
        await self._reflect(item, run_id, WorkStatus.AWAITING_HUMAN.value)

    async def _cancel(self, item: WorkItem, run_id: str) -> None:
        """Durably record a cooperative cancel ([2026] VJS-COUNTY 6, D1/D4).

        Writes the terminal ``WorkStatus.CANCELLED`` (a neutral outcome), persists a
        checkpoint, and emits one audit row on the transition. Called only from
        ``handle_claimed_item``'s ``finally`` so the terminal state is durable even if a
        later step raised; ``_stamp_outcome`` preserves the head's aggregate (SEC-166).
        Idempotent: re-running it re-writes the same terminal state, so a restart that
        re-detects the cancel-request row never resurrects the run."""
        item.status = WorkStatus.CANCELLED
        item.lease_owner = None
        item.lease_expires_at = None
        self._stamp_outcome(item, WorkStatus.CANCELLED.value)
        await self._store.update_work_item(item)
        await self._store.upsert_checkpoint(
            item.tenant_id, run_id, "execute", "cancelled"
        )
        # D4: one audit row marks the transition. Best-effort chain via the shared
        # writer; keys only (no intent/content), matching the bounded-observability
        # rule (K-20).
        await self._audit.write(
            AuditEvent(
                tenant_id=item.tenant_id, ts=utcnow(), actor=self.worker_id,
                actor_tier="tier1", action_type=ActionType.TOOL_CALL,
                status="cancelled", run_id=run_id, verb="work.cancel",
                on_behalf_of=item.on_behalf_of, workspace_id=item.workspace_id,
                detail={"work_item_id": item.id, "reason": "cancel_requested"},
            )
        )
        await self._reflect(item, run_id, WorkStatus.CANCELLED.value)

    # --- learning loop (Phase 3, US-WFL-03/06/07) ---------------------------------
    def _stamp_outcome(self, item: WorkItem, terminal_status: str) -> None:
        """Record the deterministic outcome score on the item's result (US-WFL-06).

        Stashed in the existing ``result`` JSONB dict (which round-trips) under an
        ``outcome`` sub-dict; the head's aggregate result (children/spawned) is preserved,
        which is what keeps a completed step's record under a cancel (SEC-166)."""
        item.result = dict(item.result or {})
        item.result["outcome"] = outcome_score(terminal_status, item.degraded)

    async def _maybe_learn(self, item: WorkItem, outcome: dict) -> None:
        """Re-save a succeeded, synthesised workflow as learned (US-WFL-03).

        Only a clean (non-degraded) success whose outcome carries a GENERATED definition
        is learned; a precreated/already-learned or degraded run is a no-op, so existing
        completions are unaffected. Best-effort: a learn failure never fails the item (P9).
        Never reached on a cancelled run - the flywheel is downstream of boundary 2."""
        if item.degraded:
            return
        wf = outcome.get(GENERATED_WORKFLOW_KEY)
        if wf is None or getattr(wf, "source", None) != WorkflowSource.GENERATED:
            return
        try:
            await learn_from_success(self._store, wf, item.intent)
        except asyncio.CancelledError:
            raise
        except Exception:  # learning is best-effort; never fail the run (P9)
            log.debug("learn_from_success failed for %s; continuing", item.id,
                      exc_info=True)

    async def _reflect(self, item: WorkItem, run_id: str, terminal_status: str) -> None:
        """Distil one lesson and store it via the memory verb, best-effort (US-WFL-07).

        Governed: the write goes through ``kernel.invoke`` (the one chokepoint), so the
        memory adapter's scope + secret + injection screens all run on it. Provenance is the
        run id (``source_ref``) and work item id. OFF unless enabled, and any reflection
        failure is swallowed so it can never fail the run (P9). Carries the narrow reflection
        seat, NOT the item's execution context (``authority.REFLECTION_GRANTS``)."""
        if not self._reflect_enabled or self._kernel is None:
            return
        outcome = (item.result or {}).get("outcome") or {}
        lesson = reflection_lesson(item, terminal_status, outcome)
        try:
            ctx = reflection_context(item, run_id)
            await self._kernel.invoke(
                "memory", "memory.remember",
                {
                    "content": lesson,
                    "kind": "lesson",
                    "source_kind": "reflection",
                    "source_ref": run_id,
                },
                ctx,
            )
        except asyncio.CancelledError:
            raise
        except Exception:  # reflection is best-effort; never fail the run (P9)
            log.debug("reflection failed for %s; continuing", item.id, exc_info=True)


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

    Each ``hierarchy.tier2`` entry becomes a routable Department and a DepartmentHead
    sharing the kernel's store (the fan-out CAS seam, US-EXE-07). Wildcard
    ``supported_skills`` patterns describe capabilities, not loadable skill ids, so only
    concrete entries become the head's ``domain_skills``. No hierarchy (or no manifest)
    degrades to a minimal default org - one CoS over one general head - never a crash (P9).
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
    # Codex shadow root admission (SEC-172) at the construction site: off => None => no admit.
    from boltrig.api.codex_execution import build_codex_execution_stack
    from boltrig.config import load_settings
    return WorkPump(
        kernel, spawner, chief, heads, executor,
        max_attempts=max_attempts, lease_seconds=lease_seconds,
        codex_execution=build_codex_execution_stack(load_settings(), kernel.store),
    )
