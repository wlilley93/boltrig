"""PostgreSQL persistence for the durable run-effect ledger (0085)."""

from __future__ import annotations

import json

from boltrig.models import RunEffect

from .tenant_scope import bind_conn_to_tenant


def _effect_from_row(row) -> RunEffect:
    raw = row["inverse_params"]
    return RunEffect(
        tenant_id=row["tenant_id"],
        run_id=row["run_id"],
        seq=row["seq"],
        verb_id=row["verb_id"],
        status=row["status"],
        inverse_verb=row["inverse_verb"],
        inverse_params=json.loads(raw) if isinstance(raw, str) else dict(raw or {}),
        summary=row["summary"],
        created_at=row["created_at"],
    )


class EffectLedgerStorePG:
    async def record_run_effect(self, effect: RunEffect) -> RunEffect:
        """Append with the run's next seq, atomically.

        The seq is computed inside the INSERT so two concurrent recorders
        cannot both claim it; the primary key makes a lost race an error
        rather than a silent overwrite.
        """
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await bind_conn_to_tenant(conn, effect.tenant_id, pool=self._pool)
                row = await conn.fetchrow(
                    """INSERT INTO run_effects
                         (tenant_id,run_id,seq,verb_id,status,inverse_verb,
                          inverse_params,summary,created_at)
                       SELECT $1,$2,
                              COALESCE(MAX(seq),0)+1,
                              $3,$4,$5,$6::jsonb,$7,now()
                         FROM run_effects
                        WHERE tenant_id=$1 AND run_id=$2
                       RETURNING *""",
                    effect.tenant_id,
                    effect.run_id,
                    effect.verb_id,
                    effect.status,
                    effect.inverse_verb,
                    json.dumps(effect.inverse_params),
                    effect.summary,
                )
        return _effect_from_row(row)

    async def list_run_effects(self, tenant_id: str, run_id: str) -> list[RunEffect]:
        async with self._pool.acquire() as conn:
            await bind_conn_to_tenant(conn, tenant_id, pool=self._pool)
            rows = await conn.fetch(
                """SELECT * FROM run_effects
                    WHERE tenant_id=$1 AND run_id=$2
                    ORDER BY seq ASC""",
                tenant_id,
                run_id,
            )
        return [_effect_from_row(row) for row in rows]

    async def settle_run_effect(
        self, tenant_id: str, run_id: str, seq: int, *, expected: str, status: str
    ) -> bool:
        """CAS one row's status; False = someone else settled it first.

        The guard is what makes a concurrent double-revert impossible: only
        one caller wins the recorded -> terminal transition, so an inverse
        can never execute twice (the same run-once property revertible.py
        gets by clearing its in-process list).
        """
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await bind_conn_to_tenant(conn, tenant_id, pool=self._pool)
                tag = await conn.execute(
                    """UPDATE run_effects SET status=$5
                        WHERE tenant_id=$1 AND run_id=$2 AND seq=$3 AND status=$4""",
                    tenant_id,
                    run_id,
                    seq,
                    expected,
                    status,
                )
        return tag.endswith("1")
