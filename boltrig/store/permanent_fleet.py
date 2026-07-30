"""Permanent-fleet worker observation store contract and adapters."""

from __future__ import annotations

from typing import Protocol

from boltrig.models import PermanentFleetObservation


class PermanentFleetStoreContract(Protocol):
    async def upsert_permanent_fleet_observation(
        self, observation: PermanentFleetObservation
    ) -> None: ...

    async def list_permanent_fleet_observations(
        self, tenant_id: str
    ) -> list[PermanentFleetObservation]: ...


class PermanentFleetStoreMem:
    async def upsert_permanent_fleet_observation(self, observation):
        self._permanent_fleet_observations[
            (observation.tenant_id, observation.worker_id)
        ] = observation

    async def list_permanent_fleet_observations(self, tenant_id):
        return sorted(
            [
                observation
                for (row_tenant, _), observation
                in self._permanent_fleet_observations.items()
                if row_tenant == tenant_id
            ],
            key=lambda observation: observation.worker_id,
        )


def _observation(row):
    if row is None:
        return None
    return PermanentFleetObservation(
        tenant_id=row["tenant_id"],
        worker_id=row["worker_id"],
        generation=row["generation"],
        status=row["status"],
        apply_mode=row["apply_mode"],
        applied_fields=list(row["applied_fields"] or []),
        inactive_fields=list(row["inactive_fields"] or []),
        observed_at=row["observed_at"],
    )


class PermanentFleetStorePG:
    async def upsert_permanent_fleet_observation(self, observation):
        await self._pool.execute(
            """INSERT INTO permanent_fleet_observations
                 (tenant_id, worker_id, generation, status, apply_mode,
                  applied_fields, inactive_fields, observed_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7,COALESCE($8, now()))
               ON CONFLICT (tenant_id, worker_id) DO UPDATE SET
                 generation=EXCLUDED.generation,
                 status=EXCLUDED.status,
                 apply_mode=EXCLUDED.apply_mode,
                 applied_fields=EXCLUDED.applied_fields,
                 inactive_fields=EXCLUDED.inactive_fields,
                 observed_at=EXCLUDED.observed_at""",
            observation.tenant_id,
            observation.worker_id,
            observation.generation,
            observation.status,
            observation.apply_mode,
            observation.applied_fields,
            observation.inactive_fields,
            observation.observed_at,
        )

    async def list_permanent_fleet_observations(self, tenant_id):
        rows = await self._pool.fetch(
            """SELECT * FROM permanent_fleet_observations
               WHERE tenant_id=$1 ORDER BY worker_id""",
            tenant_id,
        )
        return [_observation(row) for row in rows]
