"""Per-org/workspace/user AI config store domain (arc-1 structural partial).

The ai_configs upsert/read/delete family - extracted verbatim from
``store/postgres.py`` + ``store/memory.py`` (the [2026] VJS-COUNTY 8, D5
section). Rows carry a credential_ref, never a key. PG host: ``self._pool``;
Mem host: ``self._ai_configs``. Public surface unchanged.
"""

from __future__ import annotations

from boltrig.models import (
    AI_CONFIG_LEVELS, AI_CONFIG_MODALITIES, AiConfig, utcnow,
)
from boltrig.models.errors import SchemaValidationError

from .rows import _ai_config


class AiConfigStorePG:
    """AI config methods for ``PostgresStore``."""

    async def set_ai_config(self, config: AiConfig) -> None:
        # Reject an out-of-set level before it can be persisted (mirrors the
        # workspace-role guard). The row carries a credential_ref only, never a key.
        if config.level not in AI_CONFIG_LEVELS:
            raise SchemaValidationError(
                f"invalid ai-config level: {config.level!r}",
                errors=[f"level must be one of {sorted(AI_CONFIG_LEVELS)}"],
            )
        if config.modality not in AI_CONFIG_MODALITIES:
            raise SchemaValidationError(
                f"invalid ai-config modality: {config.modality!r}",
                errors=[f"modality must be one of {sorted(AI_CONFIG_MODALITIES)}"],
            )
        await self._pool.execute(
            """INSERT INTO ai_configs
               (tenant_id, level, scope_id, provider, model, credential_ref,
                base_url, modality, created_at, updated_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,now())
               ON CONFLICT (tenant_id, level, scope_id, modality) DO UPDATE SET
                 provider=EXCLUDED.provider, model=EXCLUDED.model,
                 credential_ref=EXCLUDED.credential_ref,
                 base_url=EXCLUDED.base_url, updated_at=now()""",
            config.tenant_id, config.level, config.scope_id, config.provider,
            config.model, config.credential_ref, config.base_url, config.modality,
            config.created_at,
        )

    async def get_ai_config(self, tenant_id, level, scope_id, modality="text"):
        # Tenant-scoped: the WHERE binds tenant_id, so it can never return another
        # tenant's AI-config row (None when absent, fail-closed).
        row = await self._pool.fetchrow(
            """SELECT * FROM ai_configs
               WHERE tenant_id=$1 AND level=$2 AND scope_id=$3 AND modality=$4""",
            tenant_id, level, scope_id, modality,
        )
        return _ai_config(row)

    async def list_ai_configs(self, tenant_id):
        rows = await self._pool.fetch(
            "SELECT * FROM ai_configs WHERE tenant_id=$1 ORDER BY level, scope_id",
            tenant_id,
        )
        return [_ai_config(r) for r in rows]

    async def delete_ai_config(self, tenant_id, level, scope_id, modality="text"):
        await self._pool.execute(
            "DELETE FROM ai_configs WHERE tenant_id=$1 AND level=$2 AND scope_id=$3 AND modality=$4",
            tenant_id, level, scope_id, modality,
        )




class AiConfigStoreMem:
    """AI config methods for ``InMemoryStore``."""

    async def set_ai_config(self, config: AiConfig) -> None:
        # Reject an out-of-set level (mirrors the workspace-role guard) so an invalid
        # level can never be persisted. The row stores a credential_ref, never a key.
        if config.level not in AI_CONFIG_LEVELS:
            raise SchemaValidationError(
                f"invalid ai-config level: {config.level!r}",
                errors=[f"level must be one of {sorted(AI_CONFIG_LEVELS)}"],
            )
        if config.modality not in AI_CONFIG_MODALITIES:
            raise SchemaValidationError(
                f"invalid ai-config modality: {config.modality!r}",
                errors=[f"modality must be one of {sorted(AI_CONFIG_MODALITIES)}"],
            )
        config.updated_at = utcnow()
        self._ai_configs[(config.tenant_id, config.level, config.scope_id, config.modality)] = (
            config
        )

    async def get_ai_config(self, tenant_id, level, scope_id, modality="text"):
        # Tenant-scoped: the key includes tenant_id, so a lookup under another tenant
        # never returns this tenant's row (fail-closed, never crosses the boundary).
        return self._ai_configs.get((tenant_id, level, scope_id, modality))

    async def list_ai_configs(self, tenant_id):
        return [c for (t, _, _, _), c in self._ai_configs.items() if t == tenant_id]

    async def delete_ai_config(self, tenant_id, level, scope_id, modality="text"):
        self._ai_configs.pop((tenant_id, level, scope_id, modality), None)
