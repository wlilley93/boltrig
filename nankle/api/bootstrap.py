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

from nankle.config import apply_manifest, load_manifest, load_settings
from nankle.fleet import make_agent_invoker, make_app_spawner
from nankle.kernel import Kernel
from nankle.store import InMemoryStore, Store

log = logging.getLogger("nankle.bootstrap")

_DEFAULT_TENANT = "default"
_MANIFEST_CANDIDATES = (
    "/app/manifest.yaml",
    "manifest.yaml",
    "manifest.example.yaml",
)


def _find_manifest() -> str | None:
    """Locate the manifest, reading ``NANKLE_MANIFEST`` LIVE (not at import time)
    so it is honoured even when set after import (tests / dynamic config), then
    falling back to the well-known paths."""
    return _find((os.environ.get("NANKLE_MANIFEST", ""), *_MANIFEST_CANDIDATES))
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
        from nankle.store import PostgresStore

        log.info("DATABASE_URL set; using durable PostgresStore")
        return await PostgresStore.connect(settings.database_url)
    return InMemoryStore()


async def _seed_default(kernel: Kernel) -> None:
    """Seed a minimal, offline-safe demo tenant when no manifest is present."""
    from nankle.adapters.builtin.memory_tickets import build as build_tickets
    from nankle.models import GrantSet, TenantPermissions

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


async def _register_memory(kernel: Kernel, tenant_id: str, memory_cfg) -> None:
    """Register the memory subsystem when the manifest opts in (Round Five).

    The engine is adopted, not built: ``local`` is the dev/offline reference,
    ``cognee`` is the production seam. memory.* verbs run the chokepoint via the
    MemoryAdapter, which is the kernel-side isolation boundary (SEC-40)."""
    if not memory_cfg or not memory_cfg.get("enabled"):
        return
    from nankle.memory import LocalMemoryEngine
    from nankle.memory.adapter import build_memory_adapter

    if memory_cfg.get("engine") == "cognee":
        from nankle.memory.cognee import CogneeEngine

        engine = CogneeEngine(memory_cfg)
    else:
        engine = LocalMemoryEngine()
    adapter = build_memory_adapter(engine, kernel.store, audit=kernel.audit, config=memory_cfg)
    await kernel.register_adapter(tenant_id, adapter)
    log.info("memory subsystem enabled (engine=%s)", memory_cfg.get("engine", "local"))


async def _register_control_plane(kernel: Kernel, tenant_id: str) -> None:
    """Register the control-plane adapter so config amendment flows through the
    chokepoint (Round Seven, 5.1): control.* verbs are grant-checked, audited and
    HITL-gateable like any other action (SEC-51)."""
    from nankle.config.control_plane import build_control_plane_adapter

    await kernel.register_adapter(tenant_id, build_control_plane_adapter(kernel.store))
    log.info("control-plane verbs registered (governed config amendment)")


async def _register_web_fetch(kernel: Kernel, tenant_id: str, network_cfg) -> None:
    """Register the governed internet-access verb (Round Eight, S4). web.fetch runs
    the chokepoint like any verb; registering it does NOT grant it (the tenant
    ceiling + caller grants still decide). It enforces NetworkConfig + the SSRF
    guard (SEC-52)."""
    from nankle.adapters.builtin.web_fetch import build_web_fetch_adapter

    await kernel.register_adapter(tenant_id, build_web_fetch_adapter(network_cfg or {}))
    log.info("web.fetch verb registered (governed internet access, SSRF-guarded)")


async def _register_skill_shelf(kernel: Kernel, tenant_id: str) -> None:
    """Register the on-demand skill shelf so an agent can browse + load skills by
    description through the chokepoint (Round Fifteen; FR-SKILL-01/02, SEC-57).
    The engine owns the shelf mechanism; the project owns the skill content."""
    from nankle.skills.shelf import build_skill_shelf_adapter

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
        from nankle.adapters.mcp_consumer import McpConsumerAdapter

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
    await _register_consumed_mcp(kernel, manifest.tenant_id, manifest.section("mcp"))
    net = manifest.network
    await _register_web_fetch(kernel, manifest.tenant_id, {
        "air_gapped": net.air_gapped, "https_proxy": net.https_proxy,
        "allowed_domains": net.allowed_domains, "blocked_domains": net.blocked_domains,
    })
    skills_dir = _find(_SKILLS_DIR_CANDIDATES)
    if skills_dir:
        from nankle.skills import load_skills_dir

        try:
            loaded = await load_skills_dir(kernel.store, manifest.tenant_id, skills_dir)
            log.info("loaded %d skills from %s", len(loaded), skills_dir)
        except Exception as exc:  # a bad skill file should not stop boot
            log.warning("skill load failed: %s", exc)


async def build_kernel_async() -> Kernel:
    """Construct and fully wire a Kernel (store, adapters, capabilities, invoker)."""
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

    A signal is: ENV / NANKLE_ENV / APP_ENV set to prod/production/staging, or an
    explicit NANKLE_PRODUCTION=1. Pure + env-injectable so it is unit-testable."""
    import os

    e = env if env is not None else os.environ
    if (e.get("NANKLE_PRODUCTION") or "").strip().lower() in {"1", "true", "yes", "on"}:
        return "NANKLE_PRODUCTION"
    for key in ("ENV", "NANKLE_ENV", "APP_ENV"):
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
            f"FATAL: NANKLE_DEV_AUTH is set with a production signal ({signal}). "
            "Dev auth is a header-trusting bypass and must never run in production "
            "(IAM-09). Unset NANKLE_DEV_AUTH and configure OIDC_*."
        )


def select_principal_resolver():
    """Choose the auth resolver from the environment (SEC-01).

    OIDC when the OIDC_* trio is set; the header-trusting dev resolver only when
    NANKLE_DEV_AUTH=1 (local dev); otherwise fail closed (refuse all requests).
    """
    settings = load_settings()
    if settings.oidc_configured:
        from nankle.identity import OidcVerifier, build_principal_resolver

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
            "NANKLE_DEV_AUTH=1: header-trusting dev auth is active. NOT for production (SEC-01)."
        )
        return None  # create_app default is the dev header resolver
    log.warning(
        "no OIDC_* config and NANKLE_DEV_AUTH unset: refusing all requests (fail-closed). "
        "Set OIDC_ISSUER/OIDC_AUDIENCE/OIDC_JWKS_URI for production, or NANKLE_DEV_AUTH=1 for dev."
    )
    return _deny_all_resolver()


def build_app():
    """Build the FastAPI app for uvicorn (target: nankle.api.asgi:app).

    The kernel is built by the app lifespan on the serving loop (not here), so
    loop-bound resources like the asyncpg pool attach to uvicorn's loop."""
    from nankle.fleet import build_spawner
    from nankle.fleet.chat import ChatService, build_turn_executor
    from nankle.kernel.app import create_app

    def chat_factory(kernel):
        # the conversational service routes turns through the fleet (US-CONV-02)
        return ChatService(
            kernel.store, kernel.events,
            turn_executor=build_turn_executor(kernel, build_spawner(kernel)),
        )

    def platform_factory(kernel):
        # Round Three studios/admin/eval ride existing services (C2)
        from nankle.config.admin import AdminConfig
        from nankle.fleet import register_workers
        from nankle.fleet.eval import EvalRunner
        from nankle.workflows import WorkflowLibrary

        manifest_path = _find_manifest()
        tenant = _DEFAULT_TENANT
        if manifest_path:
            try:
                tenant = load_manifest(manifest_path).tenant_id
            except Exception:
                pass
        spawner = build_spawner(kernel)
        return {
            "admin": AdminConfig(kernel.store, tenant_id=tenant, path=manifest_path),
            "eval": EvalRunner(kernel, spawner),
            "spawner": spawner,
            "workflows": WorkflowLibrary(
                kernel.store, executor=register_workers(kernel), kernel=kernel
            ),
        }

    return create_app(
        kernel_factory=build_kernel_async,
        spawner_factory=make_app_spawner,
        principal_resolver=select_principal_resolver(),
        chat_factory=chat_factory,
        platform_factory=platform_factory,
    )
