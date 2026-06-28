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


def build_store() -> Store:
    """The store factory. Returns the in-memory store today; a Postgres store
    plugs in here without touching any caller (the seam in NFR-MNT/§6)."""
    settings = load_settings()
    if settings.database_url:
        log.warning(
            "DATABASE_URL is set but the Postgres store is a seam; using in-memory "
            "store. Plug the SQL store into build_store() to persist."
        )
    return InMemoryStore()


async def _seed_default(kernel: Kernel) -> None:
    """Seed a minimal, offline-safe demo tenant when no manifest is present."""
    from nankle.adapters.builtin.memory_tickets import build as build_tickets
    from nankle.models import GrantSet, TenantPermissions

    kernel.store.set_tenant_permissions(  # type: ignore[attr-defined]
        TenantPermissions(_DEFAULT_TENANT, GrantSet.of(["*"]))
    )
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


def build_kernel() -> Kernel:
    """Construct and fully wire a Kernel (adapters, capabilities, agent invoker)."""
    store = build_store()
    manifest_path = _find(_MANIFEST_CANDIDATES)
    if manifest_path:
        manifest = load_manifest(manifest_path)
        kernel = Kernel(store, blocking_verbs=manifest.blocking_verbs())
        asyncio.run(_seed_from_manifest(kernel, manifest))
        log.info("booted from manifest %s (tenant %s)", manifest_path, manifest.tenant_id)
    else:
        kernel = Kernel(store)
        asyncio.run(_seed_default(kernel))
        log.info("no manifest found; booted minimal demo tenant '%s'", _DEFAULT_TENANT)

    kernel.set_agent_invoker(make_agent_invoker(kernel))  # US-KER-02
    return kernel


def build_app():
    """Build the FastAPI app for uvicorn (target: nankle.api.asgi:app)."""
    from nankle.kernel.app import create_app

    kernel = build_kernel()
    return create_app(kernel, spawner=make_app_spawner(kernel))
