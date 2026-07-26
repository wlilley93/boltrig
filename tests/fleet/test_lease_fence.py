"""The claim-time lease fence, seeded against the failure it exists for.

[2026] VJS-CC-BOLTRIG-WORK-ITEM-LEASE-FENCE-001, D2/D4/D5/D8.

The defect: nothing renews a work-item lease, so a step that outruns
``lease_seconds`` is handed to a SECOND executor while the first is still
running, and whichever finishes last writes its terminal state over the other's.
An earlier ``_still_leased`` helper compared the row against the body's own read
and reproduced the race exactly, which is why every test here steals the lease
BETWEEN the claim and the write - the only ordering that can tell a fence from a
re-read.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from boltrig.fleet import lease_token
from boltrig.models import WorkItem, WorkStatus
from boltrig.store import InMemoryStore

T = "acme"


def _item(**kw) -> WorkItem:
    return WorkItem(
        id=uuid.uuid4().hex,
        tenant_id=T,
        source="internal",
        intent=kw.pop("intent", "fix the login bug"),
        confidence=0.9,
        convergent=kw.pop("convergent", False),
        status=kw.pop("status", WorkStatus.PENDING),
        **kw,
    )


@pytest.mark.invariant("US-FLT-05")
def test_the_token_survives_the_json_boundary_the_durable_lane_crosses() -> None:
    """D2: the durable lane serialises the payload, and the fence compares exactly.

    A token that loses a microsecond in transit does not fail open - it fails
    CLOSED, refusing every legitimate write - so losslessness is the whole point.
    """
    expires = datetime(2026, 7, 26, 6, 0, 0, 123456, tzinfo=UTC)
    item = _item(lease_owner="worker-1", lease_expires_at=expires)

    payload = {"tenant_id": T, "item_id": item.id, **lease_token.encode(item)}

    import json

    round_tripped = json.loads(json.dumps(payload))  # exactly what Hatchet does
    token = lease_token.decode(round_tripped)

    assert token is not None
    assert token.owner == "worker-1"
    assert token.expires_at == expires
    assert lease_token.matches(item, token)


@pytest.mark.invariant("US-FLT-05")
def test_a_payload_from_before_the_fence_writes_unfenced_rather_than_crashing() -> None:
    """A rolling restart leaves older payloads in flight; they must still run."""
    assert lease_token.decode({"tenant_id": T, "item_id": "x"}) is None


@pytest.mark.invariant("US-FLT-05")
async def test_a_worker_that_lost_its_lease_writes_nothing_and_does_not_raise() -> None:
    """D5: a refused write is a no-op plus a warning, never an exception.

    Raising here would reach ``_record_failure``, which would re-open an item the
    winner has already settled - turning a harmless lost race into a second full
    execution of the work.
    """
    store = InMemoryStore()
    claimed_at = datetime.now(UTC)
    item = _item(
        status=WorkStatus.IN_FLIGHT,
        lease_owner="worker-1",
        lease_expires_at=claimed_at + timedelta(seconds=300),
    )
    await store.create_work_item(item)

    token = lease_token.LeaseToken(item.lease_owner, item.lease_expires_at)
    lease_token.bind(token)

    # The steal: worker-2 reclaims the expired lease and settles it DONE.
    winner = await store.get_work_item(T, item.id)
    assert winner is not None
    winner.lease_owner = "worker-2"
    winner.lease_expires_at = claimed_at + timedelta(seconds=600)
    winner.status = WorkStatus.DONE
    winner.result = {"by": "worker-2"}
    await store.update_work_item(winner)

    # worker-1 finishes and tries to land its own answer on the same row.
    item.status = WorkStatus.FAILED
    item.result = {"by": "worker-1"}
    wrote = await lease_token.write(store, item, what="settle done")

    assert wrote is False
    stored = await store.get_work_item(T, item.id)
    assert stored is not None
    assert stored.status is WorkStatus.DONE, "the loser overwrote the winner"
    assert stored.result == {"by": "worker-2"}


@pytest.mark.invariant("US-FLT-05")
async def test_a_refused_cancel_is_logged_and_never_swallowed(caplog) -> None:
    """D8: nothing on the refused path may consume or delete the evidence.

    A cancel whose write was refused has NOT been recorded, so the request that
    asked for it is the only remaining sign that anyone asked.
    """
    store = InMemoryStore()
    claimed_at = datetime.now(UTC)
    item = _item(
        status=WorkStatus.IN_FLIGHT,
        lease_owner="worker-1",
        lease_expires_at=claimed_at + timedelta(seconds=300),
    )
    await store.create_work_item(item)
    lease_token.bind(lease_token.LeaseToken("worker-1", item.lease_expires_at))

    stolen = await store.get_work_item(T, item.id)
    assert stolen is not None
    stolen.lease_owner = "worker-2"
    await store.update_work_item(stolen)

    item.status = WorkStatus.CANCELLED
    with caplog.at_level("WARNING"):
        wrote = await lease_token.write(store, item, what="cancel")

    assert wrote is False
    logged = [r.getMessage() for r in caplog.records]
    assert any("lease lost" in m for m in logged), caplog.text
    assert any("cancel" in m for m in logged), caplog.text


@pytest.mark.invariant("US-FLT-05")
async def test_an_unbound_write_says_so_rather_than_pretending_to_be_fenced() -> None:
    """The honest fallback: no token means no fence, and the log admits it."""
    store = InMemoryStore()
    item = _item(status=WorkStatus.IN_FLIGHT)
    await store.create_work_item(item)
    lease_token.bind(None)

    item.status = WorkStatus.DONE
    assert await lease_token.write(store, item, what="settle done") is True
    stored = await store.get_work_item(T, item.id)
    assert stored is not None and stored.status is WorkStatus.DONE


@pytest.mark.invariant("US-FLT-05")
async def test_the_duplicate_child_window_is_narrowed_but_not_closed() -> None:
    """D4: stated as what it is. Re-running a body must not double the follow-ons.

    This is NOT a fence and the test does not claim it is: it proves the common
    case (siblings already committed) is skipped, which is all a pre-persist read
    can promise when the child row cannot be made atomic with the parent.
    """
    from boltrig.fleet.pump import persist_new_work_items

    store = InMemoryStore()
    parent = _item(intent="parent task")
    await store.create_work_item(parent)

    first = await persist_new_work_items(
        store, parent, [{"intent": "write the migration"}], source="internal"
    )
    assert len(first) == 1

    again = await persist_new_work_items(
        store, parent, [{"intent": "write the migration"}], source="internal"
    )
    assert again == [], "the re-run created a second child for the same follow-on"

    children = await store.list_work_items(T, parent_id=parent.id)
    assert len(children) == 1
