"""Honest background-health evidence across janitors, readiness and platform."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from boltrig.api.background_readiness import read_background_job_readiness
from boltrig.api import worker as worker_mod
from boltrig.fleet.retention import run_retention_forever
from boltrig.kernel import Kernel
from boltrig.kernel.app import create_app
from boltrig.kernel.hitl_expiry import run_hitl_expiry_sweep
from boltrig.models import Organisation, utcnow
from boltrig.observability.background_jobs import project_background_job_receipts
from boltrig.store import InMemoryStore

T = "acme"
PROCESS = "bjp_aaaaaaaaaaaaaaaaaaaaaaaa"


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-34")
async def test_janitor_loops_record_attempts_and_only_a_safe_failure_code():
    store = InMemoryStore()
    await store.create_org(Organisation(id=T, name="Acme", slug="acme"))
    assert await run_hitl_expiry_sweep(
        store,
        process_instance_identity=PROCESS,
        interval=60,
    ) == 0
    hitl = (await store.list_background_job_receipts(T))[0]
    assert hitl.job_name == "hitl_expiry"
    assert hitl.last_outcome == "succeeded"

    raw_error = "postgres://private-host password=do-not-project"

    async def fail_purge(*args, **kwargs):
        raise RuntimeError(raw_error)

    store.purge_closed_conversations = fail_purge  # type: ignore[method-assign]
    task = asyncio.create_task(
        run_retention_forever(
            store,
            T,
            interval=0.01,
            process_instance_identity=PROCESS,
        )
    )
    try:
        for _ in range(200):
            rows = await store.list_background_job_receipts(T)
            if any(row.job_name == "retention" for row in rows):
                break
            await asyncio.sleep(0.01)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    retention = next(
        row
        for row in await store.list_background_job_receipts(T)
        if row.job_name == "retention"
    )
    assert retention.last_outcome == "failed"
    assert retention.failure_code == "sweep_failed"
    assert raw_error not in repr(retention)


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-34")
async def test_worker_correlates_both_jobs_with_one_random_process_identity(
    monkeypatch,
):
    seen: dict[str, str | None] = {}
    monkeypatch.setenv("BOLTRIG_HITL_EXPIRY_INTERVAL", "60")
    monkeypatch.setenv("BOLTRIG_RETENTION_INTERVAL", "3600")

    async def hitl_forever(store, *, interval, process_instance_identity):
        seen["hitl_expiry"] = process_instance_identity
        await asyncio.Event().wait()

    async def retention_forever(
        store,
        tenant_id,
        retention_days,
        *,
        interval,
        process_instance_identity,
    ):
        seen["retention"] = process_instance_identity
        await asyncio.Event().wait()

    import boltrig.kernel.hitl_expiry as hitl_expiry

    monkeypatch.setattr(hitl_expiry, "run_hitl_expiry_forever", hitl_forever)
    monkeypatch.setattr(worker_mod, "run_retention_forever", retention_forever)
    expiry = worker_mod._start_hitl_expiry_janitor(object(), PROCESS)
    retention = worker_mod._start_retention_janitor(object(), T, None, PROCESS)
    assert expiry is not None and retention is not None
    try:
        for _ in range(100):
            if len(seen) == 2:
                break
            await asyncio.sleep(0)
        assert seen == {"hitl_expiry": PROCESS, "retention": PROCESS}
    finally:
        expiry.cancel()
        retention.cancel()
        await asyncio.gather(expiry, retention, return_exceptions=True)


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-34")
async def test_readiness_is_optional_attempt_evidence_not_a_liveness_claim():
    store = InMemoryStore()
    attempted_at = utcnow()
    await store.record_background_job_attempt(
        tenant_id=T,
        job_name="retention",
        process_instance_identity=PROCESS,
        interval_seconds=3600,
        attempted_at=attempted_at,
        succeeded=True,
        item_count=2,
    )
    checks = await read_background_job_readiness(store, T, timeout_s=0.5)
    retention = checks["retention_janitor"]
    assert retention["status"] == "ok"
    assert retention["required"] is False
    assert retention["proves_liveness"] is False
    assert retention["process_coverage"] == "bounded_receipts_not_replica_inventory"
    assert checks["hitl_expiry_janitor"]["reason"] == "attempt_evidence_not_observed"

    stale = project_background_job_receipts(
        await store.list_background_job_receipts(T),
        now=attempted_at + timedelta(hours=3),
    )[0]
    assert stale["state"] == "stale_succeeded_evidence"
    assert stale["proves_liveness"] is False


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-34")
def test_authenticated_platform_projection_is_tenant_scoped_and_opaque():
    store = InMemoryStore()
    now = utcnow()
    asyncio.run(
        store.record_background_job_attempt(
            tenant_id=T,
            job_name="hitl_expiry",
            process_instance_identity=PROCESS,
            interval_seconds=60,
            attempted_at=now,
            succeeded=True,
            item_count=4,
        )
    )
    asyncio.run(
        store.record_background_job_attempt(
            tenant_id="other",
            job_name="retention",
            process_instance_identity="bjp_bbbbbbbbbbbbbbbbbbbbbbbb",
            interval_seconds=3600,
            attempted_at=now,
            succeeded=False,
            item_count=0,
        )
    )
    client = TestClient(create_app(Kernel(store), platform={}))
    response = client.get(
        "/v1/platform/status",
        headers={
            "x-boltrig-tenant": T,
            "x-boltrig-subject": "alice",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["background_job_evidence"] == {
        "status": "available",
        "evidence_kind": "bounded_attempt_receipt_not_liveness",
        "proves_liveness": False,
        "process_coverage": "bounded_receipts_not_replica_inventory",
        "max_retained_process_receipts_per_job": 4,
        # DELIBERATELY A LITERAL, not len(BACKGROUND_JOB_NAMES) * 4. Deriving it
        # would make this assertion unable to notice a change in what the
        # authenticated projection exposes, which is the one thing it is here to
        # catch. It moved 8 -> 12 on 2026-07-30 when `distillation` was registered
        # as a third background job, and this test is how that surfaced.
        "max_returned_receipts": 12,
    }
    assert [row["process_instance_identity"] for row in body["background_jobs"]] == [
        PROCESS
    ]
    serialised = response.text.lower()
    # Check the actual sensitive values and recipient/provider-shaped material.
    # ``password_reset_delivery`` is the legitimate, safe job name and must not
    # make this evidence test fail merely because it contains "password".
    for sensitive in ("private-host", "do-not-project"):
        assert sensitive not in serialised
    reset_evidence = body["password_reset_delivery"]
    assert {
        "recipient",
        "recipient_address",
        "provider",
        "provider_receipt",
        "provider_message_id",
        "message",
        "secret",
        "token",
    }.isdisjoint(reset_evidence)


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-34")
def test_worker_copy_never_upgrades_attempt_receipts_to_process_health():
    source = (
        Path(__file__).resolve().parents[2]
        / "apps/worker/src/components/OperationsView.tsx"
    ).read_text(encoding="utf-8")
    assert "they are not heartbeats" in source
    assert "do not prove current liveness or complete replica coverage" in source
    assert "Maintenance attempt evidence is unavailable" in source

    root = Path(__file__).resolve().parents[2]
    migration = (
        root / "migrations/versions/0059_background_job_receipts.py"
    ).read_text(encoding="utf-8")
    schema = (root / "boltrig/store/schema.sql").read_text(encoding="utf-8")
    rls = (root / "boltrig/store/rls.sql").read_text(encoding="utf-8")
    primary_key = (
        "PRIMARY KEY (\n"
        "              tenant_id,job_name,process_instance_identity\n"
        "            )"
    )
    assert primary_key in migration
    assert "process_instance_identity" in schema
    assert "FORCE ROW LEVEL SECURITY" in migration
    assert "'background_job_receipts'" in rls
    store_source = (root / "boltrig/store/background_jobs.py").read_text(
        encoding="utf-8"
    )
    pg_read = store_source.rsplit(
        "async def list_background_job_receipts(self, tenant_id):",
        maxsplit=1,
    )[1]
    # The readiness read holds its OWN transaction, so it must bind the tenant
    # itself. It used to do that with a bare set_config, which under a superuser
    # owner set the GUC and left the policy unconsulted - measured 2026-07-31 at 22
    # sites. bind_conn_to_tenant switches role AND sets the GUC, so requiring the
    # helper by name is strictly stronger than the literal this asserted before: an
    # inline set_config would now fail both here and in
    # tests/security/test_rls_covers_explicit_transactions.py.
    assert "bind_conn_to_tenant(" in pg_read, (
        "the readiness read must bind through the shared helper; a bare "
        "set_config leaves the transaction unfenced"
    )
    assert "LIMIT $2" in pg_read


def test_the_sql_check_constraint_admits_exactly_BACKGROUND_JOB_NAMES():
    """The tuple and the CHECK enumerate the same names, or writes fail silently.

    Registering a loop in BACKGROUND_JOB_NAMES is not enough: background_job_receipts
    carries a CHECK that lists the names independently. On 2026-07-30 `distillation`
    was added to the tuple and not the constraint, so every receipt write was refused
    by Postgres - and because attempt recording is deliberately best-effort, the sweep
    carried on while its evidence never existed. /readyz then reports
    `attempt_evidence_not_observed`, which reads as "nothing has happened yet" rather
    than "the write is broken".

    The in-memory store has no constraint, so unit tests passed throughout and only
    the deployment showed it. This gate is static: it reads schema.sql, so it fails on
    a laptop with no database, at the moment the tuple and the DDL diverge.
    """
    import re
    from pathlib import Path

    from boltrig.models import BACKGROUND_JOB_NAMES

    schema = (
        Path(__file__).resolve().parents[2] / "boltrig" / "store" / "schema.sql"
    ).read_text(encoding="utf-8")
    match = re.search(r"CHECK \(job_name IN \(([^)]*)\)\)", schema)
    assert match, "the job_name CHECK constraint is not in schema.sql any more"

    in_sql = {piece.strip().strip("'") for piece in match.group(1).split(",")}
    assert in_sql == set(BACKGROUND_JOB_NAMES), (
        f"schema.sql admits {sorted(in_sql)} but BACKGROUND_JOB_NAMES is "
        f"{sorted(BACKGROUND_JOB_NAMES)} - a name in one and not the other means "
        f"receipts are silently refused (tuple-only) or unreachable (SQL-only)"
    )


def test_an_unknown_job_name_costs_one_row_not_the_whole_readiness_surface():
    """A newer process's receipt must not blind an older one to every job.

    BackgroundJobReceipt validates job_name against BACKGROUND_JOB_NAMES, so a row
    written by a newer build raised ValueError while mapping rows and took the ENTIRE
    read down. Readiness then reported `attempt_evidence_unavailable` for EVERY job,
    including healthy ones.

    Measured on the beelink 2026-07-30: registering `distillation` and rolling only
    the fleet image left the kernel unable to read ANY receipt. Adding a job name was
    therefore not backward compatible, and during a rolling deploy the whole readiness
    surface went dark rather than degrading.

    Dropping the unknown row costs visibility of one job on an old build, which is the
    right trade against losing all of them - and it is logged, never silent.
    """
    from datetime import datetime, timezone

    from boltrig.store.background_jobs import _receipts_skipping_unknown

    at = datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)
    known = {
        "tenant_id": T,
        "job_name": "retention",
        "process_instance_identity": PROCESS,
        "interval_seconds": 3600,
        "last_attempt_at": at,
        "last_success_at": at,
        "last_failure_at": None,
        "last_outcome": "succeeded",
        "failure_code": None,
        "last_item_count": 3,
        "receipt_kind": "attempt_history_not_liveness",
    }
    unknown = {**known, "job_name": "a-job-this-build-has-never-heard-of"}

    out = _receipts_skipping_unknown([known, unknown, known])

    assert len(out) == 2, "the unknown row must be dropped, the known ones kept"
    assert {r.job_name for r in out} == {"retention"}
