"""Revisioned PostgreSQL persistence for governed model endpoints."""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
import json
from typing import TYPE_CHECKING, Any

import asyncpg  # type: ignore[import-untyped]

from boltrig.models import ModelEndpoint

from .model_endpoint_contract import (
    ModelEndpointReferenceSnapshot,
    canonical_model_endpoint_references,
    lock_model_endpoint_reference_graph,
)
from .rows import _endpoint


async def _reference_snapshot(
    conn: asyncpg.Connection, tenant_id: str, endpoint_id: str
) -> ModelEndpointReferenceSnapshot:
    capability_rows = await conn.fetch(
        """SELECT name, model_endpoint, vision_model_endpoint, model_routes
           FROM agent_capabilities
           WHERE tenant_id=$1
             AND (model_endpoint=$2 OR vision_model_endpoint=$2
                  OR EXISTS (
                    SELECT 1 FROM jsonb_each_text(
                      CASE WHEN jsonb_typeof(model_routes)='object'
                        THEN model_routes ELSE '{}'::jsonb END
                    ) AS route
                    WHERE route.value=$2
                  )
                  OR jsonb_typeof(model_routes)='string')""",
        tenant_id,
        endpoint_id,
    )
    capability_names = []
    for row in capability_rows:
        raw_routes = row["model_routes"]
        if isinstance(raw_routes, str):
            try:
                raw_routes = json.loads(raw_routes)
            except (TypeError, ValueError):
                raw_routes = {}
        route_values = (
            {str(value) for value in raw_routes.values()}
            if isinstance(raw_routes, dict)
            else set()
        )
        if (
            row["model_endpoint"] == endpoint_id
            or row["vision_model_endpoint"] == endpoint_id
            or endpoint_id in route_values
        ):
            capability_names.append(row["name"])
    fallback_rows = await conn.fetch(
        """SELECT id FROM model_endpoints
           WHERE tenant_id=$1 AND id<>$2 AND fallback=$2""",
        tenant_id,
        endpoint_id,
    )
    return canonical_model_endpoint_references(
        capability_names,
        (row["id"] for row in fallback_rows),
    )


class ModelEndpointStorePG:
    if TYPE_CHECKING:
        _pool: Any

        def with_tenant(
            self, tenant_id: str
        ) -> AbstractAsyncContextManager[asyncpg.Connection]: ...

    async def upsert_model_endpoint(self, endpoint: ModelEndpoint) -> None:
        async with self.with_tenant(endpoint.tenant_id) as conn:
            await lock_model_endpoint_reference_graph(conn, endpoint.tenant_id)
            current = await conn.fetchrow(
                """SELECT fallback FROM model_endpoints
                   WHERE tenant_id=$1 AND id=$2""",
                endpoint.tenant_id,
                endpoint.id,
            )
            old_fallback = current["fallback"] if current is not None else None
            await conn.execute(
                """INSERT INTO model_endpoints
                     (id, tenant_id, kind, base_url, model, fallback, data_class,
                      is_active, modalities)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
                   ON CONFLICT (tenant_id, id) DO UPDATE SET
                     kind=EXCLUDED.kind, base_url=EXCLUDED.base_url,
                     model=EXCLUDED.model, fallback=EXCLUDED.fallback,
                     data_class=EXCLUDED.data_class,
                     modalities=EXCLUDED.modalities,
                     revision=model_endpoints.revision+1, updated_at=now()""",
                endpoint.id,
                endpoint.tenant_id,
                endpoint.kind,
                endpoint.base_url,
                endpoint.model,
                endpoint.fallback,
                endpoint.data_class,
                endpoint.is_active,
                list(endpoint.modalities),
            )
            changed_fallbacks = (
                {
                    item
                    for item in (old_fallback, endpoint.fallback)
                    if item is not None and item != endpoint.id
                }
                if old_fallback != endpoint.fallback
                else set()
            )
            if changed_fallbacks:
                await conn.execute(
                    """UPDATE model_endpoints
                       SET revision=revision+1, updated_at=now()
                       WHERE tenant_id=$1 AND id=ANY($2::text[])""",
                    endpoint.tenant_id,
                    sorted(changed_fallbacks),
                )

    async def compare_and_upsert_model_endpoint(
        self,
        endpoint: ModelEndpoint,
        expected: ModelEndpoint | None,
        *,
        expected_fallback: ModelEndpoint | None,
        expected_references: ModelEndpointReferenceSnapshot,
    ) -> bool:
        async with self.with_tenant(endpoint.tenant_id) as conn:
            await lock_model_endpoint_reference_graph(conn, endpoint.tenant_id)
            current: ModelEndpoint | None = _endpoint(  # type: ignore[no-untyped-call]
                await conn.fetchrow(
                    "SELECT * FROM model_endpoints WHERE tenant_id=$1 AND id=$2",
                    endpoint.tenant_id,
                    endpoint.id,
                )
            )
            fallback = None
            if endpoint.fallback is not None:
                fallback = _endpoint(  # type: ignore[no-untyped-call]
                    await conn.fetchrow(
                        "SELECT * FROM model_endpoints WHERE tenant_id=$1 AND id=$2",
                        endpoint.tenant_id,
                        endpoint.fallback,
                    )
                )
            if current != expected or fallback != expected_fallback or (
                fallback is not None and not fallback.is_active
            ):
                return False
            if await _reference_snapshot(
                conn, endpoint.tenant_id, endpoint.id
            ) != expected_references:
                return False
            inserted = await conn.fetchval(
                """INSERT INTO model_endpoints
                     (id, tenant_id, kind, base_url, model, fallback, data_class,
                      is_active, modalities, revision)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
                   ON CONFLICT (tenant_id, id) DO UPDATE SET
                     kind=EXCLUDED.kind, base_url=EXCLUDED.base_url,
                     model=EXCLUDED.model, fallback=EXCLUDED.fallback,
                     data_class=EXCLUDED.data_class,
                     modalities=EXCLUDED.modalities,
                     revision=model_endpoints.revision+1, updated_at=now()
                   RETURNING id""",
                endpoint.id,
                endpoint.tenant_id,
                endpoint.kind,
                endpoint.base_url,
                endpoint.model,
                endpoint.fallback,
                endpoint.data_class,
                current.is_active if current else endpoint.is_active,
                list(endpoint.modalities),
                1 if current is None else current.revision + 1,
            )
            old_fallback = current.fallback if current is not None else None
            affected_fallbacks = {
                item
                for item in (old_fallback, endpoint.fallback)
                if item is not None and item != endpoint.id
            }
            if affected_fallbacks:
                await conn.execute(
                    """UPDATE model_endpoints
                       SET revision=revision+1, updated_at=now()
                       WHERE tenant_id=$1 AND id=ANY($2::text[])""",
                    endpoint.tenant_id,
                    sorted(affected_fallbacks),
                )
            return inserted is not None

    async def get_model_endpoint(
        self, tenant_id: str, endpoint_id: str
    ) -> ModelEndpoint | None:
        row = await self._pool.fetchrow(
            "SELECT * FROM model_endpoints WHERE tenant_id=$1 AND id=$2",
            tenant_id,
            endpoint_id,
        )
        return _endpoint(row)  # type: ignore[no-any-return,no-untyped-call]

    async def list_model_endpoints(self, tenant_id: str) -> list[ModelEndpoint]:
        rows = await self._pool.fetch(
            "SELECT * FROM model_endpoints WHERE tenant_id=$1 ORDER BY id", tenant_id
        )
        endpoints = [_endpoint(row) for row in rows]  # type: ignore[no-untyped-call]
        return [endpoint for endpoint in endpoints if endpoint is not None]

    async def model_endpoint_references(
        self, tenant_id: str, endpoint_id: str
    ) -> ModelEndpointReferenceSnapshot:
        async with self.with_tenant(tenant_id) as conn:
            await lock_model_endpoint_reference_graph(conn, tenant_id)
            return await _reference_snapshot(conn, tenant_id, endpoint_id)

    async def set_model_endpoint_active(
        self, tenant_id: str, endpoint_id: str, active: bool
    ) -> ModelEndpoint | None:
        async with self.with_tenant(tenant_id) as conn:
            await lock_model_endpoint_reference_graph(conn, tenant_id)
            row = await conn.fetchrow(
                """UPDATE model_endpoints SET is_active=$3, revision=revision+1,
                          updated_at=now()
                   WHERE tenant_id=$1 AND id=$2 RETURNING *""",
                tenant_id,
                endpoint_id,
                bool(active),
            )
        return _endpoint(row)  # type: ignore[no-any-return,no-untyped-call]

    async def compare_and_set_model_endpoint_active(
        self,
        tenant_id: str,
        endpoint_id: str,
        active: bool,
        expected: ModelEndpoint,
    ) -> ModelEndpoint | None:
        if expected.tenant_id != tenant_id or expected.id != endpoint_id:
            return None
        async with self.with_tenant(tenant_id) as conn:
            await lock_model_endpoint_reference_graph(conn, tenant_id)
            current: ModelEndpoint | None = _endpoint(  # type: ignore[no-untyped-call]
                await conn.fetchrow(
                    "SELECT * FROM model_endpoints WHERE tenant_id=$1 AND id=$2",
                    tenant_id,
                    endpoint_id,
                )
            )
            if current != expected:
                return None
            row = await conn.fetchrow(
                """UPDATE model_endpoints SET is_active=$3, revision=revision+1,
                          updated_at=now()
                   WHERE tenant_id=$1 AND id=$2 RETURNING *""",
                tenant_id,
                endpoint_id,
                bool(active),
            )
        return _endpoint(row)  # type: ignore[no-any-return,no-untyped-call]


__all__ = ["ModelEndpointStorePG"]
