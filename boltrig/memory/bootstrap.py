"""Composition helper for the optional governed Memory subsystem."""

from __future__ import annotations

import logging
import os
from typing import Any

from boltrig.config.environment import is_truthy

log = logging.getLogger("boltrig.bootstrap")


def _bool(value: Any) -> bool:
    return value is True or is_truthy(str(value))


async def register_memory(kernel, tenant_id: str, memory_cfg) -> None:
    """Select an engine and register memory.* behind the dispatcher."""
    if not memory_cfg or not _bool(memory_cfg.get("enabled")):
        return
    from boltrig.memory.adapter import build_memory_adapter
    from boltrig.memory.projection_adapters import build_memory_projection_fanout

    engine_kind = memory_cfg.get("engine", "local")
    if engine_kind == "cognee":
        from boltrig.memory.cognee import CogneeEngine

        engine = CogneeEngine(memory_cfg)
    elif engine_kind == "pgvector":
        from boltrig.memory import build_embedder
        from boltrig.memory.pgvector import PgVectorMemoryEngine

        dsn = memory_cfg.get("database_url") or os.environ.get("DATABASE_URL", "")
        engine = PgVectorMemoryEngine(dsn, build_embedder(memory_cfg))
    elif engine_kind == "vector":
        from boltrig.memory import build_embedder
        from boltrig.memory.vector import VectorMemoryEngine

        engine = VectorMemoryEngine(build_embedder(memory_cfg))
    else:
        from boltrig.memory import LocalMemoryEngine

        engine = LocalMemoryEngine()
    projections = build_memory_projection_fanout(kernel.store, memory_cfg)
    adapter = build_memory_adapter(
        engine,
        kernel.store,
        audit=kernel.audit,
        config=memory_cfg,
        projections=projections,
    )
    await kernel.register_adapter(tenant_id, adapter)
    log.info("memory subsystem enabled (engine=%s, projections=%s)", engine_kind, bool(projections))
