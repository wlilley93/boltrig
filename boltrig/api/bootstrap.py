"""Compose a running Kernel + fleet from settings and the manifest (P7).

This is the single wiring point. The store is an in-memory store by default;
a Postgres-backed store implementing the same ``Store`` protocol is the
documented swap point for durable deployments (see schema.sql). Swapping it
changes nothing else here, which is the whole point of the Store seam.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from boltrig.api.birth_profile_startup import (
    publish_birth_profile_startup as _publish_birth_profile_startup_impl,
)
from boltrig.api.agent_tool_bootstrap import register_agent_support
from boltrig.api.device_bootstrap import register_device_actions
from boltrig.api.camera_bootstrap import register_camera_actions
from boltrig.api.hitl_resume_bridge import resume_held_write_route
from boltrig.config import apply_manifest, load_manifest, load_settings, production_signal

# Re-exported: the guards moved to boot_guards.py, and several tests monkeypatch
# them THROUGH this module (`monkeypatch.setattr(bootstrap, ...)`). `X as X` is
# required - mypy disallows implicit re-export, so a plain import is private here
# and every caller fails typecheck.
from .boot_guards import (  # noqa: F401
    refuse_default_audit_key_in_prod as refuse_default_audit_key_in_prod,
    refuse_dev_auth_in_prod as refuse_dev_auth_in_prod,
)
from boltrig.config.environment import is_truthy
from boltrig.config.integration_catalogue import (
    provision_builtin_integration_catalogue,
)
from boltrig.fleet import make_agent_invoker, make_app_spawner
from boltrig.knowledge import register_knowledge
from boltrig.kernel import Kernel
from boltrig.kernel.events import build_event_relay
from boltrig.kernel.ratelimit import build_counter
from boltrig.distill.bootstrap import register_distill
from boltrig.memory.bootstrap import register_memory as _register_memory
from boltrig.store import InMemoryStore, Store

log = logging.getLogger("boltrig.bootstrap")

_DEFAULT_TENANT = "default"
_MANIFEST_CANDIDATES = (
    "/app/manifest.yaml",
    "manifest.yaml",
    "manifest.example.yaml",
)
_MANIFEST_UNSET = object()


def _find_manifest() -> str | None:
    """Locate the manifest, reading ``BOLTRIG_MANIFEST`` LIVE (not at import time)
    so it is honoured even when set after import (tests / dynamic config), then
    falling back to the well-known paths."""
    return _find((os.environ.get("BOLTRIG_MANIFEST", ""), *_MANIFEST_CANDIDATES))


_SKILLS_DIR_CANDIDATES = ("/app/libraries/skills", "libraries/skills")


def _find(paths) -> str | None:
    for p in paths:
        if p and os.path.exists(p):
            return p
    return None


def _wire_memory_projection_executor(kernel: Kernel, tenant_id: str, executor) -> None:
    from boltrig.fleet.hatchet_memory import TASK_MEMORY_PROJECTION

    adapter = kernel.loader.peek(tenant_id, "memory")
    fanout = getattr(adapter, "_projections", None)
    register = getattr(fanout, "register_executor", None)
    if callable(register):
        register(executor, task_name=TASK_MEMORY_PROJECTION)
        log.info("memory projection fanout registered with workflow executor")


async def build_store() -> Store:
    """The store factory (the §6 seam). Returns a durable PostgresStore when
    DATABASE_URL is set, else the in-memory store (so offline tests still run).
    Swapping the store changes nothing else in the system (P1, NFR-MNT)."""
    settings = load_settings()
    if settings.database_url:
        from boltrig.store import PostgresStore

        # Runtime boot never applies the mutable convenience bootstrap. Alembic is
        # the authoritative upgrade path; schema.sql is reserved for an explicit
        # first-boot bootstrap (for example Postgres' initdb mount). This is true
        # with or without RLS, otherwise a non-RLS production process could bypass
        # migration ordering merely by restarting.
        rls = is_truthy(os.environ.get("BOLTRIG_RLS"))
        log.info("DATABASE_URL set; using durable PostgresStore (rls=%s)", rls)
        return await PostgresStore.connect(settings.database_url, apply_schema=False, rls=rls)
    return InMemoryStore()


async def _seed_default(kernel: Kernel, *, model_catalogue: Any = None) -> None:
    """Seed a minimal, offline-safe demo tenant when no manifest is present."""
    from boltrig.adapters.builtin.familiar import build as build_familiar
    from boltrig.adapters.builtin.memory_tickets import build as build_tickets
    from boltrig.models import GrantSet, TenantPermissions

    import inspect

    res = kernel.store.set_tenant_permissions(  # type: ignore[attr-defined]
        TenantPermissions(_DEFAULT_TENANT, GrantSet.of(["*"]))
    )
    if inspect.isawaitable(res):  # PostgresStore seed helper is async
        await res
    await provision_builtin_integration_catalogue(kernel.store, _DEFAULT_TENANT)
    await kernel.register_adapter(_DEFAULT_TENANT, build_tickets())
    await kernel.register_adapter(_DEFAULT_TENANT, build_familiar())  # familiar.express (WL-3)
    if _desktop_hands_enabled():
        await _register_desktop_hands(kernel, _DEFAULT_TENANT)
    await _register_control_plane(kernel, _DEFAULT_TENANT, model_catalogue=model_catalogue)
    await _register_web_fetch(kernel, _DEFAULT_TENANT, {})
    await register_agent_support(kernel, _DEFAULT_TENANT)
    await _register_channel_send(kernel, _DEFAULT_TENANT)
    await register_device_actions(kernel, _DEFAULT_TENANT)
    await register_camera_actions(kernel, _DEFAULT_TENANT)
    # Keep knowledge opt-in while preserving the demo tenant's vault.
    await register_knowledge(kernel, _DEFAULT_TENANT, {"enabled": True})


def _desktop_hands_enabled() -> bool:
    """The desktop-hands add-on is OPT-IN (decision 0016, DH-1): the governed desktop.* verbs
    and the /v1/hands pull surface exist only when the operator turns the add-on on
    (BOLTRIG_DESKTOP_HANDS=1) AND installs the host executor. Default OFF: a kernel that does
    not drive a desktop must not even advertise the capability."""
    return is_truthy(os.environ.get("BOLTRIG_DESKTOP_HANDS"))


async def _register_desktop_hands(kernel: Kernel, tenant_id: str) -> None:
    """Register governed desktop hands through the ordinary chokepoint.
    The handler queues work for the host executor; registration grants no authority."""
    from boltrig.adapters.builtin.desktop import build as build_desktop

    await kernel.register_adapter(tenant_id, build_desktop(kernel.hands_registry))
    log.info("desktop hands verbs registered (governed host window control)")


async def _register_control_plane(
    kernel: Kernel, tenant_id: str, *, model_catalogue: Any = None
) -> None:
    """Register config amendment through the governed control-plane chokepoint.

    Loader and registry are injected here; runtime collaborators bind later.
    """
    from boltrig.config.control_plane import build_control_plane_adapter

    await kernel.register_adapter(
        tenant_id,
        build_control_plane_adapter(
            kernel.store,
            loader=kernel.loader,
            registry=kernel.registry,
            credentials=kernel.credentials,  # MCP bearers bind to the seam (SEC-04/05)
            model_catalogue=model_catalogue,
        ),
    )
    log.info("control-plane verbs registered (governed config amendment)")


async def _register_web_fetch(kernel: Kernel, tenant_id: str, network_cfg) -> None:
    """Register the governed internet-access verb (Round Eight, S4). web.fetch runs
    the chokepoint like any verb; registering it does NOT grant it (the tenant
    ceiling + caller grants still decide). It enforces NetworkConfig + the SSRF
    guard (SEC-52)."""
    from boltrig.adapters.builtin.web_fetch import build_web_fetch_adapter

    await kernel.register_adapter(tenant_id, build_web_fetch_adapter(network_cfg or {}))
    log.info("web.fetch verb registered (governed internet access, SSRF-guarded)")


async def _register_channel_send(kernel: Kernel, tenant_id: str, manifest=None) -> None:
    """Register the governed outbound channel verb (decision 0003). channel.send
    runs the chokepoint like any verb: consequence=high (HITL by default, SEC-39),
    grant-checked, audited; the kernel executes the outbound send directly. A
    registration with no manifest gets no diversion resolver, so the demo tenant
    and every bare boot send normally (``announced_diversion_fn``). The
    manifest's network posture rides the adapter (SEC-52): the outbound webhook
    leg is ordinary egress and honours the operator's air-gap / allow-list."""
    from boltrig.adapters.builtin.channel_send import build_channel_send
    from boltrig.kernel.dev_egress_runtime import announced_diversion_fn

    diversion = announced_diversion_fn(manifest)
    network_cfg = manifest.network.as_egress_config() if manifest is not None else None
    await kernel.register_adapter(
        tenant_id,
        build_channel_send(
            kernel.store, diversion=diversion, network_config=network_cfg
        ),
    )
    log.info("channel.send verb registered (governed outbound, HITL by default)")


async def _register_consumed_mcp(kernel: Kernel, tenant_id: str, mcp_cfg) -> None:
    """Register external MCP servers declared in the bundle's manifest
    (`mcp.consume`), each INERT pending review (SEC-22) - the review/activate route
    still gates them. Lets a project declare its external MCP servers as data
    rather than POSTing them at runtime (Round Fifteen). An entry names its bearer
    with ``credential_ref`` (a secret-store key, never the secret itself) so the
    kernel resolves it per call (SEC-04/05); raw material is refused."""
    from boltrig.adapters.mcp_consumer import McpConsumerAdapter
    from boltrig.config.control_mcp import bind_mcp_credential

    for entry in (mcp_cfg or {}).get("consume", []) or []:
        if not isinstance(entry, dict) or not entry.get("id"):
            continue
        consumer = McpConsumerAdapter(entry["id"], url=entry.get("url"))
        await kernel.register_adapter(tenant_id, consumer)  # describe()=[] until review
        await bind_mcp_credential(kernel.store, kernel.credentials, tenant_id, consumer.id, entry)
        log.info("external MCP server '%s' registered (inert, pending review)", entry["id"])


async def _rehydrate_store_adapters(kernel: Kernel, tenant_id: str) -> None:
    """Rebuild live instances for adapter rows the control plane persisted.

    MCP rows use their private endpoint registration; generated rows use their
    bounded executable projection, never the whole OpenAPI document. Durable
    review state stands. Invalid or unknown shapes warn and remain store-only;
    rows already registered by this boot win.
    """

    from boltrig.config.control_generated_adapter import (
        is_generated_adapter_record,
    )
    from boltrig.config.control_rehydrate import rehydrate_adapter_instance

    for record in await kernel.store.list_adapters(tenant_id):
        if kernel.loader.peek(tenant_id, record.id) is not None:
            continue  # the manifest registered this id this boot already
        adapter = await rehydrate_adapter_instance(
            kernel.store, kernel.credentials, kernel.loader, tenant_id, record
        )
        if adapter is not None:
            log.info(
                "rehydrated %s adapter '%s' from its store row",
                record.source,
                record.id,
            )
        elif is_generated_adapter_record(record):
            log.warning(
                "generated adapter '%s' has no valid durable reconstruction "
                "projection; delete and re-generate it",
                record.id,
            )
        elif record.module_ref != "boltrig.adapters.mcp_consumer":
            # Not broken - undeclared: builtin rows have no spec_ref by design
            # (the open builtin-rehydration fork, docs/findings/2026-07-25);
            # the boot path that reconstructs builtins is the manifest
            # `adapters:` list. The old "no honest boot reconstruction"
            # wording misread as a defect (beelink, 2026-08-21).
            log.warning(
                "adapter '%s' (module_ref %s) is not declared in the manifest "
                "and a %s store row is not boot-reconstructible; add it to the "
                "manifest adapters: list (or its opt-in flag) if it should be "
                "live, else it stays a store-only row",
                record.id,
                record.module_ref,
                record.source,
            )
        else:
            log.warning(
                "mcp adapter '%s' has no persisted url (spec_ref) and cannot be "
                "rehydrated; delete and re-register it",
                record.id,
            )


async def _seed_from_manifest(kernel: Kernel, manifest, *, model_catalogue: Any = None) -> None:
    await apply_manifest(kernel, manifest)
    await provision_builtin_integration_catalogue(kernel.store, manifest.tenant_id)
    await _register_memory(kernel, manifest.tenant_id, manifest.section("memory"))
    await register_knowledge(kernel, manifest.tenant_id, manifest.section("knowledge"))
    await register_distill(kernel, manifest.tenant_id, manifest.section("distill"))
    await _register_control_plane(kernel, manifest.tenant_id, model_catalogue=model_catalogue)
    await register_agent_support(kernel, manifest.tenant_id)
    await _register_channel_send(kernel, manifest.tenant_id, manifest)
    await register_device_actions(kernel, manifest.tenant_id)
    await register_camera_actions(kernel, manifest.tenant_id)
    if os.environ.get("BOLTRIG_EMOTION", "").strip() == "1":
        # desktop-only: the same box that publishes the phenotype accepts voluntary gestures (WL-3).
        from boltrig.adapters.builtin.familiar import build as build_familiar

        await kernel.register_adapter(manifest.tenant_id, build_familiar())
    if _desktop_hands_enabled():
        # governed hands on the desktop host (DH-1), only when the add-on is turned on
        await _register_desktop_hands(kernel, manifest.tenant_id)
    await _register_consumed_mcp(kernel, manifest.tenant_id, manifest.section("mcp"))
    net = manifest.network
    # web-fetch BEFORE the rehydrate: rehydrate skips already-registered ids,
    # so the old order warned about the 'web' row every boot and then
    # registered it live two lines later - a pure ordering artifact that read
    # as a dead adapter (misdiagnosed on the beelink, 2026-08-21).
    await _register_web_fetch(kernel, manifest.tenant_id, net.as_egress_config())
    await _rehydrate_store_adapters(kernel, manifest.tenant_id)
    skills_dir = _find(_SKILLS_DIR_CANDIDATES)
    if skills_dir:
        from boltrig.skills import load_skills_dir

        try:
            loaded = await load_skills_dir(kernel.store, manifest.tenant_id, skills_dir)
            log.info("loaded %d skills from %s", len(loaded), skills_dir)
        except Exception as exc:  # a bad skill file should not stop boot
            log.warning("skill load failed: %s", exc)


def wire_hitl_resume(kernel: Kernel, *, executor=None, pump=None, resume_held_write=None) -> None:
    """Bridge a HITL answer to the lane that can act on it (Beat 5, NFR-REL-03).

    On answer: push the scoped approval event (resumes a durable workflow-run
    waiting on the request's run), requeue the request's AWAITING_HUMAN work
    item back to PENDING, and replay a HELD WRITE if one is waiting on this run
    (decision 0018). All three legs are independent, fail-safe and optional -
    an API-only deployment has no pump, an offline one records events on the
    local executor (P9). The kernel side only sees the injected callables; it
    never imports the fleet (P1). Exactly-once execution of the gated verb is
    the CAS's job (SEC-14), so a duplicate notification is harmless.
    """
    from boltrig.fleet.hatchet_app import APPROVAL_EVENT_KEY

    async def _on_answer(request) -> None:
        await resume_held_write_route(kernel, resume_held_write, request)
        if executor is not None and request.run_id:
            try:
                resp = await kernel.store.get_hitl_response(request.tenant_id, request.id)
                await executor.push_event(
                    APPROVAL_EVENT_KEY,
                    {
                        "hitl_request_id": request.id,
                        "run_id": request.run_id,
                        "verb": request.verb,
                        "decision": resp.decision if resp else None,
                    },
                    scope=request.run_id,
                )
            except Exception:  # resume is best-effort; the answer stands (P9)
                log.warning("HITL resume event push failed", exc_info=True)
        if pump is not None and request.work_item_id:
            try:
                await pump.requeue(request.tenant_id, request.work_item_id)
            except Exception:
                log.warning("HITL work-item requeue failed", exc_info=True)
        await _harvest_hitl_signal(kernel, request)

    kernel.hitl.set_resume_notifier(_on_answer)


async def _harvest_hitl_signal(kernel: Kernel, request) -> None:
    """Turn a HITL verdict into a reuse signal ([2026] VJS-COUNTY 5), best-effort.

    Approval endorses and rejection blocks reuse through the governed reweight-only
    path. It never changes authority, and harvest failure never voids the answer.
    """
    from boltrig.kernel.hitl import _APPROVING
    from boltrig.models import HITLType, InvocationContext
    from boltrig.workflows import harvest_reuse_signal

    try:
        if request.type != HITLType.APPROVAL:
            return
        resp = await kernel.store.get_hitl_response(request.tenant_id, request.id)
        if resp is None:
            return
        approving = resp.decision.strip().lower() in _APPROVING
        perms = await kernel.store.get_tenant_permissions(request.tenant_id)
        ctx = InvocationContext(
            tenant_id=request.tenant_id,
            run_id=request.run_id,
            grants=perms.grants,
            actor="hitl-harvest",
            actor_tier="tier1",
        )
        await harvest_reuse_signal(
            kernel,
            ctx,
            target=request.work_item_id or request.run_id,
            polarity="endorsement" if approving else "block",
            kind="hitl_verdict",
        )
    except Exception:  # the answer stands; a harvest fault never voids it (P9)
        log.debug("HITL reuse-signal harvest failed; continuing", exc_info=True)


def _attach_hands_registry(kernel: Kernel) -> None:
    """Create the ONE pending desktop-command registry (decision 0016, DH-1) and
    hang it on the kernel so the desktop adapter (seed) and the /v1/hands pull
    routes (app.py) share the same instance."""
    from boltrig.kernel.hands_registry import HandsRegistry

    kernel.hands_registry = HandsRegistry()


async def build_kernel_async(
    *,
    codex_config: dict[str, object] | None = None,
    model_catalogue: Any = None,
    sensitive_endpoint_id: str | None = None,
    manifest_snapshot: Any = _MANIFEST_UNSET,
    manifest_path: str | None = None,
) -> Kernel:
    """Construct and fully wire a Kernel (store, adapters, capabilities, invoker).

    H3 (K-19): enforce the audit-key guard on API, fleet and Hatchet boot.
    ``codex_config``, ``sensitive_endpoint_id`` and ``manifest_snapshot`` are
    assembled once by the serving process and injected into every fleet spawner
    it owns. A missing sensitive role remains fail-closed rather than falling
    through to egress. Callers that omit ``manifest_snapshot`` retain the
    standalone convenience behavior of loading the configured manifest here.
    """
    refuse_default_audit_key_in_prod()
    store = await build_store()
    # FR-KER-05: production's shared counter and relay use the same Redis URL;
    # each factory independently refuses a production-local fallback.
    counter = build_counter(os.environ.get("REDIS_URL"))
    event_relay = build_event_relay(
        os.environ.get("REDIS_URL"),
        production=production_signal() is not None,
        namespace=os.environ.get("BOLTRIG_EVENT_RELAY_NAMESPACE", "default"),
    )
    if manifest_snapshot is _MANIFEST_UNSET:
        manifest_path = _find_manifest()
        manifest = load_manifest(manifest_path) if manifest_path else None
    else:
        manifest = manifest_snapshot
    if manifest is not None:
        configured_sensitive_endpoint = manifest.models.sensitive_endpoint
        if (
            sensitive_endpoint_id is not None
            and sensitive_endpoint_id != configured_sensitive_endpoint
        ):
            raise RuntimeError("sensitive model routing changed during process composition")
        sensitive_endpoint_id = configured_sensitive_endpoint
        kernel = Kernel(
            store,
            counter=counter,
            event_relay=event_relay,
            blocking_verbs=manifest.blocking_verbs(),
            approval_timeout_seconds=manifest.hitl.approval_timeout_seconds,
            development_posture=manifest.development_posture,
        )
        if _desktop_hands_enabled():
            _attach_hands_registry(kernel)
        await _seed_from_manifest(kernel, manifest, model_catalogue=model_catalogue)
        log.info("booted from manifest %s (tenant %s)", manifest_path, manifest.tenant_id)
    else:
        kernel = Kernel(store, counter=counter, event_relay=event_relay)
        if _desktop_hands_enabled():
            _attach_hands_registry(kernel)
        await _seed_default(kernel, model_catalogue=model_catalogue)
        log.info("no manifest found; booted minimal demo tenant '%s'", _DEFAULT_TENANT)

    kernel.set_agent_invoker(
        make_agent_invoker(
            kernel,
            codex_config=codex_config,
            model_catalogue=model_catalogue,
            sensitive_endpoint_id=sensitive_endpoint_id,
        )
    )  # US-KER-02
    return kernel


def build_kernel() -> Kernel:
    """Synchronous entrypoint for uvicorn/worker import-time construction."""
    from boltrig.api.model_runtime_composition import compose_process_model_runtime

    manifest_path, manifest, codex_config, model_catalogue = compose_process_model_runtime(
        find_manifest=_find_manifest,
        load_manifest=load_manifest,
        build_codex_config=_build_shared_codex_config,
    )
    return asyncio.run(
        build_kernel_async(
            codex_config=codex_config,
            model_catalogue=model_catalogue,
            manifest_snapshot=manifest,
            manifest_path=manifest_path,
        )
    )


def _deny_all_resolver():
    """A fail-closed resolver: refuse every request (no auth configured, SEC-01)."""
    from fastapi import HTTPException, Request

    async def resolver(request: Request):  # noqa: ARG001
        raise HTTPException(status_code=401, detail="authentication is not configured")

    return resolver


def select_principal_resolver(manifest_snapshot: Any = _MANIFEST_UNSET):
    """Choose the auth resolver from process and manifest trust policy (SEC-01).

    Session and Cloudflare Access remain explicit process deployment modes. For
    generic OIDC, the manifest trio is now a real input: it may supply the full
    verifier configuration, must exactly match a simultaneously configured
    environment trio, and a partial trio refuses boot. The header-trusting dev
    resolver remains local-only; otherwise all requests are refused.
    """
    refuse_default_audit_key_in_prod()  # K-19: a default audit key in prod is fatal
    settings = load_settings()
    if manifest_snapshot is _MANIFEST_UNSET:
        manifest_path = _find_manifest()
        manifest = load_manifest(manifest_path) if manifest_path else None
    else:
        manifest = manifest_snapshot
    from boltrig.api.auth_selection import select_auth_resolver

    return select_auth_resolver(
        settings,
        manifest,
        default_tenant=_DEFAULT_TENANT,
        refuse_dev_auth_in_prod=refuse_dev_auth_in_prod,
        deny_all_resolver=_deny_all_resolver,
    )


def _build_shared_codex_config() -> "dict[str, object] | None":
    """Assemble the trusted read-only Codex provider ONCE, for all spawners.

    Shared deliberately ([2026] VJS-CC-VJS 2, and VJS-CC-VJS 8 which makes the kernel
    the locus of orchestration with Codex a routed leaf). Sharing is load-bearing:
    the provider owns the CellLane that accounts the four physical per-cell tmpfs
    slots, so a second provider would double-count them. Threading this one instance
    into the chat, platform and /v1/spawn spawners also closes the gap VJS-CC-VJS 8
    named - previously only the chat spawner carried it, yet a bare chat turn resolves
    to the cheapest (pi) capability and never to codex-worker, while /v1/spawn could
    pin codex-worker but had no provider and degraded to a script, so no single call
    both routed to Codex and answered. None (any of the three flags unset) constructs
    nothing and keeps every path byte-identical.
    """
    from boltrig.api.codex_trusted import build_trusted_codex_config
    from boltrig.fleet.model_gateway import gateway_config

    settings = load_settings()
    return build_trusted_codex_config(
        settings,
        model_id=settings.codex_model,
        gateway_base_url=str(gateway_config().get("base_url") or ""),
    )


async def _publish_birth_profile_startup(kernel: Kernel, **kwargs: Any) -> bool:
    return await _publish_birth_profile_startup_impl(
        kernel,
        default_tenant=_DEFAULT_TENANT,
        **kwargs,
    )


def _build_chat_wiring(
    codex_config,
    spawn_rules=(),
    sensitive_endpoint_id: str | None = None,
    model_catalogue=None,
):
    """Return ``(chat_factory, resume_held_write)`` sharing ONE ChatService.

    The two are built together because the HITL answer bridge has to reach the
    SAME service the SSE routes use in development, while production's Redis
    relay permits another replica to observe the same continuation (decision
    0018).
    Late-bound through a holder rather than by call order, so it does not matter
    which factory the app lifespan runs first."""
    from boltrig.fleet import build_spawner
    from boltrig.fleet.chat import ChatService, build_turn_executor

    holder = {}

    def chat_factory(kernel):
        from boltrig.api.codex_execution import build_codex_execution_stack

        # the conversational service routes turns through the fleet (US-CONV-02);
        # the manifest chat knob decides a bare turn's skill set per caller role
        # ([2026] VJS-COUNTY 1) - no manifest means the fail-closed empty knob
        manifest_path = _find_manifest()
        chat_cfg = None
        if manifest_path:
            try:
                chat_cfg = load_manifest(manifest_path).chat
            except Exception:
                pass
        settings = load_settings()
        service = ChatService(
            kernel.store,
            kernel.events,
            turn_executor=build_turn_executor(
                kernel,
                build_spawner(
                    kernel,
                    codex_config=codex_config,
                    model_catalogue=model_catalogue,
                    sensitive_endpoint_id=sensitive_endpoint_id,
                    spawn_rules=spawn_rules,
                ),
                chat_config=chat_cfg,
                # Codex shadow stack (SEC-170): None when BOLTRIG_CODEX_LEDGER is off.
                codex_execution=build_codex_execution_stack(settings, kernel.store),
            ),
            # The same ChatConfig carries the attachment caps ([2026] VJS-COUNTY 3);
            # ChatService enforces them fail-closed at intake.
            chat_config=chat_cfg,
            # The ONE chokepoint a held write is replayed through (decision 0018).
            kernel=kernel,
        )
        holder["service"] = service
        return service

    async def resume_held_write(tenant_id, run_id, hitl_request_id):
        service = holder.get("service")
        if service is None:
            return None
        return await service.resume_held_write(tenant_id, run_id, hitl_request_id)

    return chat_factory, resume_held_write


def build_app(
    *,
    addons_snapshot: Any = None,
    password_reset_notifier: Any = None,
    password_reset_readiness_probe: Any = None,
):
    """Build the FastAPI app lazily so resources attach to uvicorn's loop."""
    from boltrig.api.app_composition import compose_api_app

    return compose_api_app(
        addons_snapshot=addons_snapshot,
        password_reset_notifier=password_reset_notifier,
        password_reset_readiness_probe=password_reset_readiness_probe,
        default_tenant=_DEFAULT_TENANT,
        build_shared_codex_config=_build_shared_codex_config,
        find_manifest=_find_manifest,
        load_manifest=load_manifest,
        build_chat_wiring=_build_chat_wiring,
        build_kernel_async=build_kernel_async,
        make_app_spawner=make_app_spawner,
        select_principal_resolver=select_principal_resolver,
        publish_birth_profile_startup=_publish_birth_profile_startup,
        wire_hitl_resume=wire_hitl_resume,
        wire_memory_projection_executor=_wire_memory_projection_executor,
    )
