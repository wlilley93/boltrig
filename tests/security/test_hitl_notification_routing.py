"""HITL approval notice follows eligibility (SEC-179, SEC-14; [2026]
VJS-CC-BOLTRIG-HITL-NOTIFICATION-ROUTING-001, D1-D3).

HITL-NOTIFICATION-ROUTING-001 D5: every test in this module was seeded red
against the pre-fix kernel (the cure reverted); the red runs are recorded in
the discharge note.

``_notify_request`` addressed only ``assignee or requested_on_behalf_of or
requested_by`` - an operator-raised approval notified its raiser and never the
only lawful approver. The notice set is now derived from ONE eligibility
definition shared with ``authorize_approval_response`` (non-initiator, human,
assignee-consistent, live grant, the sole-author exemption applied
identically), deduplicated against the legacy subject, fail-safe as ever: a
notifier or eligibility fault never voids the recorded request, and no
authorization path reads notification state.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from boltrig.identity.provisioning import current_grants_for_user
from boltrig.kernel import Kernel
from boltrig.kernel.app import Principal
from boltrig.kernel.hitl import HITLManager
from boltrig.kernel import hitl_response_auth
from boltrig.kernel.hitl_response_auth import authorize_approval_response
from boltrig.models import (
    Channel,
    ChannelBinding,
    GrantSet,
    HITLStatus,
    HITLType,
    NotificationPref,
    TenantPermissions,
    User,
)
from boltrig.store import InMemoryStore

T = "cv"
VERB = "control.invitation.create"
OPERATOR = "op@classicalvisas.com"
CLIENT = "info@classicalvisas.com"


def _store() -> InMemoryStore:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    return store


def _seat(store, subject: str, role: str, scope: dict | None = None,
          status: str = "active") -> User:
    user = User(
        id=subject, tenant_id=T, email=subject, role=role,
        scope={"all": True} if scope is None else scope, status=status,
    )
    asyncio.run(store.upsert_user(user))
    return user


def _principal(user: User) -> Principal:
    """The principal the resolver would build for this user at the door."""
    return Principal(
        tenant_id=user.tenant_id,
        subject=user.id,
        grants=current_grants_for_user(user),
        role=user.role,
        actor_tier="human",
        scope=user.scope,
        # A person who authenticated at a door. Principal defaults this to
        # "machine" so an unlabelled resolver is refused, which means a test
        # modelling a human must say so - otherwise it silently models a bot and
        # the route refuses where a real user would be admitted.
        credential_kind="session",
    )


def _bind(store, subject: str, external: str) -> None:
    async def go():
        await store.upsert_channel(
            Channel(id="ch-s1", tenant_id=T, platform="slack", name="Ops",
                    transport="socket")
        )
        await store.upsert_channel_binding(
            ChannelBinding(id=f"b-{subject}", tenant_id=T, channel_id="ch-s1",
                           platform="slack", external_user_id=external,
                           subject=subject, role="member")
        )
    asyncio.run(go())


def _pref(store, subject: str) -> None:
    asyncio.run(store.upsert_notification_pref(
        NotificationPref(
            id=f"np-approval-{subject}", tenant_id=T, scope_kind="user",
            scope_ref=subject, event_type="approval", channel="slack",
            enabled=True,
        )
    ))


def _claimed(store):
    return asyncio.run(store.claim_channel_outbox(T, ["ch-s1"], "test", 60, 20))


def _raise(hitl: HITLManager, requested_by: str, *, assignee: str | None = None,
           fp: str = "fp-1"):
    return asyncio.run(hitl.create(
        T, f"run-{fp}", HITLType.APPROVAL, f"Approve {VERB} ?",
        verb=VERB, requested_by=requested_by, request_fingerprint=fp,
        assignee=assignee,
    ))


def _admitted(kernel: Kernel, request, users: list[User]) -> set[str]:
    """The set the RESPONSE ROUTE admits, asked user by user."""
    admitted = set()
    for user in users:
        try:
            asyncio.run(authorize_approval_response(kernel, _principal(user), request))
        except HTTPException:
            continue
        admitted.add(user.id)
    return admitted


@pytest.mark.security
@pytest.mark.invariant("SEC-179")
def test_operator_raised_approval_reaches_the_client_author():
    """HITL-NOTIFICATION-ROUTING-001 D1: two active authors, no assignee,
    EMPTY prefs for the raiser - the client (the only lawful approver) is
    enqueued anyway; delivery prefs govern the channel layer, never the
    eligibility computation."""
    store = _store()
    _seat(store, OPERATOR, "superadmin")
    _seat(store, CLIENT, "admin")
    _bind(store, OPERATOR, "U-op")
    _bind(store, CLIENT, "U-client")
    _pref(store, CLIENT)  # the raiser has NO prefs - the live CV posture

    req = _raise(HITLManager(store), OPERATOR)

    assert req.status == HITLStatus.PENDING
    (msg,) = _claimed(store)
    assert msg.payload["event"] == "approval"
    assert msg.payload["subject"] == CLIENT


@pytest.mark.security
@pytest.mark.invariant("SEC-179")
def test_notice_set_equals_the_response_route_set():
    """HITL-NOTIFICATION-ROUTING-001 D2: ONE shared derivation - the notified
    set IS the set authorize_approval_response admits, across the whole
    eligibility matrix: initiator, grant missing, deactivated, assignee
    mismatch, lapsed exemption, sole-author exempt. A role-based or duplicated
    rule goes red:
    member-granted holds the verb's live grant without an author-tier role,
    and the response route admits them, so the notice set must too."""
    store = _store()
    users = [
        _seat(store, OPERATOR, "superadmin"),
        _seat(store, CLIENT, "admin"),
        _seat(store, "nogrant@cv", "admin", scope={}),
        _seat(store, "ghost@cv", "admin", status="deactivated"),
        _seat(store, "member-granted@cv", "member", scope={"verbs": [VERB]}),
    ]
    kernel = Kernel(store)
    hitl = kernel.hitl

    # no assignee: everyone but the initiator and the grant-less is eligible
    req = _raise(hitl, OPERATOR)
    assert set(asyncio.run(hitl_response_auth.eligible_approval_responders(store, req))) == _admitted(
        kernel, req, users
    ) == {CLIENT, "member-granted@cv"}

    # assignee-consistent: with an assignee set, every other user is refused
    assigned = _raise(hitl, OPERATOR, assignee=CLIENT, fp="fp-2")
    assert set(asyncio.run(hitl_response_auth.eligible_approval_responders(store, assigned))) == _admitted(
        kernel, assigned, users
    ) == {CLIENT}

    # the sole-author exemption applied identically: on a single-author tenant
    # the initiator IS eligible (exempt) and the notice set says so too
    solo = _store()
    will = _seat(solo, "will@solo", "superadmin")
    solo_kernel = Kernel(solo)
    own = _raise(solo_kernel.hitl, "will@solo")
    assert set(asyncio.run(hitl_response_auth.eligible_approval_responders(solo, own))) == _admitted(
        solo_kernel, own, [will]
    ) == {"will@solo"}
    assert asyncio.run(
        authorize_approval_response(solo_kernel, _principal(will), own)
    ) == "sole_author"  # the relief is now NAMED, not a bare True


@pytest.mark.security
@pytest.mark.invariant("SEC-179")
def test_notice_set_equals_the_route_set_UNDER_A_DEVELOPMENT_POSTURE(monkeypatch):
    """DEVELOPMENT-POSTURE-001 D6. The row this matrix was missing, and the reason it could not fail.

    ``eligible_approval_responders`` called ``approval_response_block`` without
    the posture, so notice was computed against ``posture=None`` while the route
    used the live one. Under a posture the route therefore admitted the initiator
    and the notice set never named them. Measured on the shipped code before the
    fix: notice ``['client@cv']``, route ``['client@cv', 'operator@cv']``.

    The matrix above stayed green throughout, because not one of its rows ever
    set a posture - a check that could not fail in the exact dimension the new
    code introduced. That is why this row exists rather than a broader assertion:
    the gap was a missing INPUT, and only an input can close it.
    """
    from datetime import datetime, timedelta, timezone

    from boltrig.config.dev_posture import DevelopmentPosture

    monkeypatch.setenv("BOLTRIG_ENV", "dev")
    for key in ("BOLTRIG_OIDC_ISSUER", "CF_ACCESS_TEAM_DOMAIN", "BOLTRIG_AUTH_MODE"):
        monkeypatch.delenv(key, raising=False)

    store = _store()
    users = [_seat(store, OPERATOR, "superadmin"), _seat(store, CLIENT, "admin")]
    kernel = Kernel(store)
    posture = DevelopmentPosture(
        enabled=True,
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        declared_by=OPERATOR, reason="pre-launch",
        covers=(OPERATOR, CLIENT),
    )
    kernel.hitl.development_posture = posture

    req = _raise(kernel.hitl, OPERATOR)
    notice = set(asyncio.run(
        hitl_response_auth.eligible_approval_responders(store, req, posture=posture)
    ))
    route = _admitted(kernel, req, users)
    assert notice == route, f"notice {sorted(notice)} != route {sorted(route)}"
    # And the initiator IS in it: under a live posture they may answer their own
    # request, so a notice set that omitted them would be the drift D2 forbids.
    assert OPERATOR in route


@pytest.mark.security
@pytest.mark.invariant("SEC-179")
def test_eligible_requester_is_not_double_notified():
    """HITL-NOTIFICATION-ROUTING-001 D1: the raiser who IS an eligible
    approver (sole author, exemption live) gets ONE notice, not two - dedup
    against the legacy subject."""
    store = _store()
    _seat(store, "will@solo", "superadmin")
    _bind(store, "will@solo", "U-will")
    _pref(store, "will@solo")

    _raise(HITLManager(store), "will@solo")

    (msg,) = _claimed(store)
    assert msg.payload["subject"] == "will@solo"


@pytest.mark.security
@pytest.mark.invariant("SEC-179")
def test_non_author_tier_and_grantless_users_are_not_notified():
    """HITL-NOTIFICATION-ROUTING-001 D2: eligibility is grant-based - a
    member WITHOUT the verb's live grant and
    a deactivated admin are refused by the response route, so the fan-out
    never addresses them - role alone confers nothing either way."""
    store = _store()
    _seat(store, OPERATOR, "superadmin")
    _seat(store, CLIENT, "admin")
    _seat(store, "viewer@cv", "member", scope={})
    _seat(store, "ghost@cv", "admin", status="deactivated")
    for subject, external in (
        (CLIENT, "U-client"), ("viewer@cv", "U-viewer"), ("ghost@cv", "U-ghost")
    ):
        _bind(store, subject, external)
        _pref(store, subject)

    _raise(HITLManager(store), OPERATOR)

    (msg,) = _claimed(store)
    assert msg.payload["subject"] == CLIENT


@pytest.mark.security
@pytest.mark.invariant("SEC-179")
def test_eligibility_fault_still_notifies_the_legacy_subject(monkeypatch):
    """HITL-NOTIFICATION-ROUTING-001 D3: an eligibility-sweep fault degrades
    to today's behaviour - the legacy subject is still enqueued and the
    recorded request stands."""
    store = _store()
    _seat(store, OPERATOR, "superadmin")
    _seat(store, CLIENT, "admin")
    _bind(store, OPERATOR, "U-op")
    _pref(store, OPERATOR)

    async def boom(_store, _req):
        raise RuntimeError("store lookup failed")

    monkeypatch.setattr(
        "boltrig.kernel.hitl_response_auth.eligible_approval_responders", boom
    )
    req = _raise(HITLManager(store), OPERATOR)

    assert req.status == HITLStatus.PENDING
    (msg,) = _claimed(store)
    assert msg.payload["subject"] == OPERATOR


@pytest.mark.security
@pytest.mark.invariant("SEC-179")
def test_enqueue_fault_never_voids_the_recorded_request(monkeypatch):
    """HITL-NOTIFICATION-ROUTING-001 D3: a notifier fault on the fan-out is
    a delivery gap, never a lost request - create still returns the recorded
    PENDING request."""
    store = _store()
    _seat(store, OPERATOR, "superadmin")
    _seat(store, CLIENT, "admin")

    async def boom(*_args, **_kwargs):
        raise RuntimeError("outbox down")

    monkeypatch.setattr(
        "boltrig.kernel.channel_notify.enqueue_user_notification", boom
    )
    req = _raise(HITLManager(store), OPERATOR)

    assert req.status == HITLStatus.PENDING
    stored = asyncio.run(HITLManager(store).get(T, req.id))
    assert stored is not None and stored.status == HITLStatus.PENDING


@pytest.mark.security
@pytest.mark.invariant("SEC-14")
@pytest.mark.invariant("SEC-179")
def test_authorization_never_reads_notification_state():
    """HITL-NOTIFICATION-ROUTING-001 D3: authorize_approval_response and
    consume_approved_by behave identically with an empty and a populated
    outbox - notification is a side channel, never an input to an
    authorization decision."""
    def flow(with_delivery: bool):
        store = _store()
        _seat(store, OPERATOR, "superadmin")
        client = _seat(store, CLIENT, "admin")
        if with_delivery:
            _bind(store, CLIENT, "U-client")
            _pref(store, CLIENT)
        kernel = Kernel(store)
        req = _raise(kernel.hitl, OPERATOR)
        outbox = _claimed(store)
        exempt = asyncio.run(
            authorize_approval_response(kernel, _principal(client), req)
        )
        asyncio.run(kernel.hitl.answer(T, req.id, "approve", respondent=CLIENT))
        consumed = asyncio.run(kernel.hitl.consume_approved_by(T, req.id, VERB, "fp-1"))
        return len(outbox), exempt, consumed

    empty_outbox, empty_exempt, empty_consumed = flow(False)
    full_outbox, full_exempt, full_consumed = flow(True)

    assert empty_outbox == 0 and full_outbox == 1  # the outbox state differed
    assert (empty_exempt, empty_consumed) == (full_exempt, full_consumed)
    # None, not False: authorize_approval_response now returns the NAME of the
    # relief that lifted independence ("sole_author" / "development_posture")
    # or None when none was needed. The client is independent of the operator
    # who raised this, so no relief applies - which is what this asserts.
    assert full_exempt is None and full_consumed == CLIENT
