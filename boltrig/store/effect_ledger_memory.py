"""In-memory twin of :mod:`effect_ledger_postgres` (store parity)."""

from __future__ import annotations

from dataclasses import replace

from boltrig.models import RunEffect


class EffectLedgerStoreMem:
    def _effect_rows(self) -> dict[tuple[str, str], list[RunEffect]]:
        rows = getattr(self, "_run_effects", None)
        if rows is None:
            rows = {}
            self._run_effects = rows
        return rows

    async def record_run_effect(self, effect: RunEffect) -> RunEffect:
        bucket = self._effect_rows().setdefault(
            (effect.tenant_id, effect.run_id), []
        )
        stamped = replace(effect, seq=len(bucket) + 1)
        bucket.append(stamped)
        return stamped

    async def list_run_effects(self, tenant_id: str, run_id: str) -> list[RunEffect]:
        # Copy-on-read, like every other twin: Postgres builds each row fresh
        # from JSON, so handing out the live dict here would let a caller
        # mutate stored inverse params that PG callers cannot.
        return [
            replace(row, inverse_params=dict(row.inverse_params))
            for row in self._effect_rows().get((tenant_id, run_id), [])
        ]

    async def settle_run_effect(
        self, tenant_id: str, run_id: str, seq: int, *, expected: str, status: str
    ) -> bool:
        bucket = self._effect_rows().get((tenant_id, run_id), [])
        for index, row in enumerate(bucket):
            if row.seq == seq and row.status == expected:
                bucket[index] = replace(row, status=status)
                return True
        return False
