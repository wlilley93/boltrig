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

from boltrig.config import apply_manifest, load_manifest, load_settings
from boltrig.fleet import make_agent_invoker, make_app_spawner
from boltrig.kernel import Kernel
from boltrig.store import InMemoryStore, Store

log = logging.getLogger("boltrig.bootstrap")

_DEFAULT_TENANT = "default"
_MANIFEST_CANDIDATES = (
    "/app/manifest.yaml",
    "manifest.yaml",
    "manifest.example.yaml",
)


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


async def build_store() -> Store:
    """The store factory (the §6 seam). Returns a durable PostgresStore when
    DATABASE_URL is set, else the in-memory store (so offline tests still run).
    Swapping the store changes nothing else in the system (P1, NFR-MNT)."""
    settings = load_settings()
    if settings.database_url:
        from boltrig.store import PostgresStore

        # RLS-live (opt-in): BOLTRIG_RLS=1 activates the DB-enforced tenant fence.
        # It requires the schema + rls.sql already provisioned by an owner and the
        # app to connect as the non-bypassing boltrig_app role, so apply_schema is
        # off in that mode (an owner connection runs the DDL).
        rls = os.environ.get("BOLTRIG_RLS", "").lower() in ("1", "true", "yes")
        log.info("DATABASE_URL set; using durable PostgresStore (rls=%s)", rls)
        return await PostgresStore.connect(
            settings.database_url, apply_schema=not rls, rls=rls
        )
    return InMemoryStore()


async def _seed_default(kernel: Kernel) -> None:
    """Seed a minimal, offline-safe demo tenant when no manifest is present."""
    from boltrig.adapters.builtin.memory_tickets import build as build_tickets
    from boltrig.models import GrantSet, TenantPermissions

    import inspect

    res = kernel.store.set_tenant_permissions(  # type: ignore[attr-defined]
        TenantPermissions(_DEFAULT_TENANT, GrantSet.of(["*"]))
    )
    if inspect.isawaitable(res):  # PostgresStore seed helper is async
        await res
    await kernel.register_adapter(_DEFAULT_TENANT, build_tickets())
    await _register_control_plane(kernel, _DEFAULT_TENANT)
    await _register_web_fetch(kernel, _DEFAULT_TENANT, {})
    await _register_skill_shelf(kernel, _DEFAULT_TENANT)
    await _register_channel_send(kernel, _DEFAULT_TENANT)


async def _register_memory(kernel: Kernel, tenant_id: str, memory_cfg) -> None:
    """Register the memory subsystem when the manifest opts in (Round Five).

    The engine is adopted, not built: ``local`` is the dev/offline reference,
    ``cognee`` is the production seam. memory.* verbs run the chokepoint via the
    MemoryAdapter, which is the kernel-side isolation boundary (SEC-40)."""
    if not memory_cfg or not memory_cfg.get("enabled"):
        return
    from boltrig.memory.adapter import build_memory_adapter

    engine_kind = memory_cfg.get("engine", "local")
    if engine_kind == "cognee":
        # The flag-on graph upgrade (adopted, not built) - see boltrig/memory/cognee.py.
        from boltrig.memory.cognee import CogneeEngine

        engine = CogneeEngine(memory_cfg)
    elif engine_kind == "pgvector":
        # Native vector recall persisted to this Postgres + pgvector (MEM-ENG-02).
        # The embedder is model-backed when the manifest configures one (route
        # sensitive embedding to a local endpoint, SEC-43); offline default hashes.
        from boltrig.memory import build_embedder
        from boltrig.memory.pgvector import PgVectorMemoryEngine

        dsn = memory_cfg.get("database_url") or os.environ.get("DATABASE_URL", "")
        engine = PgVectorMemoryEngine(dsn, build_embedder(memory_cfg))
    elif engine_kind == "vector":
        # In-process native vector recall (offline reference; same semantics).
        from boltrig.memory import build_embedder
        from boltrig.memory.vector import VectorMemoryEngine

        engine = VectorMemoryEngine(build_embedder(memory_cfg))
    else:
        from boltrig.memory import LocalMemoryEngine

        engine = LocalMemoryEngine()
    adapter = build_memory_adapter(engine, kernel.store, audit=kernel.audit, config=memory_cfg)
    await kernel.register_adapter(tenant_id, adapter)
    log.info("memory subsystem enabled (engine=%s)", memory_cfg.get("engine", "local"))


async def _register_control_plane(kernel: Kernel, tenant_id: str) -> None:
    """Register the control-plane adapter so config amendment flows through the
    chokepoint (Round Seven, 5.1): control.* verbs are grant-checked, audited and
    HITL-gateable like any other action (SEC-51). The loader is injected so
    control.mcp_server.register can park a consumer inert pending SEC-22 review;
    the AdminConfig is late-bound by platform_factory (SEC-75)."""
    from boltrig.config.control_plane import build_control_plane_adapter

    await kernel.register_adapter(
        tenant_id, build_control_plane_adapter(kernel.store, loader=kernel.loader)
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


async def _register_channel_send(kernel: Kernel, tenant_id: str) -> None:
    """Register the governed outbound channel verb (decision 0003). channel.send
    runs the chokepoint like any verb: consequence=high (HITL by default, SEC-39),
    grant-checked, audited; the kernel executes the outbound send directly."""
    from boltrig.adapters.builtin.channel_send import build_channel_send

    await kernel.register_adapter(tenant_id, build_channel_send(kernel.store))
    log.info("channel.send verb registered (governed outbound, HITL by default)")


async def _register_skill_shelf(kernel: Kernel, tenant_id: str) -> None:
    """Register the on-demand skill shelf so an agent can browse + load skills by
    description through the chokepoint (Round Fifteen; FR-SKILL-01/02, SEC-57).
    The engine owns the shelf mechanism; the project owns the skill content."""
    from boltrig.skills.shelf import build_skill_shelf_adapter

    await kernel.register_adapter(tenant_id, build_skill_shelf_adapter(kernel.store))
    log.info("skill shelf registered (skill.search/describe/load)")


async def _register_consumed_mcp(kernel: Kernel, tenant_id: str, mcp_cfg) -> None:
    """Register external MCP servers declared in the bundle's manifest
    (`mcp.consume`), each INERT pending review (SEC-22) - the review/activate route
    still gates them. Lets a project declare its external MCP servers as data
    rather than POSTing them at runtime (Round Fifteen)."""
    for entry in (mcp_cfg or {}).get("consume", []) or []:
        if not isinstance(entry, dict) or not entry.get("id"):
            continue
        from boltrig.adapters.mcp_consumer import McpConsumerAdapter

        consumer = McpConsumerAdapter(
            entry["id"], url=entry.get("url"),
            # credential enters via ${ENV} interpolation at manifest load - held
            # kernel-side, never handed to an agent.
            token=entry.get("credential") or entry.get("token"),
        )
        await kernel.register_adapter(tenant_id, consumer)  # describe()=[] until review
        log.info("external MCP server '%s' registered (inert, pending review)", entry["id"])


async def _seed_from_manifest(kernel: Kernel, manifest) -> None:
    await apply_manifest(kernel, manifest)
    await _register_memory(kernel, manifest.tenant_id, manifest.section("memory"))
    await _register_control_plane(kernel, manifest.tenant_id)
    await _register_skill_shelf(kernel, manifest.tenant_id)
    await _register_channel_send(kernel, manifest.tenant_id)
    await _register_consumed_mcp(kernel, manifest.tenant_id, manifest.section("mcp"))
    net = manifest.network
    await _register_web_fetch(kernel, manifest.tenant_id, {
        "air_gapped": net.air_gapped, "https_proxy": net.https_proxy,
        "allowed_domains": net.allowed_domains, "blocked_domains": net.blocked_domains,
    })
    skills_dir = _find(_SKILLS_DIR_CANDIDATES)
    if skills_dir:
        from boltrig.skills import load_skills_dir

        try:
            loaded = await load_skills_dir(kernel.store, manifest.tenant_id, skills_dir)
            log.info("loaded %d skills from %s", len(loaded), skills_dir)
        except Exception as exc:  # a bad skill file should not stop boot
            log.warning("skill load failed: %s", exc)


def wire_hitl_resume(kernel: Kernel, *, executor=None, pump=None) -> None:
    """Bridge a HITL answer to the durable lane (Beat 5, NFR-REL-03).

    On answer: push the scoped approval event (resumes a durable workflow-run
    waiting on the request's run) and requeue the request's AWAITING_HUMAN work
    item back to PENDING. Both legs are independent, fail-safe and optional -
    an API-only deployment has no pump, an offline one records events on the
    local executor (P9). The kernel side only sees the injected callable; it
    never imports the fleet (P1). Exactly-once execution of the gated verb is
    the CAS's job (SEC-14), so a duplicate notification is harmless.
    """
    from boltrig.fleet.hatchet_app import APPROVAL_EVENT_KEY

    async def _on_answer(request) -> None:
        if executor is not None and request.run_id:
            try:
                resp = await kernel.store.get_hitl_response(request.tenant_id, request.id)
                await executor.push_event(
                    APPROVAL_EVENT_KEY,
                    {"hitl_request_id": request.id, "run_id": request.run_id,
                     "verb": request.verb,
                     "decision": resp.decision if resp else None},
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

    An approval is an ENDORSEMENT, a rejection a BLOCK signal for the run/item the
    request paused. It reweights memory through ``memory.improve`` (reweight-only)
    under a governed system context, so it runs through the chokepoint but can only
    change reuse likelihood - never a grant, scope, or tier. Any failure is
    swallowed: the recorded answer is the truth, a harvest fault never voids it (P9).
    """
    from boltrig.kernel.hitl import _APPROVING
    from boltrig.models import InvocationContext
    from boltrig.workflows import harvest_reuse_signal

    try:
        resp = await kernel.store.get_hitl_response(request.tenant_id, request.id)
        if resp is None:
            return
        approving = resp.decision.strip().lower() in _APPROVING
        perms = await kernel.store.get_tenant_permissions(request.tenant_id)
        ctx = InvocationContext(
            tenant_id=request.tenant_id, run_id=request.run_id,
            grants=perms.grants, actor="hitl-harvest", actor_tier="tier1",
        )
        await harvest_reuse_signal(
            kernel, ctx,
            target=request.work_item_id or request.run_id,
            polarity="endorsement" if approving else "block",
            kind="hitl_verdict",
        )
    except Exception:  # the answer stands; a harvest fault never voids it (P9)
        log.debug("HITL reuse-signal harvest failed; continuing", exc_info=True)


async def build_kernel_async() -> Kernel:
    """Construct and fully wire a Kernel (store, adapters, capabilities, invoker).

    H3 (K-19): enforce the audit-key guard on EVERY kernel-building path, not just
    create_app. The fleet worker and Hatchet worker boot through here (not
    create_app), so without this a production worker missing BOLTRIG_AUDIT_HMAC_KEY
    would silently write forgeable audit rows under the in-source default key. Fail
    hard before building anything; create_app keeps its own idempotent call."""
    refuse_default_audit_key_in_prod()
    store = await build_store()
    manifest_path = _find_manifest()
    if manifest_path:
        manifest = load_manifest(manifest_path)
        kernel = Kernel(store, blocking_verbs=manifest.blocking_verbs())
        await _seed_from_manifest(kernel, manifest)
        log.info("booted from manifest %s (tenant %s)", manifest_path, manifest.tenant_id)
    else:
        kernel = Kernel(store)
        await _seed_default(kernel)
        log.info("no manifest found; booted minimal demo tenant '%s'", _DEFAULT_TENANT)

    kernel.set_agent_invoker(make_agent_invoker(kernel))  # US-KER-02
    return kernel


def build_kernel() -> Kernel:
    """Synchronous entrypoint for uvicorn/worker import-time construction."""
    return asyncio.run(build_kernel_async())


def _deny_all_resolver():
    """A fail-closed resolver: refuse every request (no auth configured, SEC-01)."""
    from fastapi import HTTPException, Request

    async def resolver(request: Request):  # noqa: ARG001
        raise HTTPException(status_code=401, detail="authentication is not configured")

    return resolver


_PROD_SIGNALS = ("prod", "production", "staging")


def production_signal(env: dict | None = None) -> str | None:
    """Return a production signal if one is present, else None (IAM-09).

    A signal is: ENV / BOLTRIG_ENV / APP_ENV set to prod/production/staging, or an
    explicit BOLTRIG_PRODUCTION=1. Pure + env-injectable so it is unit-testable."""
    import os

    e = env if env is not None else os.environ
    if (e.get("BOLTRIG_PRODUCTION") or "").strip().lower() in {"1", "true", "yes", "on"}:
        return "BOLTRIG_PRODUCTION"
    for key in ("ENV", "BOLTRIG_ENV", "APP_ENV"):
        val = (e.get(key) or "").strip().lower()
        if val in _PROD_SIGNALS:
            return f"{key}={val}"
    return None


def refuse_dev_auth_in_prod(env: dict | None = None) -> None:
    """Abort if dev auth is enabled with any production signal (IAM-09).

    The header-trusting resolver is a debug bypass; leaving it reachable in
    production is the #1 fast-build failure. Fail hard, do not merely warn."""
    signal = production_signal(env)
    if signal is not None:
        raise RuntimeError(
            f"FATAL: BOLTRIG_DEV_AUTH is set with a production signal ({signal}). "
            "Dev auth is a header-trusting bypass and must never run in production "
            "(IAM-09). Unset BOLTRIG_DEV_AUTH and configure OIDC_*."
        )


def refuse_default_audit_key_in_prod(env: dict | None = None) -> None:
    """Abort if the audit-chain HMAC key is unset/default with a production signal
    (K-19). The hash chain is only tamper-evident while the key is secret; shipping
    the in-source `dev-insecure-audit-key` in prod makes the chain forgeable. Fail
    hard, mirroring refuse_dev_auth_in_prod."""
    import os

    e = env if env is not None else os.environ
    signal = production_signal(e)
    key = e.get("BOLTRIG_AUDIT_HMAC_KEY")
    if signal is not None and (not key or key == "dev-insecure-audit-key"):
        raise RuntimeError(
            f"FATAL: BOLTRIG_AUDIT_HMAC_KEY is unset/default with a production signal "
            f"({signal}). The audit chain is forgeable without a secret key (K-19). "
            "Set a strong BOLTRIG_AUDIT_HMAC_KEY."
        )


def select_principal_resolver():
    """Choose the auth resolver from the environment (SEC-01).

    OIDC when the OIDC_* trio is set; the header-trusting dev resolver only when
    BOLTRIG_DEV_AUTH=1 (local dev); otherwise fail closed (refuse all requests).
    """
    refuse_default_audit_key_in_prod()  # K-19: a default audit key in prod is fatal
    settings = load_settings()
    if settings.session_auth_configured:
        # First-party invite-only login ([2026] VJS-COUNTY 7, D3). Opt-in via
        # BOLTRIG_AUTH_MODE=session; selected in place of Cloudflare Access. Verifies
        # the Boltrig session cookie and resolves the Principal, fail-closed. The CF
        # Access resolver stays in the code (below) so a deploy that has not opted in
        # is unchanged - the prod cutover / CF-Access removal is Principal-gated (D10).
        from boltrig.identity import build_session_resolver

        tenant = settings.session_tenant or _DEFAULT_TENANT
        log.info("first-party session auth enabled (tenant %s)", tenant)
        return build_session_resolver(tenant)
    if settings.cf_access_configured:
        import json

        from boltrig.identity import OidcVerifier, build_cf_access_resolver

        team = settings.cf_access_team_domain
        try:
            role_map = json.loads(settings.cf_access_role_map) if settings.cf_access_role_map else {}
        except (ValueError, TypeError):
            log.error("CF_ACCESS_ROLE_MAP is not valid JSON; treating as empty (deny-by-default)")
            role_map = {}
        tenant = settings.cf_access_tenant or _DEFAULT_TENANT
        # CF Access JWTs are verified against the team's certs; the issuer IS the
        # team domain and the audience IS the application's AUD tag.
        verifier = OidcVerifier(
            issuer=team,
            audience=settings.cf_access_aud,
            jwks_uri=f"{team}/cdn-cgi/access/certs",
        )
        log.info("Cloudflare Access auth enabled (team %s, %d mapped emails)", team, len(role_map))
        return build_cf_access_resolver(
            verifier=verifier,
            tenant_id=tenant,
            role_map=role_map,
            default_role=settings.cf_access_default_role,
        )
    if settings.oidc_configured:
        from boltrig.identity import OidcVerifier, build_principal_resolver

        manifest_path = _find_manifest()
        if manifest_path:
            manifest = load_manifest(manifest_path)
            mappings, tenant = list(manifest.role_mappings), manifest.tenant_id
        else:
            mappings, tenant = [], _DEFAULT_TENANT
        verifier = OidcVerifier(
            settings.oidc_issuer, settings.oidc_audience, settings.oidc_jwks_uri
        )
        log.info("OIDC auth enabled (issuer %s)", settings.oidc_issuer)
        return build_principal_resolver(verifier=verifier, mappings=mappings, tenant_id=tenant)
    if settings.dev_auth:
        # IAM-09: dev auth must be IMPOSSIBLE in production. Refuse to start (not
        # just warn) if a production signal is present alongside dev auth.
        refuse_dev_auth_in_prod()
        log.warning(
            "BOLTRIG_DEV_AUTH=1: header-trusting dev auth is active. NOT for production (SEC-01)."
        )
        return None  # create_app default is the dev header resolver
    log.warning(
        "no OIDC_* config and BOLTRIG_DEV_AUTH unset: refusing all requests (fail-closed). "
        "Set OIDC_ISSUER/OIDC_AUDIENCE/OIDC_JWKS_URI for production, or BOLTRIG_DEV_AUTH=1 for dev."
    )
    return _deny_all_resolver()


def build_app():
    """Build the FastAPI app for uvicorn (target: boltrig.api.asgi:app).

    The kernel is built by the app lifespan on the serving loop (not here), so
    loop-bound resources like the asyncpg pool attach to uvicorn's loop."""
    from boltrig.fleet import build_spawner
    from boltrig.fleet.chat import ChatService, build_turn_executor
    from boltrig.kernel.app import create_app

    def chat_factory(kernel):
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
        return ChatService(
            kernel.store, kernel.events,
            turn_executor=build_turn_executor(
                kernel, build_spawner(kernel), chat_config=chat_cfg
            ),
            # The same ChatConfig carries the attachment caps ([2026] VJS-COUNTY 3);
            # ChatService enforces them fail-closed at intake.
            chat_config=chat_cfg,
        )

    def platform_factory(kernel):
        # Round Three studios/admin/eval ride existing services (C2)
        from boltrig.config.admin import AdminConfig
        from boltrig.fleet import register_workers
        from boltrig.fleet.eval import EvalRunner
        from boltrig.workflows import WorkflowLibrary, WorkflowPromoter

        manifest_path = _find_manifest()
        tenant = _DEFAULT_TENANT
        if manifest_path:
            try:
                tenant = load_manifest(manifest_path).tenant_id
            except Exception:
                pass
        spawner = build_spawner(kernel)
        # Honest executor selection (US-EXE-05): record which executor serves
        # this app and whether it is durable. Workflow trigger descriptors
        # already stamp `durable` per run; Beat 4 extends the same stamp into
        # spawn/work-item execution metadata (fleet/spawner, not wired here).
        executor = register_workers(kernel)
        log.info(
            "workflow executor: %s (durable=%s)",
            type(executor).__name__, executor.durable,
        )
        # Beat 5: register the governed task bodies on the local executor (the
        # Hatchet executor got its client-side handles in register_workers) and
        # bridge HITL answers to the durable lane. No pump here - the API
        # process is queue-side; the worker process wires its own (NFR-REL-03).
        try:
            from boltrig.fleet.hatchet_app import register_boltrig_tasks

            register_boltrig_tasks(executor, kernel)
        except Exception:  # task registration must never break boot (P9)
            log.warning("boltrig task registration failed", exc_info=True)
        wire_hitl_resume(kernel, executor=executor)
        admin = AdminConfig(kernel.store, tenant_id=tenant, path=manifest_path)
        # Share the ONE AdminConfig with the governed control.config.upsert verb
        # so the PUT route and the verb mutate one config doc and record revisions
        # through one path (SEC-75).
        control = kernel.loader.peek(tenant, "control")
        if control is not None and hasattr(control, "set_admin"):
            control.set_admin(admin)
        eval_runner = EvalRunner(kernel, spawner)
        return {
            "admin": admin,
            "eval": eval_runner,
            "spawner": spawner,
            "workflows": WorkflowLibrary(
                kernel.store, executor=executor, kernel=kernel
            ),
            # Eval-gated promotion ([2026] VJS-COUNTY 5): shares the ONE EvalRunner
            # so a candidate is proven through the same chokepoint under the
            # initiator ceiling (SEC-29) before it is preferred for reuse.
            "promoter": WorkflowPromoter(kernel.store, eval_runner),
        }

    return create_app(
        kernel_factory=build_kernel_async,
        spawner_factory=make_app_spawner,
        principal_resolver=select_principal_resolver(),
        chat_factory=chat_factory,
        platform_factory=platform_factory,
    )
