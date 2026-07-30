"""Durable effective-policy lookup for validated spawn rules."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from .spawn_rules import EffectiveSpawnRules, SpawnRule, parse_spawn_rules


async def effective_spawn_rules(
    store: Any,
    tenant_id: str,
    base_rules: Sequence[SpawnRule],
) -> EffectiveSpawnRules:
    revisions = await store.list_config_revisions(
        tenant_id, "manifest_section", "spawn_rules"
    )
    if not revisions:
        return EffectiveSpawnRules(
            rules=tuple(base_rules),
            source="process_start_manifest",
            revision_id=None,
        )
    revision = max(
        revisions,
        key=lambda item: (
            item.id is not None,
            item.id if item.id is not None else -1,
            item.created_at,
        ),
    )
    return EffectiveSpawnRules(
        rules=parse_spawn_rules(revision.payload.get("value")),
        source="config_revision",
        revision_id=revision.id,
    )
