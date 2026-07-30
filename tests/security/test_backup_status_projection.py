"""Backup freshness is bounded evidence, never artifact or liveness access."""

from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.testclient import TestClient

from boltrig.kernel import Kernel
from boltrig.kernel.app import Principal, create_app
from boltrig.observability.backup_status import backup_status
from boltrig.store import InMemoryStore


def test_backup_status_classifies_bounded_success_marker(tmp_path: Path) -> None:
    marker = tmp_path / "last-success"
    marker.write_text("1000\n", encoding="ascii")

    fresh = backup_status(
        str(marker),
        interval_seconds=100,
        grace_seconds=20,
        now_epoch=1120,
    )
    assert fresh["state"] == "fresh"
    assert fresh["age_seconds"] == 120
    assert fresh["last_success_at"] == "1970-01-01T00:16:40+00:00"
    assert fresh["liveness_claimed"] is False
    assert fresh["restore_readiness"] == "unavailable_no_restore_drill_receipt"

    stale = backup_status(
        str(marker),
        interval_seconds=100,
        grace_seconds=20,
        now_epoch=1121,
    )
    assert stale["state"] == "stale"
    assert stale["age_seconds"] == 121


def test_backup_status_rejects_missing_malformed_and_future_markers(
    tmp_path: Path,
) -> None:
    marker = tmp_path / "last-success"
    assert backup_status(
        str(marker),
        interval_seconds=100,
        grace_seconds=20,
        now_epoch=1000,
    )["state"] == "never_observed"

    marker.write_text("not-an-epoch\n", encoding="ascii")
    assert backup_status(
        str(marker),
        interval_seconds=100,
        grace_seconds=20,
        now_epoch=1000,
    )["state"] == "invalid_marker"

    marker.write_text("1001\n", encoding="ascii")
    assert backup_status(
        str(marker),
        interval_seconds=100,
        grace_seconds=20,
        now_epoch=1000,
    )["state"] == "invalid_marker"


def test_backup_route_is_authenticated_and_does_not_disclose_artifacts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    marker = tmp_path / "last-success"
    marker.write_text("1000\n", encoding="ascii")
    monkeypatch.setenv("BOLTRIG_BACKUP_HEALTH_FILE", str(marker))
    monkeypatch.setenv("BACKUP_INTERVAL", "100")
    monkeypatch.setenv("BACKUP_HEALTH_GRACE", "20")

    async def resolver(request: Request) -> Principal:
        if request.headers.get("authorization") != "Bearer member-session":
            raise HTTPException(status_code=401, detail="invalid session")
        return Principal(tenant_id="acme", subject="alice", role="member")

    client = TestClient(
        create_app(Kernel(InMemoryStore()), principal_resolver=resolver)
    )

    assert client.get("/v1/backup/status").status_code == 401
    response = client.get(
        "/v1/backup/status",
        headers={"authorization": "Bearer member-session"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["backup"]["evidence_kind"] == "shared_success_marker"
    assert body["backup"]["off_box_state"] == "unknown_not_in_marker"
    rendered = response.text
    assert str(tmp_path) not in rendered
    assert "artifact" not in rendered
