"""The four-eyes ratchet is one-way, announced, and honestly attributed
([2026] VJS-CC-BOLTRIG-OPERATOR-SEAT-001, D2, D3, D4, D6).

The sole-author bootstrap exemption lifts the independent-approver rule while a
tenant has exactly ONE active author-tier user, because at one the rule is
unsatisfiable. So that count is not a property of the user table, it is the
tenant's approval REGIME: at one, self-approval is lawful; at two, it is not.

On Classical Visas the regime changed silently and in the worst possible way.
`control.invitation.create` was self-approved under the exemption, the client
was seated, and then `control.user.update` promoted her to `admin` - itself
self-approved under the exemption, at 08:30:05 on 2026-07-27. The promotion
executed 26 seconds later and killed the exemption. The last act performed
under the exemption destroyed it, and nothing said so. The operator discovered
it by hitting the wall, read the wall as a deadlock, and applied to open the
host boundary with a new `seat-operator` command.

Both limbs of that application were refused, and these four directives repair
what the record actually disclosed:

D2 - the crossing DOWN to one is refused outright, before the write. The
     "narrower cure" of demoting the client was the most destructive option on
     the list: it revives self-approval, and because `control.user.update` is
     itself high-consequence it needs the client to approve stripping her own
     protection.
D3 - any crossing of the 1<->2 boundary is announced on the audit stream.
D4 - an exemption spent on the very act that ends it says so, at the moment it
     is spent.
D6 - `set-password` and `mint-token` stop attributing themselves to the user
     they act UPON, and land on the security stream.
"""

from __future__ import annotations

import json

import pytest

from boltrig.api import initiate as initiate_mod
from boltrig.api.host_boundary import HOST_BOUNDARY_ACTOR
from boltrig.config.control_operations import (
    deactivate_user_record,
    update_user_record,
)
from boltrig.config.control_plane import build_control_plane_adapter
from boltrig.identity.provisioning import current_grants_for_user
from boltrig.kernel import Kernel
from boltrig.kernel.app import Principal
from boltrig.kernel.hitl_http import _exemption_would_end_itself, respond_to_hitl
from boltrig.kernel.hitl_response_auth import _sole_active_author
from boltrig.models import (
    GrantSet,
    HITLType,
    InvocationContext,
    SecurityEventType,
    TenantPermissions,
    User,
)
from boltrig.store import InMemoryStore

T = "cv"
OPERATOR = "will.lilley93@gmail.com"
CLIENT = "info@classicalvisas.com"


def _store() -> InMemoryStore:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    return store


async def _seat(store, subject: str, role: str, status: str = "active") -> User:
    user = User(
        id=subject, tenant_id=T, email=subject, role=role,
        scope={"all": True}, status=status,
    )
    await store.upsert_user(user)
    return user


def _ctx(actor: str = OPERATOR, role: str = "superadmin") -> InvocationContext:
    return InvocationContext(
        tenant_id=T, grants=GrantSet.of(["*"]), actor=actor, actor_tier="human",
        run_id="run-1", extra={"principal_role": role},
    )


# --- D2: the ratchet only turns one way ------------------------------------


async def test_demoting_the_second_author_is_refused(anyio_backend=None) -> None:
    """2 -> 1 by demotion: refused, and the exemption stays dead afterwards.

    The second assertion is the one that matters. A refusal that still left the
    tenant readable as single-author would be a refusal in name only.
    """
    store = _store()
    await _seat(store, OPERATOR, "superadmin")
    await _seat(store, CLIENT, "admin")

    with pytest.raises(PermissionError, match="single active author-tier"):
        await update_user_record(
            store, T, {"user_id": CLIENT, "role": "member"}, context=_ctx()
        )

    assert await _sole_active_author(store, T, OPERATOR) is False
    assert (await store.get_user(T, CLIENT)).role == "admin"


async def test_deactivating_the_second_author_is_refused() -> None:
    """The same crossing by the other route. A deactivated author is not one."""
    store = _store()
    await _seat(store, OPERATOR, "superadmin")
    await _seat(store, CLIENT, "admin")

    with pytest.raises(PermissionError, match="single active author-tier"):
        await deactivate_user_record(store, T, CLIENT, context=_ctx())

    assert await _sole_active_author(store, T, OPERATOR) is False
    assert (await store.get_user(T, CLIENT)).status == "active"


async def test_setting_the_second_author_inactive_via_update_is_refused() -> None:
    """status='deactivated' through control.user.update is the same crossing."""
    store = _store()
    await _seat(store, OPERATOR, "superadmin")
    await _seat(store, CLIENT, "admin")

    with pytest.raises(PermissionError, match="single active author-tier"):
        await update_user_record(
            store, T, {"user_id": CLIENT, "status": "deactivated"}, context=_ctx()
        )


async def test_three_to_two_is_allowed() -> None:
    """The exemption keys on exactly one, so only that crossing changes anything."""
    store = _store()
    await _seat(store, OPERATOR, "superadmin")
    await _seat(store, CLIENT, "admin")
    await _seat(store, "third@acme", "admin")

    await update_user_record(
        store, T, {"user_id": "third@acme", "role": "member"}, context=_ctx()
    )
    assert (await store.get_user(T, "third@acme")).role == "member"
    assert await _sole_active_author(store, T, OPERATOR) is False


async def test_two_to_two_is_allowed() -> None:
    """A change that does not move the count is not the court's business."""
    store = _store()
    await _seat(store, OPERATOR, "superadmin")
    await _seat(store, CLIENT, "admin")

    await update_user_record(
        store, T, {"user_id": CLIENT, "role": "org-admin"}, context=_ctx()
    )
    assert (await store.get_user(T, CLIENT)).role == "org-admin"


async def test_one_to_one_is_allowed() -> None:
    """A single-author tenant is ALREADY at one; nothing is being taken away.

    Refusing here would brick the bootstrap posture the exemption exists to
    serve - the tenant could never demote or deactivate its only non-author.
    """
    store = _store()
    await _seat(store, OPERATOR, "superadmin")
    await _seat(store, CLIENT, "member")

    await deactivate_user_record(store, T, CLIENT, context=_ctx())
    assert await _sole_active_author(store, T, OPERATOR) is True


# --- D3: announce the crossing ---------------------------------------------


async def _kernel(store) -> Kernel:
    k = Kernel(store)
    control = build_control_plane_adapter(store, loader=k.loader, registry=k.registry)
    await k.register_adapter(T, control)
    return k


async def _crossing_rows(store) -> list:
    events, _ = await store.audit_scan(T, 0, 1000), None
    return [e for e in events if e.verb == "control.author_tier.crossing"]


async def _approved(k: Kernel, verb: str, params: dict) -> dict:
    from boltrig.models.errors import PendingHuman

    with pytest.raises(PendingHuman) as exc:
        await k.invoke("control", verb, params, _ctx())
    req_id = exc.value.hitl_request_id
    await k.hitl.answer(T, req_id, "approve", CLIENT)
    return await k.invoke("control", verb, params, _ctx(), approval_id=req_id)


async def test_promotion_across_the_boundary_writes_exactly_one_crossing_row() -> None:
    """1 -> 2: the act that ended the exemption on CV now announces itself."""
    store = _store()
    await _seat(store, OPERATOR, "superadmin")
    await _seat(store, CLIENT, "member")
    k = await _kernel(store)

    await _approved(k, "control.user.update", {"user_id": CLIENT, "role": "admin"})

    rows = await _crossing_rows(store)
    assert len(rows) == 1, f"expected exactly one crossing row, got {len(rows)}"
    detail = rows[0].detail
    assert detail["verb"] == "control.user.update"
    assert detail["active_authors_before"] == 1
    assert detail["active_authors_after"] == 2
    assert detail["sole_author_exemption_after"] is False


async def test_a_promotion_that_does_not_move_the_count_writes_no_row() -> None:
    """Silent on 2 -> 2. A row per control verb buries the six that matter."""
    store = _store()
    await _seat(store, OPERATOR, "superadmin")
    await _seat(store, CLIENT, "admin")
    await _seat(store, "third@acme", "member")
    k = await _kernel(store)

    await _approved(k, "control.user.update", {"user_id": "third@acme", "role": "member"})

    assert await _crossing_rows(store) == []


# --- D4: an exemption spent to end itself says so ---------------------------


class _Req:
    def __init__(self, verb: str, inputs: dict | None, *, raw: str | None = None) -> None:
        self.verb = verb
        self.context = (
            raw if raw is not None else json.dumps({"version": 1, "inputs": inputs or {}})
        )


@pytest.mark.parametrize(
    "verb,inputs",
    [
        ("control.user.update", {"user_id": CLIENT, "role": "admin"}),
        ("control.user.update", {"user_id": CLIENT, "role": "org-admin"}),
        ("control.invitation.create", {"email": CLIENT, "role": "admin"}),
    ],
)
def test_flag_is_present_for_an_approval_that_grants_author_tier(verb, inputs) -> None:
    assert _exemption_would_end_itself(_Req(verb, inputs)) is True


@pytest.mark.parametrize(
    "verb,inputs",
    [
        # Same verbs, a role that is not author-tier: the count does not move.
        ("control.user.update", {"user_id": CLIENT, "role": "member"}),
        ("control.invitation.create", {"email": CLIENT, "role": "member"}),
        # A verb that cannot change the author count at all.
        ("control.adapter.activate", {"adapter_id": "generated"}),
        # No role stated.
        ("control.user.update", {"user_id": CLIENT, "scope": {"all": True}}),
    ],
)
def test_flag_is_absent_for_an_approval_that_does_not(verb, inputs) -> None:
    assert _exemption_would_end_itself(_Req(verb, inputs)) is False


def test_a_non_canonical_context_says_nothing_rather_than_guessing() -> None:
    """The gate refuses to raise an approval whose context is not canonical
    JSON, so such a row is legacy or hand-made. Guessing from it would be
    inventing a fact about an authority someone is spending."""
    assert _exemption_would_end_itself(_Req("control.user.update", None, raw="not json")) is False
    assert _exemption_would_end_itself(_Req("control.user.update", None, raw="")) is False


async def test_respond_to_hitl_flags_and_audits_the_self_ending_exemption() -> None:
    """End to end: the flag reaches BOTH the response and the audit detail.

    A flag returned to the caller and absent from the chain would be a warning
    only the person already doing it ever sees.
    """
    store = _store()
    operator = await _seat(store, OPERATOR, "superadmin")
    k = await _kernel(store)

    request = await k.hitl.create(
        tenant_id=T, run_id="run-1", type=HITLType.APPROVAL,
        question="Approve control.user.update?",
        context=json.dumps({"version": 1, "inputs": {"user_id": CLIENT, "role": "admin"}}),
        options=["approve", "reject"], verb="control.user.update",
        requested_by=OPERATOR, request_fingerprint="fp-1",
    )
    principal = Principal(
        tenant_id=T, subject=OPERATOR, grants=current_grants_for_user(operator),
        role=operator.role, actor_tier="human", scope=operator.scope,
    )

    result = await respond_to_hitl(k, principal, request.id, "approve", "")

    assert result["sole_author_exemption"] is True
    assert result["ends_sole_author_exemption"] is True

    events = await store.audit_scan(T, 0, 1000)
    rows = [e for e in events if e.verb == "hitl.sole_author_approval"]
    assert len(rows) == 1
    assert rows[0].detail["ends_sole_author_exemption"] is True


# --- D6: the host boundary owns its own acts -------------------------------


async def test_set_password_attributes_the_host_boundary_and_alarms(monkeypatch) -> None:
    """Neither (a) an audit row actor'd to the target, nor (b) silence.

    Writing actor=email made a shell holder resetting someone's password
    produce a row that reads as that person's own act - and the same boundary
    can mint a fully-scoped PAT as them, so the forged participation was
    end-to-end consistent. That is why the court answered this by attributing
    the boundary rather than opening a third command beside it.
    """
    store = _store()
    await _seat(store, CLIENT, "admin")

    async def _fake_build_store():
        return store

    monkeypatch.setattr("boltrig.api.bootstrap.build_store", _fake_build_store)
    rc = await initiate_mod._run_set_password(CLIENT, "Correct-Horse-Battery-9!", T)
    assert rc == 0

    events = await store.audit_scan(T, 0, 1000)
    rows = [e for e in events if e.verb == "auth.set_password"]
    assert len(rows) == 1
    assert rows[0].actor != CLIENT, "the act is still attributed to the target user"
    assert rows[0].actor == HOST_BOUNDARY_ACTOR
    assert rows[0].on_behalf_of == CLIENT, "the row must still say who was acted upon"

    signals = await store.security_scan(T, 0, 1000)
    hb = [s for s in signals if s.event_type == SecurityEventType.HOST_BOUNDARY_CREDENTIAL]
    assert len(hb) == 1
    assert hb[0].reason == "set_password"
    assert hb[0].actor == HOST_BOUNDARY_ACTOR
    # The subject rides the column: SecurityWriter scrubs detail keys-only, so
    # an address put in detail would come back a digest.
    assert hb[0].on_behalf_of == CLIENT
