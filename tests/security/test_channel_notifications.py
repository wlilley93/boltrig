"""Channel notification round-trip (decision 0003, Phase 2; SEC-179): a HITL
approval / escalation and a run completion reach the user's BOUND channel
surface through the durable outbox, addressed back to the thread the
triggering message came from. Delivery is preference-driven data
(notification_prefs), gated by kernel-authoritative bindings, and honest about
its edges: no binding, a disabled pref, or a non-socket channel enqueues
nothing.
"""

import asyncio

import pytest

from boltrig.kernel.channel_notify import (
    enqueue_user_notification,
    notify_work_item_result,
)
from boltrig.kernel.hitl import HITLManager
from boltrig.models import (
    Channel,
    ChannelBinding,
    HITLType,
    NotificationPref,
    User,
    WorkItem,
    WorkStatus,
)
from boltrig.store import InMemoryStore

T = "acme"


async def _store() -> InMemoryStore:
    store = InMemoryStore()
    await store.upsert_channel(
        Channel(id="ch-s1", tenant_id=T, platform="slack", name="Ops", transport="socket")
    )
    # a webhook-class channel for the same platform family is NOT an outbox
    # consumer - the direct path belongs to channel.send, not to notifications
    await store.upsert_channel(
        Channel(id="ch-w1", tenant_id=T, platform="slack", name="Hook", transport="webhook")
    )
    await store.upsert_channel_binding(
        ChannelBinding(id="b-1", tenant_id=T, channel_id="ch-s1", platform="slack",
                       external_user_id="U-9", subject="alice", role="member")
    )
    await store.upsert_channel_binding(
        ChannelBinding(id="b-2", tenant_id=T, channel_id="ch-w1", platform="slack",
                       external_user_id="U-9w", subject="alice", role="member")
    )
    return store


async def _pref(store, event_type: str, *, subject="alice", enabled=True, target=None):
    await store.upsert_notification_pref(
        NotificationPref(
            id=f"np-{event_type}-{subject}-{enabled}", tenant_id=T, scope_kind="user",
            scope_ref=subject, event_type=event_type, channel="slack",
            target=target, enabled=enabled,
        )
    )


async def _claimed(store):
    return await store.claim_channel_outbox(T, ["ch-s1", "ch-w1"], "test", 60, 20)


@pytest.mark.security
@pytest.mark.invariant("SEC-179")
def test_hitl_approval_reaches_the_bound_surface():
    store = asyncio.run(_store())
    asyncio.run(_pref(store, "approval"))
    hitl = HITLManager(store)
    req = asyncio.run(hitl.create(
        T, "run-1", HITLType.APPROVAL, "Approve the deploy?",
        verb="deploy.run", requested_by="cos-agent",
        request_fingerprint="fp-1", requested_on_behalf_of="alice",
    ))
    assert req.id
    (msg,) = asyncio.run(_claimed(store))
    assert msg.channel_id == "ch-s1"  # the socket-class bound surface only
    assert msg.payload["event"] == "approval"
    assert msg.payload["subject"] == "alice"
    assert msg.payload["text"] == "Approve the deploy?"
    assert msg.payload["target"] == "U-9"  # no thread context: the bound sender


@pytest.mark.security
@pytest.mark.invariant("SEC-179")
def test_no_pref_no_binding_or_disabled_means_no_delivery():
    store = asyncio.run(_store())
    hitl = HITLManager(store)
    # no pref at all
    asyncio.run(hitl.create(T, "r1", HITLType.ESCALATION, "q1", requested_by="cos"))
    # a disabled pref
    asyncio.run(_pref(store, "escalation", enabled=False))
    asyncio.run(hitl.create(T, "r2", HITLType.ESCALATION, "q2", requested_by="alice"))
    # a pref for a user with NO binding on the channel
    asyncio.run(_pref(store, "escalation", subject="mallory"))
    asyncio.run(hitl.create(T, "r3", HITLType.ESCALATION, "q3", requested_by="mallory"))
    assert asyncio.run(_claimed(store)) == []


@pytest.mark.security
@pytest.mark.invariant("SEC-179")
def test_run_completion_returns_to_the_originating_thread():
    store = asyncio.run(_store())
    # the pref names a home thread, but the ROUND TRIP wins: the notice goes
    # back to the thread the triggering message came from
    asyncio.run(_pref(store, "work_status", target="C-home"))
    item = WorkItem(
        id="w-1", tenant_id=T, source="slack", intent="deploy", confidence=0.9,
        convergent=True, status=WorkStatus.DONE, on_behalf_of="alice",
        target="cos",
        reply_route={"channel_id": "ch-s1", "thread": "C-ops", "sender": "U-9"},
    )
    enqueued = asyncio.run(notify_work_item_result(store, item))
    assert len(enqueued) == 1
    (msg,) = asyncio.run(_claimed(store))
    assert msg.payload["target"] == "C-ops"  # round-trip integrity
    assert msg.payload["event"] == "work_status"
    # a non-channel item (no human origin / no reply route) notifies no one
    orphan = WorkItem(id="w-2", tenant_id=T, source="jira", intent="x",
                      confidence=0.5, convergent=True, status=WorkStatus.DONE)
    assert asyncio.run(notify_work_item_result(store, orphan)) == []
    assert asyncio.run(_claimed(store)) == []


@pytest.mark.security
@pytest.mark.invariant("SEC-179")
def test_direct_enqueue_is_user_scoped_and_event_matched():
    store = asyncio.run(_store())
    asyncio.run(_pref(store, "budget_alert"))
    # a different event type does not match the pref
    assert asyncio.run(
        enqueue_user_notification(store, T, "alice", "error", "boom")) == []
    # a team-scoped pref resolves to the team's members - with no users in the
    # store it addresses no one
    asyncio.run(store.upsert_notification_pref(
        NotificationPref(id="np-team", tenant_id=T, scope_kind="team", scope_ref="eng",
                         event_type="error", channel="slack")
    ))
    assert asyncio.run(
        enqueue_user_notification(store, T, "alice", "error", "boom")) == []
    # the matching one lands
    assert asyncio.run(
        enqueue_user_notification(store, T, "alice", "budget_alert", "over")) != []


async def _user(store, subject: str, departments: list[str], *, status="active"):
    await store.upsert_user(
        User(id=subject, tenant_id=T, scope={"departments": departments}, status=status)
    )


@pytest.mark.security
@pytest.mark.invariant("SEC-179")
def test_team_pref_reaches_exactly_the_bound_members():
    store = asyncio.run(_store())  # ch-s1 socket/slack, alice bound to it
    # bob: eng member, bound. carol: eng member, UNBOUND. dave: bound but
    # another team. eve: eng member, bound but deactivated.
    asyncio.run(store.upsert_channel_binding(
        ChannelBinding(id="b-3", tenant_id=T, channel_id="ch-s1", platform="slack",
                       external_user_id="U-bob", subject="bob", role="member")))
    asyncio.run(store.upsert_channel_binding(
        ChannelBinding(id="b-4", tenant_id=T, channel_id="ch-s1", platform="slack",
                       external_user_id="U-dave", subject="dave", role="member")))
    asyncio.run(store.upsert_channel_binding(
        ChannelBinding(id="b-5", tenant_id=T, channel_id="ch-s1", platform="slack",
                       external_user_id="U-eve", subject="eve", role="member")))
    asyncio.run(_user(store, "alice", ["eng"]))
    asyncio.run(_user(store, "bob", ["eng"]))
    asyncio.run(_user(store, "carol", ["eng"]))
    asyncio.run(_user(store, "dave", ["sales"]))
    asyncio.run(_user(store, "eve", ["eng"], status="deactivated"))
    asyncio.run(store.upsert_notification_pref(
        NotificationPref(id="np-team-eng", tenant_id=T, scope_kind="team",
                         scope_ref="eng", event_type="error", channel="slack")))
    enqueued = asyncio.run(enqueue_user_notification(store, T, "alice", "error", "boom"))
    assert len(enqueued) == 2
    msgs = asyncio.run(_claimed(store))
    # exactly the ACTIVE, BOUND eng members hear it - carol (unbound), dave
    # (another team) and eve (deactivated) do not
    assert {m.payload["subject"] for m in msgs} == {"alice", "bob"}
    assert {m.payload["target"] for m in msgs} == {"U-9", "U-bob"}


@pytest.mark.security
@pytest.mark.invariant("SEC-179")
def test_team_pref_disabled_or_memberless_delivers_nothing():
    store = asyncio.run(_store())
    asyncio.run(_user(store, "alice", ["eng"]))
    # a DISABLED team pref addresses no one
    asyncio.run(store.upsert_notification_pref(
        NotificationPref(id="np-team-off", tenant_id=T, scope_kind="team",
                         scope_ref="eng", event_type="error", channel="slack",
                         enabled=False)))
    assert asyncio.run(
        enqueue_user_notification(store, T, "alice", "error", "boom")) == []
    # an enabled pref for a team with no members delivers nothing either
    asyncio.run(store.upsert_notification_pref(
        NotificationPref(id="np-team-empty", tenant_id=T, scope_kind="team",
                         scope_ref="ops", event_type="error", channel="slack")))
    assert asyncio.run(
        enqueue_user_notification(store, T, "alice", "error", "boom")) == []
    assert asyncio.run(_claimed(store)) == []
