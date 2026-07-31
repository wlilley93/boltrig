"""The fleet worker process. Run with: python -m boltrig.api.worker

Builds the kernel, selects the durable executor (Hatchet in production, the
local fallback offline, US-EXE-05), builds the org from the manifest hierarchy
(Chief of Staff + department heads, P7), and runs the delegation pump: pending
work items are claimed, routed, decomposed, joined and completed (US-FLT-06).
No manifest hierarchy degrades to the minimal default org, never a crash (P9).
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from boltrig.addons import active_addons
from boltrig.config import load_manifest, load_settings
from boltrig.config.permanent_fleet import (
    effective_manifest_from_desired,
    record_permanent_fleet_startup_observation,
)
from boltrig.store import Store
from boltrig.fleet import (
    anchor_interval_from_env,
    build_org,
    build_spawner,
    register_workers,
    retention_days_from_manifest,
    retention_interval_from_env,
    run_anchor_forever,
    run_retention_forever,
)

from .bootstrap import (
    _DEFAULT_TENANT,
    _build_shared_codex_config,
    _find_manifest,
    _publish_birth_profile_startup,
    build_kernel_async,
)
from .codex_execution import build_codex_execution_stack
from .logging_config import configure_logging

configure_logging()
log = logging.getLogger("boltrig.worker")

# Resolve the configured addons at BOOT, exactly as the ASGI entrypoint does.
# BOTH processes need this, and for different reasons. The worker is where chat
# turns actually execute, so an unregistered name here would otherwise surface as
# every turn dying mid-run with its work item stranded IN_FLIGHT, rather than as a
# process that refuses to start. And because the pinned kernel-tools birth profile
# is COMPOSED from the active addons at import, a worker whose environment differs
# from the kernel's would compile a different profile version than the kernel
# attests - the exact drift this seam claims cannot happen. Resolving in both
# places makes a mismatch loud on startup instead of silent at attestation.
_ADDONS = active_addons()
log.info("addons active: %s", ", ".join(f"{a.name}/{a.version}" for a in _ADDONS) or "(none)")

_POLL_SECONDS = 5.0


def _start_hitl_expiry_janitor(
    store: Store,
    process_instance_identity: str | None = None,
) -> "asyncio.Task[None] | None":
    """Start the HITL expiry janitor (SEC-14), or None when disabled.

    On an interval the janitor transitions every overdue PENDING request to
    TIMED_OUT and settles its parked work item, so a request raised by a
    crashed run never sits actionable forever. Same worker-side loop shape as
    the anchor janitor - store-only, engine-independent, never crashes boot
    (P9). Off when BOLTRIG_HITL_EXPIRY_INTERVAL is <= 0; one-minute default
    (the lazy 409 layer already fails overdue answers closed, so this is
    hygiene). Held in a name so the task is not garbage-collected mid-flight.
    """
    from boltrig.kernel.hitl_expiry import (
        hitl_expiry_interval_from_env,
        run_hitl_expiry_forever,
    )

    interval = hitl_expiry_interval_from_env()
    if interval <= 0:
        log.info("hitl-expiry janitor disabled (interval<=0)")
        return None
    log.info("hitl-expiry janitor live (interval=%ss)", interval)
    return asyncio.create_task(
        run_hitl_expiry_forever(
            store,
            interval=interval,
            process_instance_identity=process_instance_identity,
        ),
        name="hitl-expiry-janitor",
    )


def _start_anchor_janitor(store: Store, anchorer: Any) -> "asyncio.Task[None] | None":
    """Start the audit-rollup anchor janitor (COUNTY 9 D4), or None when disabled.

    On an interval it seals every tenant's un-anchored audit-chain tail so a
    verifier can prove a segment was not rewritten. A worker-side loop (there is
    no native Hatchet cron seam), independent of the durable engine so it runs the
    same on Hatchet or the local fallback, and it never crashes boot (P9). Off
    when BOLTRIG_AUDIT_ANCHOR_INTERVAL is <= 0; conservative daily default. Held
    in a name so the task is not garbage-collected mid-flight."""
    interval = anchor_interval_from_env()
    if interval <= 0:
        log.info("audit-anchor janitor disabled (interval<=0)")
        return None
    log.info("audit-anchor janitor live (interval=%ss)", interval)
    return asyncio.create_task(
        run_anchor_forever(store, anchorer, interval=interval),
        name="audit-anchor-janitor",
    )


def _start_retention_janitor(
    store: Store,
    tenant: str,
    manifest: Any,
    process_instance_identity: str | None = None,
) -> "asyncio.Task[None] | None":
    """Start the retention janitor (M11 / SEC-74), or None when disabled.

    It belongs here because for as long as it existed it belonged NOWHERE. Its own
    docstring told the reader to schedule it with a cron or a small entrypoint, and
    nothing ever did: no compose service, no Makefile target, no deploy unit, no
    ``__main__``. So ``purge_closed_conversations`` had never once run in a
    deployment, while docs/security-conformance.md recorded DATA-07 and PRIV-04 as
    BUILT and SEC-74 claimed a deleted conversation no longer sat in Postgres
    indefinitely. A DELETE soft-closes the thread; without this loop the body and
    every message stay there for good.

    Same shape as the anchor and HITL-expiry janitors: store-only,
    engine-independent, never crashes boot (P9). Off when
    BOLTRIG_RETENTION_INTERVAL is <= 0 - and the worker says which it did, so
    "off" is a decision on the record rather than the silence it used to be."""
    interval = retention_interval_from_env()
    if interval <= 0:
        log.info("retention janitor disabled (interval<=0)")
        return None
    days = retention_days_from_manifest(manifest)
    log.info(
        "retention janitor live (tenant=%s, window=%sd, interval=%ss)",
        tenant,
        days,
        interval,
    )
    return asyncio.create_task(
        run_retention_forever(
            store,
            tenant,
            days,
            interval=interval,
            process_instance_identity=process_instance_identity,
        ),
        name="retention-janitor",
    )


def _start_session_distillation(
    kernel: Any, tenant: str, manifest: Any
) -> "asyncio.Task[None] | None":
    """Start the on_session_end distillation sweep, or None when the manifest is off.

    Same reason this sits beside the retention janitor: the flag
    ``memory.ingest.on_session_end`` had shipped in manifest.example.yaml and been
    offered as an admin-console toggle while NOTHING read it. An operator who
    turned it on believed conversations were being distilled into memory; none
    were. A switch for behaviour that does not exist is worse than no switch.

    Off unless the manifest asks for it, and the worker SAYS which - so "off" is a
    decision on the record rather than the silence it used to be.
    """
    from boltrig.memory.session_distillation import (
        distillation_context,
        policy_from_manifest,
        run_distillation_forever,
    )

    policy = policy_from_manifest(getattr(manifest, "extra", None))
    if not policy.enabled:
        log.info("session distillation disabled (memory.ingest.on_session_end)")
        return None
    log.info(
        "session distillation live (tenant=%s, idle=%smin)", tenant, policy.idle_minutes
    )
    return asyncio.create_task(
        run_distillation_forever(
            kernel, tenant, policy, lambda user_id: distillation_context(tenant, user_id)
        ),
        name="session-distillation",
    )




def _start_workflow_scheduler(
    kernel: Any, tenant: str, executor: Any
) -> "asyncio.Task[None] | None":
    """Start the store-backed cron reconciler used by every executor mode."""

    from boltrig.workflows import WorkflowLibrary
    from boltrig.workflows.scheduler import scheduler_interval_from_env
    from boltrig.workflows.scheduler_loop import run_workflow_scheduler_forever

    interval = scheduler_interval_from_env()
    if interval <= 0:
        log.info("workflow scheduler disabled (interval<=0)")
        return None
    workflows = WorkflowLibrary(kernel.store, executor=executor, kernel=kernel)
    log.info(
        "workflow scheduler started (tenant=%s, interval=%ss, durable=%s)",
        tenant,
        interval,
        bool(getattr(executor, "durable", False)),
    )
    return asyncio.create_task(
        run_workflow_scheduler_forever(
            kernel.store,
            tenant,
            workflows,
            executor=executor,
            interval=interval,
        ),
        name="workflow-scheduler",
    )


async def _manifest_spawn_context(
    kernel: Any,
    *,
    codex_config: dict[str, object] | None,
    manifest_snapshot: Any,
) -> tuple[Any, str, Any, bool]:
    """Overlay one process-owned manifest and compose its policy-aware spawner."""

    manifest = manifest_snapshot
    desired_overlay_applied = False
    if manifest is not None:
        try:
            manifest = await effective_manifest_from_desired(kernel.store, manifest)
            desired_overlay_applied = True
        except Exception as exc:
            log.warning("manifest load failed (%s); using the default org", exc)
            manifest = None
    tenant = manifest.tenant_id if manifest is not None else _DEFAULT_TENANT
    spawner = (
        build_spawner(
            kernel,
            codex_config=codex_config,
            sensitive_endpoint_id=manifest.models.sensitive_endpoint,
            spawn_rules=manifest.spawn_rules,
        )
        if manifest is not None
        else build_spawner(
            kernel,
            codex_config=codex_config,
            sensitive_endpoint_id=None,
        )
    )
    return manifest, tenant, spawner, desired_overlay_applied


def _start_background_tasks(
    kernel: Any,
    tenant: str,
    manifest: Any,
    executor: Any,
) -> tuple["asyncio.Task[None] | None", ...]:
    """Start fleet-owned loops under one opaque per-boot process identity."""
    stack_health_task: asyncio.Task[None] | None = None
    if str(os.environ.get("REDIS_URL") or "").strip():
        from boltrig.fleet.stack_tool_health import run_fleet_tool_heartbeat

        stack_health_task = asyncio.create_task(
            run_fleet_tool_heartbeat(tenant),
            name="fleet-stack-tool-heartbeat",
        )
        log.info("fleet stack-tool heartbeat started (tenant=%s)", tenant)
    else:
        log.info("fleet stack-tool heartbeat not started (REDIS_URL not configured)")

    from boltrig.observability.background_jobs import new_background_process_identity

    process_identity = new_background_process_identity()
    return (
        _start_anchor_janitor(kernel.store, kernel.anchorer),
        _start_hitl_expiry_janitor(kernel.store, process_identity),
        stack_health_task,
        _start_retention_janitor(kernel.store, tenant, manifest, process_identity),
        _start_workflow_scheduler(kernel, tenant, executor),
        _start_session_distillation(kernel, tenant, manifest),
    )


async def _stop_background_tasks(
    tasks: tuple["asyncio.Task[None] | None", ...],
) -> None:
    pending = [task for task in tasks if task is not None]
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


async def _run() -> None:
    # Build the trusted provider once for this process and inject that exact
    # instance into both kernel-bound and pump-bound fleet spawners. None is off.
    codex_config = _build_shared_codex_config()
    manifest_path = _find_manifest()
    manifest_snapshot = load_manifest(manifest_path) if manifest_path else None
    sensitive_endpoint_id = (
        manifest_snapshot.models.sensitive_endpoint if manifest_snapshot is not None else None
    )
    kernel = await build_kernel_async(
        codex_config=codex_config,
        sensitive_endpoint_id=sensitive_endpoint_id,
        manifest_snapshot=manifest_snapshot,
        manifest_path=manifest_path,
    )  # async build (no nested asyncio.run)
    executor = register_workers(kernel)
    # Honest executor selection (US-EXE-05): the boot record states durability.
    log.info(
        "fleet worker started (%s, durable=%s)",
        type(executor).__name__,
        executor.durable,
    )
    # The org from the manifest hierarchy; a missing/broken manifest degrades to
    # the minimal default org (one CoS over one general head, P9).
    manifest, tenant, spawner, desired_overlay_applied = await _manifest_spawn_context(
        kernel,
        codex_config=codex_config,
        manifest_snapshot=manifest_snapshot,
    )
    pump = build_org(
        kernel,
        spawner,
        manifest,
        executor=executor,
        # Codex shadow root admission (SEC-172), built here at the composition
        # root: None when BOLTRIG_CODEX_LEDGER is off => no admit.
        codex_execution=build_codex_execution_stack(load_settings(), kernel.store),
    )
    await _publish_birth_profile_startup(
        kernel,
        process_kind="fleet",
        manifest=manifest,
        addons_snapshot=_ADDONS,
        codex_config=codex_config,
        sensitive_endpoint_id=(
            manifest.models.sensitive_endpoint if manifest is not None else None
        ),
    )
    if desired_overlay_applied:
        await record_permanent_fleet_startup_observation(
            kernel.store,
            tenant,
            os.environ.get("HOSTNAME") or "fleet-worker",
        )
    log.info(
        "delegation pump live (tenant=%s, departments=%s)",
        tenant,
        sorted(pump.heads),
    )
    tasks = _start_background_tasks(kernel, tenant, manifest, executor)
    try:
        await pump.run_forever(tenant, interval=_POLL_SECONDS)
    finally:
        await _stop_background_tasks(tasks)
        close = getattr(kernel, "aclose", None)
        if close is not None:
            await close()


def main() -> None:
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        log.info("fleet worker stopping")


if __name__ == "__main__":
    main()
