"""Rebuildable compiler fanout; canonical ingestion never depends on it."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from boltrig.config.environment import is_truthy
from boltrig.memory.cognee import CogneeEngine
from boltrig.memory.engine import EngineFact

from .models import Asset, ProjectionStatus, Provider, Segment, now


UNAVAILABLE_PROVIDER_IDS = frozenset({"supermemory", "mem0"})
UNAVAILABLE_PROVIDER_REASON = (
    "Credential-backed projection adapter is not implemented in this build."
)


def provider_defaults(tenant_id: str, config: dict[str, Any] | None = None) -> list[Provider]:
    cfg = dict(config or {})
    entries = {
        str(row.get("id")): row
        for row in cfg.get("providers", [])
        if isinstance(row, dict) and row.get("id")
    }

    def make(
        provider_id: str,
        name: str,
        role: str,
        *,
        enabled: bool,
        bundled: bool,
    ) -> Provider:
        entry = entries.get(provider_id, {})
        configured_enabled = _bool(entry.get("enabled"), enabled)
        unavailable = provider_id in UNAVAILABLE_PROVIDER_IDS
        return Provider(
            id=provider_id,
            tenant_id=tenant_id,
            display_name=name,
            role=role,
            enabled=False if unavailable else configured_enabled,
            bundled=bundled,
            health="unavailable" if unavailable else "unknown",
            status=(
                "unavailable" if unavailable else ("enabled" if configured_enabled else "available")
            ),
            last_error=UNAVAILABLE_PROVIDER_REASON if unavailable else None,
            config={**dict(cfg.get(provider_id) or {}), **dict(entry.get("config") or {})},
        )

    return [
        make("cognee", "Cognee", "knowledge_compiler", enabled=True, bundled=True),
        make("supermemory", "Supermemory", "managed_context", enabled=False, bundled=False),
        make("mem0", "Mem0", "memory_compatibility", enabled=False, bundled=False),
    ]


async def reconcile_unavailable_providers(repository, tenant_id: str) -> None:
    """Repair persisted rows that older builds allowed operators to enable."""

    for provider_id in UNAVAILABLE_PROVIDER_IDS:
        provider = await repository.get_provider(tenant_id, provider_id)
        if provider is None:
            continue
        if (
            provider.enabled
            or provider.health != "unavailable"
            or provider.status != "unavailable"
            or provider.last_error != UNAVAILABLE_PROVIDER_REASON
        ):
            await repository.save_provider(
                replace(
                    provider,
                    enabled=False,
                    health="unavailable",
                    status="unavailable",
                    last_error=UNAVAILABLE_PROVIDER_REASON,
                    updated_at=now(),
                )
            )


def _bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return is_truthy(str(value))


class KnowledgeProjectionCoordinator:
    def __init__(self, repository, config: dict[str, Any] | None = None) -> None:
        self._repository = repository
        self._config = dict(config or {})
        self._cognee = CogneeEngine(dict(self._config.get("cognee") or {}))

    async def refresh_health(self, tenant_id: str) -> None:
        provider = await self._repository.get_provider(tenant_id, "cognee")
        if provider is None:
            return
        health = await self._cognee.health()
        await self._repository.save_provider(
            replace(
                provider,
                health=health,
                status="enabled" if provider.enabled and health == "ok" else (
                    "degraded" if provider.enabled else "available"
                ),
                last_error=self._cognee.health_reason,
                updated_at=now(),
            )
        )

    async def compile(
        self, tenant_id: str, asset: Asset, segments: tuple[Segment, ...], context
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for provider in await self._repository.list_providers(tenant_id):
            if not provider.enabled:
                continue
            if provider.id == "cognee":
                status = await self._compile_cognee(provider, asset, segments)
            else:
                status = ProjectionStatus(
                    tenant_id=tenant_id,
                    provider_id=provider.id,
                    subject_type="asset",
                    subject_id=asset.id,
                    operation="compile",
                    status="failed",
                    error=(
                        f"{provider.display_name} is enabled but needs its credential-backed "
                        "projection adapter configured"
                    ),
                )
                await self._mark_provider(provider, "degraded", status.error)
            await self._repository.save_projection(status)
            results.append(_public_status(status))
        return results

    async def _compile_cognee(
        self, provider: Provider, asset: Asset, segments: tuple[Segment, ...]
    ) -> ProjectionStatus:
        health = await self._cognee.health()
        if health != "ok":
            error = self._cognee.health_reason or "Cognee is not ready"
            await self._mark_provider(provider, "degraded", error)
            return ProjectionStatus(
                tenant_id=asset.tenant_id,
                provider_id="cognee",
                subject_type="asset",
                subject_id=asset.id,
                operation="compile",
                status="failed",
                error=error,
            )
        facts = [
            EngineFact(
                id=segment.id,
                owner_scope=asset.owner_scope,
                kind="knowledge_segment",
                content=segment.text,
                source_kind="knowledge_revision",
                source_ref=(
                    f"knowledge://{asset.id}/{segment.revision_id}#{segment.id}"
                ),
            )
            for segment in segments
        ]
        try:
            refs = await self._cognee.remember(asset.tenant_id, facts)
        except Exception as exc:
            error = _error_text(exc)
            await self._mark_provider(provider, "degraded", error)
            return ProjectionStatus(
                tenant_id=asset.tenant_id,
                provider_id="cognee",
                subject_type="asset",
                subject_id=asset.id,
                operation="compile",
                status="failed",
                error=error,
            )
        await self._mark_provider(provider, "ok", None)
        return ProjectionStatus(
            tenant_id=asset.tenant_id,
            provider_id="cognee",
            subject_type="asset",
            subject_id=asset.id,
            operation="compile",
            status="written",
            projection_ref=f"cognee:{len(refs)}:{asset.id}",
        )

    async def erase(
        self, tenant_id: str, asset_id: str, segment_ids: list[str]
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for provider in await self._repository.list_providers(tenant_id):
            if not provider.enabled:
                continue
            status = await self._erase_one(provider, tenant_id, asset_id, segment_ids)
            await self._repository.save_projection(status)
            results.append(_public_status(status))
        return results

    async def _erase_one(
        self, provider: Provider, tenant_id: str, asset_id: str, segment_ids: list[str]
    ) -> ProjectionStatus:
        try:
            if provider.id != "cognee":
                raise ValueError("credential-backed erasure adapter is not configured")
            await self._cognee.forget(tenant_id, fact_ids=segment_ids, scopes=None)
            return ProjectionStatus(
                tenant_id=tenant_id,
                provider_id=provider.id,
                subject_type="asset",
                subject_id=asset_id,
                operation="erase",
                status="deleted",
            )
        except Exception as exc:
            error = _error_text(exc)
            await self._mark_provider(provider, "degraded", error)
            return ProjectionStatus(
                tenant_id=tenant_id,
                provider_id=provider.id,
                subject_type="asset",
                subject_id=asset_id,
                operation="erase",
                status="delete_failed",
                error=error,
            )

    async def _mark_provider(
        self, provider: Provider, health: str, error: str | None
    ) -> None:
        await self._repository.save_provider(
            replace(
                provider,
                health=health,
                status="enabled" if health == "ok" else "degraded",
                last_error=error,
                updated_at=now(),
            )
        )


def _error_text(exc: Exception) -> str:
    # Controlled messages (ValueError/LookupError raised deliberately) may be
    # surfaced; anything else collapses to the type name so endpoint URLs,
    # bucket names, or DSN fragments never reach the agent or the audit log.
    if isinstance(exc, (ValueError, LookupError)):
        return str(exc)[:500]
    return type(exc).__name__


def _public_status(status: ProjectionStatus) -> dict[str, Any]:
    return {
        "provider_id": status.provider_id,
        "operation": status.operation,
        "status": status.status,
        "projection_ref": status.projection_ref,
        "error": status.error,
    }
