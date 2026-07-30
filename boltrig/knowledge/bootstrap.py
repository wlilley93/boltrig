"""Composition root for the first-party Knowledge extension."""

from __future__ import annotations

import logging
import os
from pathlib import Path
import platform
from typing import Any

from boltrig.config.environment import is_truthy

from .adapter import KnowledgeAdapter
from .filesystem_vault import FilesystemObjectVault
from .memory_repository import InMemoryKnowledgeRepository
from .projections import (
    KnowledgeProjectionCoordinator,
    provider_defaults,
    reconcile_unavailable_providers,
)
from .service import KnowledgeService

log = logging.getLogger("boltrig.bootstrap")


def _enabled(config: dict[str, Any]) -> bool:
    # Default OFF: a manifest without a ``knowledge:`` section must not silently
    # spin up a filesystem vault under $HOME (the memory subsystem is likewise
    # default-OFF). Opt in explicitly with ``knowledge.enabled: true``.
    value = config.get("enabled", False)
    return value is True or is_truthy(str(value))


def _default_root() -> Path:
    configured = os.environ.get("BOLTRIG_KNOWLEDGE_VAULT")
    if configured:
        return Path(configured)
    if platform.system() == "Darwin":
        return Path.home() / "Library" / "Application Support" / "Boltrig" / "Knowledge"
    return Path.home() / ".local" / "share" / "boltrig" / "knowledge"


def _default_cognee_root() -> Path:
    configured = os.environ.get("BOLTRIG_COGNEE_ROOT")
    if configured:
        return Path(configured)
    if platform.system() == "Darwin":
        return Path.home() / "Library" / "Application Support" / "Boltrig" / "Cognee"
    return Path.home() / ".local" / "share" / "boltrig" / "cognee"


def _repository(store):
    # Capability check on the PUBLIC type (mirrors build_codex_execution_stack):
    # a PostgresStore gets the durable repository, anything else the in-memory
    # one. PostgresStore exposes no public pool accessor (adding one would grow
    # the already-exempted store/postgres.py), so the pool is read off the
    # checked type - an isinstance guard, not a blind getattr, so a renamed
    # attribute fails loudly instead of silently degrading to in-memory.
    from boltrig.store.postgres import PostgresStore

    if isinstance(store, PostgresStore):
        from .postgres_repository import PostgresKnowledgeRepository

        return PostgresKnowledgeRepository(store._pool)
    return InMemoryKnowledgeRepository()


def _vault(config: dict[str, Any]):
    cfg = dict(config.get("vault") or {})
    if str(cfg.get("kind") or "filesystem").lower() == "s3":
        from .s3_vault import S3ObjectVault

        return S3ObjectVault(
            str(cfg.get("bucket") or ""),
            prefix=str(cfg.get("prefix") or "boltrig"),
            endpoint_url=cfg.get("endpoint_url"),
        )
    return FilesystemObjectVault(cfg.get("root") or _default_root())


async def register_knowledge(
    kernel, tenant_id: str, config: dict[str, Any] | None = None
) -> KnowledgeService | None:
    cfg = dict(config or {})
    if not _enabled(cfg):
        return None
    repository = _repository(kernel.store)
    await repository.ensure_providers(tenant_id, provider_defaults(tenant_id, cfg))
    await reconcile_unavailable_providers(repository, tenant_id)
    cognee_config = dict(cfg.get("cognee") or {})
    cognee_config.setdefault("cognee_root", str(_default_cognee_root()))
    cfg["cognee"] = cognee_config
    projections = KnowledgeProjectionCoordinator(repository, cfg)
    service = KnowledgeService(repository, _vault(cfg), projections)
    await kernel.register_adapter(tenant_id, KnowledgeAdapter(service))
    log.info("Knowledge enabled (Cognee default compiler; canonical vault + catalogue)")
    return service
