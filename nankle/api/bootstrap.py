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
    os.environ.get("NANKLE_MANIFEST", ""),
    "/app/manifest.yaml",
    "manifest.yaml",
    "manifest.example.yaml",
)
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


async def _seed_from_manifest(kernel: Kernel, manifest) -> None:
    await apply_manifest(kernel, manifest)
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
    manifest_path = _find(_MANIFEST_CANDIDATES)
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


def select_principal_resolver():
    """Choose the auth resolver from the environment (SEC-01).

    OIDC when the OIDC_* trio is set; the header-trusting dev resolver only when
    NANKLE_DEV_AUTH=1 (local dev); otherwise fail closed (refuse all requests).
    """
    settings = load_settings()
    if settings.oidc_configured:
        from nankle.identity import OidcVerifier, build_principal_resolver

        manifest_path = _find(_MANIFEST_CANDIDATES)
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
    from nankle.kernel.app import create_app

    return create_app(
        kernel_factory=build_kernel_async,
        spawner_factory=make_app_spawner,
        principal_resolver=select_principal_resolver(),
    )
