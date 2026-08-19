"""Detached, revisioned in-memory model endpoint persistence."""

from __future__ import annotations

from dataclasses import replace
from threading import Lock

from boltrig.models import ModelEndpoint

from .model_endpoint_contract import (
    ModelEndpointReferenceSnapshot,
    canonical_model_endpoint_references,
)


class ModelEndpointStoreMem:
    def _init_model_endpoint_state(self) -> None:
        self._endpoints: dict[tuple[str, str], ModelEndpoint] = {}
        self._model_endpoint_lock = Lock()

    def _model_endpoint_references_locked(
        self, tenant_id: str, endpoint_id: str
    ) -> ModelEndpointReferenceSnapshot:
        return canonical_model_endpoint_references(
            # Names, deduped, exactly as the PostgreSQL twin does. Two
            # same-named capabilities in different workspaces therefore collapse
            # to one entry: the snapshot is a compare-and-set fingerprint that is
            # SERIALISED INTO A GOVERNED APPROVAL CONTEXT
            # (ModelEndpointReferenceSnapshot.parse_approval_context), so widening
            # it to scope-qualified names would invalidate every in-flight
            # model-endpoint approval. Both stores lose the same precision in the
            # same way, so parity holds; the residue is that retiring one of two
            # same-named references leaves the fingerprint unchanged.
            (
                capability.name
                for key, capability in self._caps.items()
                if key[0] == tenant_id
                and (
                    capability.model_endpoint == endpoint_id
                    or capability.vision_model_endpoint == endpoint_id
                    or endpoint_id in capability.model_routes.values()
                )
            ),
            (
                endpoint.id
                for (tenant, _), endpoint in self._endpoints.items()
                if tenant == tenant_id
                and endpoint.id != endpoint_id
                and endpoint.fallback == endpoint_id
            ),
        )

    def _bump_model_endpoint_revisions_locked(
        self, tenant_id: str, endpoint_ids: set[str]
    ) -> None:
        for endpoint_id in sorted(endpoint_ids):
            key = (tenant_id, endpoint_id)
            endpoint = self._endpoints.get(key)
            if endpoint is not None:
                self._endpoints[key] = replace(
                    endpoint, revision=endpoint.revision + 1
                )

    async def upsert_model_endpoint(self, endpoint: ModelEndpoint) -> None:
        key = (endpoint.tenant_id, endpoint.id)
        with self._model_endpoint_lock:
            existing = self._endpoints.get(key)
            self._endpoints[key] = replace(
                endpoint,
                is_active=existing.is_active if existing else endpoint.is_active,
                revision=existing.revision + 1 if existing else 1,
            )
            old_fallback = existing.fallback if existing is not None else None
            changed_fallbacks = (
                {
                    item
                    for item in (old_fallback, endpoint.fallback)
                    if item is not None and item != endpoint.id
                }
                if old_fallback != endpoint.fallback
                else set()
            )
            self._bump_model_endpoint_revisions_locked(
                endpoint.tenant_id, changed_fallbacks
            )

    async def compare_and_upsert_model_endpoint(
        self,
        endpoint: ModelEndpoint,
        expected: ModelEndpoint | None,
        *,
        expected_fallback: ModelEndpoint | None,
        expected_references: ModelEndpointReferenceSnapshot,
    ) -> bool:
        key = (endpoint.tenant_id, endpoint.id)
        with self._model_endpoint_lock:
            existing = self._endpoints.get(key)
            if existing != expected:
                return False
            fallback = (
                self._endpoints.get((endpoint.tenant_id, endpoint.fallback))
                if endpoint.fallback is not None else None
            )
            if fallback != expected_fallback or (
                fallback is not None and not fallback.is_active
            ):
                return False
            if self._model_endpoint_references_locked(
                endpoint.tenant_id, endpoint.id
            ) != expected_references:
                return False
            self._endpoints[key] = replace(
                endpoint,
                is_active=existing.is_active if existing else endpoint.is_active,
                revision=existing.revision + 1 if existing else 1,
            )
            old_fallback = existing.fallback if existing is not None else None
            affected_fallbacks = {
                item
                for item in (old_fallback, endpoint.fallback)
                if item is not None and item != endpoint.id
            }
            self._bump_model_endpoint_revisions_locked(
                endpoint.tenant_id, affected_fallbacks
            )
            return True

    async def get_model_endpoint(
        self, tenant_id: str, endpoint_id: str
    ) -> ModelEndpoint | None:
        endpoint = self._endpoints.get((tenant_id, endpoint_id))
        return replace(endpoint) if endpoint is not None else None

    async def list_model_endpoints(self, tenant_id: str) -> list[ModelEndpoint]:
        return [
            replace(row)
            for (tenant, _), row in self._endpoints.items()
            if tenant == tenant_id
        ]

    async def model_endpoint_references(
        self, tenant_id: str, endpoint_id: str
    ) -> ModelEndpointReferenceSnapshot:
        with self._model_endpoint_lock:
            return self._model_endpoint_references_locked(tenant_id, endpoint_id)

    async def set_model_endpoint_active(
        self, tenant_id: str, endpoint_id: str, active: bool
    ) -> ModelEndpoint | None:
        key = (tenant_id, endpoint_id)
        with self._model_endpoint_lock:
            endpoint = self._endpoints.get(key)
            if endpoint is None:
                return None
            stored = replace(
                endpoint, is_active=bool(active), revision=endpoint.revision + 1
            )
            self._endpoints[key] = stored
            return replace(stored)

    async def compare_and_set_model_endpoint_active(
        self,
        tenant_id: str,
        endpoint_id: str,
        active: bool,
        expected: ModelEndpoint,
    ) -> ModelEndpoint | None:
        key = (tenant_id, endpoint_id)
        with self._model_endpoint_lock:
            endpoint = self._endpoints.get(key)
            if endpoint is None or endpoint != expected:
                return None
            stored = replace(
                endpoint, is_active=bool(active), revision=endpoint.revision + 1
            )
            self._endpoints[key] = stored
            return replace(stored)


__all__ = ["ModelEndpointStoreMem"]
