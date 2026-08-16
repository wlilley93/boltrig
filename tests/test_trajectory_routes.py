"""The trajectory HTTP surface: read, export, purge -- all gated on run visibility.

WHY THE GATE IS THE INTERESTING PART. This stream carries more than any other
run-scoped surface: the whole prompt and the whole tool payload, unscrubbed.
Serving it on tenancy alone would let anyone in an organisation read the
verbatim contents of anyone else's run, so it uses the same
``visible_work_item_by_run`` check the existing run-event streams use.

A run with no visible work item is 404 EVEN IF ROWS EXIST. That is deliberate
and it is a real constraint on the feature: a trajectory is readable through
the API only for runs the caller can already see. Recording is not the same as
being allowed to read.
"""

import json

import pytest
from fastapi.testclient import TestClient

from boltrig.models import TrajectoryKind, WorkItem


TENANT = "default"
HEADERS = {
    "x-boltrig-tenant": TENANT,
    "x-boltrig-grants": "*",
    "x-boltrig-subject": "u1",
}


@pytest.fixture()
def client(monkeypatch):
    for key in ("DATABASE_URL", "ENV", "BOLTRIG_ENV", "APP_ENV", "BOLTRIG_PRODUCTION"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("BOLTRIG_MANIFEST", "manifest.example.yaml")
    monkeypatch.setenv("BOLTRIG_DEV_AUTH", "1")
    monkeypatch.setenv("BOLTRIG_TRAJECTORY", "1")
    from boltrig.api.bootstrap import build_app

    with TestClient(build_app()) as c:
        yield c


async def _seed(kernel, run_id: str, *, with_work_item: bool = True) -> None:
    if with_work_item:
        await kernel.store.create_work_item(
            WorkItem(
                id=f"wi-{run_id}",
                tenant_id=TENANT,
                source="internal",
                intent="trajectory fixture",
                confidence=1.0,
                convergent=True,
                hatchet_run_id=run_id,
            )
        )
    await kernel.trajectory_store.append_trajectory(
        TENANT, run_id, TrajectoryKind.PROMPT, {"text": "why did it say that"}
    )
    await kernel.trajectory_store.append_trajectory(
        TENANT, run_id, TrajectoryKind.TOOL_CALL,
        {"verb": "ticket.create", "params": {"title": "verbatim"}},
    )


def _kernel(client):
    return client.app.state.kernel


@pytest.mark.asyncio
async def test_reading_a_visible_run_returns_its_events_in_sequence(client):
    await _seed(_kernel(client), "run-visible")
    body = client.get("/v1/trajectory/run-visible", headers=HEADERS).json()
    assert [e["seq"] for e in body["events"]] == [1, 2]
    assert body["events"][0]["kind"] == "prompt"
    # VERBATIM: the params survive the round trip, which is the whole feature.
    assert body["events"][1]["payload"]["params"] == {"title": "verbatim"}
    assert body["complete"] is True


@pytest.mark.asyncio
async def test_a_run_with_no_visible_work_item_is_not_readable(client):
    """404, not 403: saying "exists but not yours" leaks other people's activity."""
    await _seed(_kernel(client), "run-hidden", with_work_item=False)
    assert client.get("/v1/trajectory/run-hidden", headers=HEADERS).status_code == 404
    assert client.get("/v1/trajectory/run-hidden/export", headers=HEADERS).status_code == 404
    assert client.delete("/v1/trajectory/run-hidden", headers=HEADERS).status_code == 404


@pytest.mark.asyncio
async def test_export_is_one_json_object_per_line(client):
    await _seed(_kernel(client), "run-export")
    response = client.get("/v1/trajectory/run-export/export", headers=HEADERS)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    assert "run-export.jsonl" in response.headers["content-disposition"]

    lines = [line for line in response.text.splitlines() if line.strip()]
    assert len(lines) == 2
    rows = [json.loads(line) for line in lines]
    assert [row["seq"] for row in rows] == [1, 2]
    # Self-describing, and carrying no tenant: an export is scoped by where it
    # came from, not by a field a reader might treat as portable.
    assert "tenant_id" not in rows[0]


@pytest.mark.asyncio
async def test_after_seq_resumes_rather_than_offsets(client):
    await _seed(_kernel(client), "run-cursor")
    body = client.get("/v1/trajectory/run-cursor?after_seq=1", headers=HEADERS).json()
    assert [e["seq"] for e in body["events"]] == [2]
    assert body["next_seq"] == 2


@pytest.mark.asyncio
async def test_purge_deletes_the_verbatim_record(client):
    """Available to whoever can read it: this stream exists to be disposable."""
    kernel = _kernel(client)
    await _seed(kernel, "run-purge")
    assert client.delete("/v1/trajectory/run-purge", headers=HEADERS).json()["deleted"] == 2
    assert await kernel.trajectory_store.read_trajectory(TENANT, "run-purge") == []


@pytest.mark.asyncio
async def test_the_listing_reports_whether_recording_is_on(client):
    await _seed(_kernel(client), "run-listed")
    body = client.get("/v1/trajectory", headers=HEADERS).json()
    assert "run-listed" in body["runs"]
    # The client needs to distinguish "no runs recorded" from "recording is off",
    # which look identical from an empty list.
    assert body["enabled"] is True
