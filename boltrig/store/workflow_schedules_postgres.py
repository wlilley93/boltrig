"""PostgreSQL workflow schedule desired state and occurrence receipts."""

from __future__ import annotations

from boltrig.models import GrantSet
from boltrig.models.workflow_schedules import (
    WorkflowSchedule,
    WorkflowScheduleOccurrence,
)


def _schedule(row) -> WorkflowSchedule | None:
    if row is None:
        return None
    return WorkflowSchedule(
        tenant_id=row["tenant_id"],
        workflow_id=row["workflow_id"],
        workspace_id=row["workspace_id"],
        cron=row["cron"],
        timezone=row["timezone"],
        authority_subject=row["authority_subject"],
        grant_ceiling=GrantSet.of(list(row["grant_allow"] or []), list(row["grant_deny"] or [])),
        observed_status=row["observed_status"],
        observed_reason=row["observed_reason"],
        next_due_at=row["next_due_at"],
        last_scheduled_for=row["last_scheduled_for"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        observed_at=row["observed_at"],
    )


def _occurrence(row) -> WorkflowScheduleOccurrence | None:
    if row is None:
        return None
    return WorkflowScheduleOccurrence(
        tenant_id=row["tenant_id"],
        workflow_id=row["workflow_id"],
        scheduled_for=row["scheduled_for"],
        run_id=row["run_id"],
        status=row["status"],
        lease_owner=row["lease_owner"],
        lease_expires_at=row["lease_expires_at"],
        engine_run_id=row["engine_run_id"],
        reason=row["reason"],
        attempts=int(row["attempts"]),
        workflow_sha256=row["workflow_sha256"],
        schedule_sha256=row["schedule_sha256"],
        claimed_at=row["claimed_at"],
        enqueued_at=row["enqueued_at"],
        outcome_at=row["outcome_at"],
        manual_retries=int(row["manual_retries"]),
        last_retry_at=row["last_retry_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class WorkflowScheduleStorePG:
    async def upsert_workflow_schedule(self, schedule):
        row = await self._pool.fetchrow(
            """INSERT INTO workflow_schedules
                 (tenant_id,workflow_id,workspace_id,cron,timezone,
                  authority_subject,grant_allow,grant_deny,observed_status,
                  observed_reason,next_due_at,last_scheduled_for,created_at,
                  updated_at,observed_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,
                       COALESCE($13,now()),COALESCE($14,now()),$15)
               ON CONFLICT (tenant_id,workflow_id) DO UPDATE SET
                 workspace_id=EXCLUDED.workspace_id,
                 cron=EXCLUDED.cron,
                 timezone=EXCLUDED.timezone,
                 authority_subject=EXCLUDED.authority_subject,
                 grant_allow=EXCLUDED.grant_allow,
                 grant_deny=EXCLUDED.grant_deny,
                 observed_status=EXCLUDED.observed_status,
                 observed_reason=EXCLUDED.observed_reason,
                 next_due_at=EXCLUDED.next_due_at,
                 last_scheduled_for=NULL,
                 updated_at=now(),
                 observed_at=EXCLUDED.observed_at
               RETURNING *""",
            schedule.tenant_id,
            schedule.workflow_id,
            schedule.workspace_id,
            schedule.cron,
            schedule.timezone,
            schedule.authority_subject,
            list(schedule.grant_ceiling.allow),
            list(schedule.grant_ceiling.deny),
            schedule.observed_status,
            schedule.observed_reason,
            schedule.next_due_at,
            schedule.last_scheduled_for,
            schedule.created_at,
            schedule.updated_at,
            schedule.observed_at,
        )
        return _schedule(row)

    async def get_workflow_schedule(self, tenant_id, workflow_id):
        row = await self._pool.fetchrow(
            """SELECT * FROM workflow_schedules
               WHERE tenant_id=$1 AND workflow_id=$2""",
            tenant_id,
            workflow_id,
        )
        return _schedule(row)

    async def list_workflow_schedules(self, tenant_id):
        rows = await self._pool.fetch(
            """SELECT * FROM workflow_schedules
               WHERE tenant_id=$1 ORDER BY workflow_id""",
            tenant_id,
        )
        return [_schedule(row) for row in rows]

    async def delete_workflow_schedule(self, tenant_id, workflow_id):
        await self._pool.execute(
            """DELETE FROM workflow_schedules
               WHERE tenant_id=$1 AND workflow_id=$2""",
            tenant_id,
            workflow_id,
        )

    async def observe_workflow_schedule(self, tenant_id, workflow_id, *, status, reason):
        row = await self._pool.fetchrow(
            """UPDATE workflow_schedules
                  SET observed_status=$3,observed_reason=$4,
                      observed_at=now(),updated_at=now()
                WHERE tenant_id=$1 AND workflow_id=$2 RETURNING *""",
            tenant_id,
            workflow_id,
            status,
            reason,
        )
        return _schedule(row)

    async def advance_workflow_schedule(
        self,
        tenant_id,
        workflow_id,
        *,
        expected_due_at,
        next_due_at,
        last_scheduled_for,
        status,
        reason,
    ):
        row = await self._pool.fetchrow(
            """UPDATE workflow_schedules
                  SET next_due_at=$4,last_scheduled_for=$5,
                      observed_status=$6,observed_reason=$7,
                      observed_at=now(),updated_at=now()
                WHERE tenant_id=$1 AND workflow_id=$2
                  AND next_due_at=$3
                RETURNING workflow_id""",
            tenant_id,
            workflow_id,
            expected_due_at,
            next_due_at,
            last_scheduled_for,
            status,
            reason,
        )
        return row is not None

    async def claim_workflow_schedule_occurrence(self, occurrence, *, lease_seconds):
        row = await self._pool.fetchrow(
            """INSERT INTO workflow_schedule_occurrences
                 (tenant_id,workflow_id,scheduled_for,run_id,status,lease_owner,
                  lease_expires_at,attempts,workflow_sha256,schedule_sha256,
                  claimed_at,created_at,updated_at)
               VALUES ($1,$2,$3,$4,'claimed',$5,
                       now()+($6 * interval '1 second'),1,$7,$8,now(),
                       COALESCE($9,now()),COALESCE($10,now()))
               ON CONFLICT (tenant_id,workflow_id,scheduled_for) DO UPDATE SET
                 status='claimed',
                 lease_owner=EXCLUDED.lease_owner,
                 lease_expires_at=EXCLUDED.lease_expires_at,
                 attempts=workflow_schedule_occurrences.attempts+1,
                 claimed_at=now(),
                 updated_at=now()
               WHERE (
                    workflow_schedule_occurrences.status='retryable'
                    OR (
                    workflow_schedule_occurrences.status='claimed'
                    AND workflow_schedule_occurrences.lease_expires_at <= now()
                    )
                  )
                 AND workflow_schedule_occurrences.run_id=EXCLUDED.run_id
                 AND workflow_schedule_occurrences.workflow_sha256
                       =EXCLUDED.workflow_sha256
                 AND workflow_schedule_occurrences.schedule_sha256
                       =EXCLUDED.schedule_sha256
               RETURNING *""",
            occurrence.tenant_id,
            occurrence.workflow_id,
            occurrence.scheduled_for,
            occurrence.run_id,
            occurrence.lease_owner,
            max(1, int(lease_seconds)),
            occurrence.workflow_sha256,
            occurrence.schedule_sha256,
            occurrence.created_at,
            occurrence.updated_at,
        )
        if row is not None:
            return _occurrence(row), True
        existing = await self._pool.fetchrow(
            """SELECT * FROM workflow_schedule_occurrences
               WHERE tenant_id=$1 AND workflow_id=$2 AND scheduled_for=$3""",
            occurrence.tenant_id,
            occurrence.workflow_id,
            occurrence.scheduled_for,
        )
        return _occurrence(existing), False

    async def get_workflow_schedule_occurrence(self, tenant_id, workflow_id, scheduled_for):
        row = await self._pool.fetchrow(
            """SELECT * FROM workflow_schedule_occurrences
               WHERE tenant_id=$1 AND workflow_id=$2 AND scheduled_for=$3""",
            tenant_id,
            workflow_id,
            scheduled_for,
        )
        return _occurrence(row)

    async def list_workflow_schedule_occurrences(self, tenant_id, workflow_id, *, limit):
        rows = await self._pool.fetch(
            """SELECT * FROM workflow_schedule_occurrences
               WHERE tenant_id=$1 AND workflow_id=$2
               ORDER BY scheduled_for DESC
               LIMIT $3""",
            tenant_id,
            workflow_id,
            max(1, min(int(limit), 51)),
        )
        return [_occurrence(row) for row in rows]

    async def list_recoverable_workflow_schedule_occurrences(self, tenant_id, *, limit):
        rows = await self._pool.fetch(
            """SELECT * FROM workflow_schedule_occurrences
               WHERE tenant_id=$1
                 AND (
                   status='retryable'
                   OR (
                     status='claimed'
                     AND lease_expires_at <= now()
                   )
                 )
               ORDER BY updated_at,workflow_id,scheduled_for
               LIMIT $2""",
            tenant_id,
            max(1, min(int(limit), 100)),
        )
        return [_occurrence(row) for row in rows]

    async def request_workflow_schedule_occurrence_retry(
        self,
        tenant_id,
        workflow_id,
        scheduled_for,
        *,
        run_id,
        workflow_sha256,
        schedule_sha256,
        max_manual_retries,
    ):
        row = await self._pool.fetchrow(
            """UPDATE workflow_schedule_occurrences
                  SET status='retryable',reason='manual_retry_requested',
                      manual_retries=manual_retries+1,last_retry_at=now(),
                      outcome_at=NULL,updated_at=now()
                WHERE tenant_id=$1 AND workflow_id=$2 AND scheduled_for=$3
                  AND status='failed' AND run_id=$4
                  AND workflow_sha256=$5 AND schedule_sha256=$6
                  AND manual_retries < $7
                RETURNING *""",
            tenant_id,
            workflow_id,
            scheduled_for,
            run_id,
            workflow_sha256,
            schedule_sha256,
            max(0, int(max_manual_retries)),
        )
        return _occurrence(row)

    async def finish_workflow_schedule_occurrence(
        self,
        tenant_id,
        workflow_id,
        scheduled_for,
        *,
        lease_owner,
        status,
        engine_run_id,
        reason,
    ):
        row = await self._pool.fetchrow(
            """UPDATE workflow_schedule_occurrences
                  SET status=$5,engine_run_id=$6,reason=$7,
                      enqueued_at=CASE WHEN $5='queued' THEN now()
                                       ELSE enqueued_at END,
                      outcome_at=CASE WHEN $5='failed' THEN now()
                                      ELSE outcome_at END,
                      lease_owner=NULL,lease_expires_at=NULL,updated_at=now()
                WHERE tenant_id=$1 AND workflow_id=$2 AND scheduled_for=$3
                  AND lease_owner=$4 AND status='claimed'
                RETURNING workflow_id""",
            tenant_id,
            workflow_id,
            scheduled_for,
            lease_owner,
            status,
            engine_run_id,
            reason,
        )
        return row is not None

    async def finish_workflow_schedule_outcome(self, tenant_id, run_id, *, status, reason):
        if status not in {"succeeded", "failed"}:
            return False
        row = await self._pool.fetchrow(
            """UPDATE workflow_schedule_occurrences
                  SET status=$3,reason=$4,outcome_at=now(),
                      enqueued_at=COALESCE(enqueued_at,now()),
                      lease_owner=NULL,lease_expires_at=NULL,updated_at=now()
                WHERE tenant_id=$1 AND run_id=$2
                  AND (
                    status IN ('claimed','queued')
                    OR (status='failed' AND $3='succeeded')
                  )
                RETURNING workflow_id""",
            tenant_id,
            run_id,
            status,
            reason,
        )
        return row is not None


__all__ = ["WorkflowScheduleStorePG"]
