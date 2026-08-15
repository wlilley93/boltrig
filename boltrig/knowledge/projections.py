"""Rebuildable compiler fanout; canonical ingestion never depends on it."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from boltrig.config.environment import is_truthy
from boltrig.memory.cognee import CogneeEngine
from boltrig.memory.cognee_model_binding import (
    CogneeModelBindingResolver,
    CogneeModelUnavailable,
)
from boltrig.memory.engine import EngineFact

from .models import Asset, ProjectionStatus, Provider, Segment, now


SUPPORTED_PROVIDER_IDS = frozenset({"cognee"})
_RETIRED_PROVIDER_IDS = frozenset({"supermemory", "mem0"})
_RETIRED_PROVIDER_REASON = "This legacy provider is no longer shipped by Boltrig."


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
        return Provider(
            id=provider_id,
            tenant_id=tenant_id,
            display_name=name,
            role=role,
            enabled=configured_enabled,
            bundled=bundled,
            health="unknown",
            status="enabled" if configured_enabled else "available",
            last_error=None,
            config={**dict(cfg.get(provider_id) or {}), **dict(entry.get("config") or {})},
        )

    return [
        make("cognee", "Cognee", "knowledge_compiler", enabled=True, bundled=True),
    ]


async def retire_legacy_providers(repository, tenant_id: str) -> None:
    """Disable rows created before Mem0 and Supermemory left the shipped catalogue.

    The rows remain as inert migration history so an upgrade cannot accidentally
    re-enable an old external sink. Public provider reads filter them out.
    """

    for provider_id in _RETIRED_PROVIDER_IDS:
        provider = await repository.get_provider(tenant_id, provider_id)
        if provider is None:
            continue
        if (
            provider.enabled
            or provider.health != "retired"
            or provider.status != "retired"
            or provider.last_error != _RETIRED_PROVIDER_REASON
        ):
            await repository.save_provider(
                replace(
                    provider,
                    enabled=False,
                    health="retired",
                    status="retired",
                    last_error=_RETIRED_PROVIDER_REASON,
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
    def __init__(
        self,
        repository,
        config: dict[str, Any] | None = None,
        *,
        model_resolver: CogneeModelBindingResolver | None = None,
    ) -> None:
        self._repository = repository
        self._config = dict(config or {})
        self._cognee = CogneeEngine(dict(self._config.get("cognee") or {}))
        self._model_resolver = model_resolver

    async def refresh_health(self, tenant_id: str, context=None) -> None:
        provider = await self._repository.get_provider(tenant_id, "cognee")
        if provider is None:
            return
        try:
            runtime_model = await self._runtime_model(tenant_id, context)
        except CogneeModelUnavailable as error:
            await self._repository.save_provider(
                replace(
                    provider,
                    health="degraded",
                    status="degraded" if provider.enabled else "available",
                    last_error=str(error),
                    updated_at=now(),
                )
            )
            return
        health = await self._cognee.health(runtime_model)
        reason = self._cognee.health_reason
        if runtime_model is None and health == "degraded" and not self._static_llm():
            reason = "Connect an AI provider to enable knowledge enrichment"
        await self._repository.save_provider(
            replace(
                provider,
                health=health,
                status="enabled"
                if provider.enabled and health == "ok"
                else ("degraded" if provider.enabled else "available"),
                last_error=reason,
                updated_at=now(),
            )
        )

    def _static_llm(self) -> bool:
        llm = dict((self._config.get("cognee") or {}).get("llm") or {})
        return bool(llm.get("api_key"))

    async def _runtime_model(self, tenant_id: str, context):
        if self._model_resolver is None or context is None:
            return None
        return await self._model_resolver.resolve(tenant_id, context)

    async def compile(
        self, tenant_id: str, asset: Asset, segments: tuple[Segment, ...], context
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for provider in await self._repository.list_providers(tenant_id):
            if provider.id not in SUPPORTED_PROVIDER_IDS or not provider.enabled:
                continue
            if provider.id == "cognee":
                status = await self._compile_cognee(provider, asset, segments, context)
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
        self,
        provider: Provider,
        asset: Asset,
        segments: tuple[Segment, ...],
        context,
    ) -> ProjectionStatus:
        try:
            runtime_model = await self._runtime_model(asset.tenant_id, context)
        except CogneeModelUnavailable as error:
            await self._mark_provider(provider, "degraded", str(error))
            return ProjectionStatus(
                tenant_id=asset.tenant_id,
                provider_id="cognee",
                subject_type="asset",
                subject_id=asset.id,
                operation="compile",
                status="failed",
                error=str(error),
            )
        health = await self._cognee.health(runtime_model)
        if health != "ok":
            error = self._cognee.health_reason or "Knowledge enrichment is not ready"
            if runtime_model is None and not self._static_llm():
                error = "Connect an AI provider to enable knowledge enrichment"
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
                source_ref=(f"knowledge://{asset.id}/{segment.revision_id}#{segment.id}"),
            )
            for segment in segments
        ]
        try:
            refs = await self._cognee.remember(
                asset.tenant_id,
                facts,
                runtime_model=runtime_model,
            )
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
        self,
        tenant_id: str,
        asset_id: str,
        segment_ids: list[str],
        context=None,
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for provider in await self._repository.list_providers(tenant_id):
            if provider.id not in SUPPORTED_PROVIDER_IDS or not provider.enabled:
                continue
            status = await self._erase_one(provider, tenant_id, asset_id, segment_ids, context)
            await self._repository.save_projection(status)
            results.append(_public_status(status))
        return results

    async def _erase_one(
        self,
        provider: Provider,
        tenant_id: str,
        asset_id: str,
        segment_ids: list[str],
        context,
    ) -> ProjectionStatus:
        try:
            if provider.id != "cognee":
                raise ValueError("credential-backed erasure adapter is not configured")
            runtime_model = await self._runtime_model(tenant_id, context)
            await self._cognee.forget(
                tenant_id,
                fact_ids=segment_ids,
                scopes=None,
                runtime_model=runtime_model,
            )
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

    async def _mark_provider(self, provider: Provider, health: str, error: str | None) -> None:
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
