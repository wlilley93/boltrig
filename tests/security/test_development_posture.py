"""A declared development posture lifts INDEPENDENCE, and nothing else.

The Principal's requirement: on a tenant that is not yet in service, an
operator must be able to work without a second human answering each approval,
and must be able to turn that off again.

What the posture therefore removes is the second person's CLICK. Everything
else a reader of the record would want is deliberately kept: the request is
still raised, still bound to its verb and fingerprint, still answered by a
named human, still marked on the audit row, and additionally alarmed on the
tamper-evident security stream. A party who was never asked to approve can
always read what was done on their tenant, and when.

The design has one honest weakness and these tests pin its mitigations rather
than pretend it away: the superadmin who declares the posture is the same party
four-eyes constrains. So the flag alone is never enough -

  * a production signal refuses it outright, whatever the manifest says
    (an OBSERVED fact, mirroring fleet/codex_trusted_wall);
  * it must carry an expiry, and an absent or malformed one refuses;
  * `admin` cannot use it - that is a role a CLIENT is routinely given;
  * it reaches `control.*` only;
  * it never lifts the grant check, the humanity check, or assignment.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from boltrig.config.dev_posture import DevelopmentPosture, posture_block
from boltrig.config.manifest import _parse_development_posture

NOW = datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc)
LIVE = DevelopmentPosture(enabled=True, expires_at=NOW + timedelta(days=7), declared_by="op")


def _block(**over):
    kwargs = dict(
        posture=LIVE, now=NOW, production_signal=None,
        verb="control.adapter.activate", subject_role="superadmin",
    )
    kwargs.update(over)
    return posture_block(**kwargs)


def test_a_declared_unexpired_posture_admits_a_superadmin_control_verb() -> None:
    assert _block() is None


# --- the observed condition, which the operator cannot assert away ----------


@pytest.mark.parametrize("signal", ["BOLTRIG_PRODUCTION", "ENV=production", "APP_ENV=prod"])
def test_a_production_signal_refuses_whatever_the_manifest_declares(signal) -> None:
    """Checked BEFORE the declaration. A tenant that says it is in development
    and also says it is production is not one whose own declaration should
    break the tie."""
    assert "production signal" in (_block(production_signal=signal) or "")


# --- it expires, and an unbounded posture is not a posture ------------------


def test_an_expired_posture_refuses() -> None:
    assert "expired" in (_block(posture=DevelopmentPosture(
        enabled=True, expires_at=NOW - timedelta(seconds=1))) or "")


def test_a_posture_with_no_expiry_refuses() -> None:
    """'Development' must not become a permanent condition nobody re-examines:
    the justification is that the tenant is not yet in service, and that claim
    goes stale."""
    assert "no expires_at" in (_block(posture=DevelopmentPosture(enabled=True)) or "")


def test_a_malformed_expiry_in_the_manifest_fails_closed() -> None:
    """A bad date must yield full four-eyes, never an unbounded suspension."""
    parsed = _parse_development_posture(
        {"development_posture": {"enabled": True, "expires_at": "not-a-date"}}
    )
    assert parsed.expires_at is None
    assert _block(posture=parsed) is not None


# --- it is not declared unless it is declared -------------------------------


def test_an_absent_block_is_not_a_posture() -> None:
    assert _parse_development_posture({}).enabled is False
    assert _block(posture=_parse_development_posture({})) is not None


def test_the_flag_defaults_off_even_when_the_block_exists() -> None:
    parsed = _parse_development_posture({"development_posture": {"expires_at": "2026-08-05"}})
    assert parsed.enabled is False
    assert _block(posture=parsed) is not None


# --- bounded: who, and over what -------------------------------------------


@pytest.mark.parametrize("role", ["admin", "org-admin", "member", "manager", ""])
def test_only_superadmin_may_use_it(role) -> None:
    """`admin` is the role a CLIENT is routinely given so they have authority
    over their own data. Admitting it would hand the relief to the very party
    four-eyes protects."""
    assert "superadmin only" in (_block(subject_role=role) or "")


@pytest.mark.parametrize("verb", ["opbox.add_comment", "jira.delete", "ms-graph.sendMail", ""])
def test_it_covers_control_verbs_only(verb) -> None:
    """Business verbs are untouched: the operator asked to work on the tenant's
    CONFIGURATION without a second human, not on its data."""
    assert "control.* only" in (_block(verb=verb) or "")


def test_the_refusal_says_which_condition_failed() -> None:
    """A caller that got a bare False could not tell 'not declared' from
    'declared but this is production', and those want very different responses
    from an operator."""
    assert "no development posture" in (_block(posture=None) or "")
    assert "production signal" in (_block(production_signal="ENV=production") or "")
    assert "expired" in (_block(
        posture=DevelopmentPosture(enabled=True, expires_at=NOW - timedelta(days=1))) or "")


# --- end to end through the real kernel ------------------------------------

import asyncio  # noqa: E402

from boltrig.identity.provisioning import current_grants_for_user  # noqa: E402
from boltrig.kernel import Kernel  # noqa: E402
from boltrig.kernel.app import Principal  # noqa: E402
from boltrig.kernel.hitl_http import respond_to_hitl  # noqa: E402
from boltrig.models import (  # noqa: E402
    GrantSet,
    HITLType,
    SecurityEventType,
    TenantPermissions,
    User,
)
from boltrig.store import InMemoryStore  # noqa: E402

T = "cv"
OP = "operator@example.com"
CLIENT = "client@example.com"


async def _two_author_kernel(posture):
    """A tenant with TWO active authors - so the sole-author exemption has
    lapsed and ONLY the posture can admit a self-approval."""
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    for uid, role in ((OP, "superadmin"), (CLIENT, "admin")):
        await store.upsert_user(User(id=uid, tenant_id=T, email=uid, role=role,
                                     scope={"all": True}, status="active"))
    k = Kernel(store)
    k.hitl.development_posture = posture
    return k, store


async def _raise_and_answer(k):
    request = await k.hitl.create(
        tenant_id=T, run_id="r1", type=HITLType.APPROVAL,
        question="Approve control.adapter.activate?",
        context='{"version": 1, "inputs": {"adapter_id": "opbox"}}',
        options=["approve", "reject"], verb="control.adapter.activate",
        requested_by=OP, request_fingerprint="fp",
    )
    user = await k.store.get_user(T, OP)
    principal = Principal(tenant_id=T, subject=OP, grants=current_grants_for_user(user),
                          role=user.role, actor_tier="human", scope=user.scope)
    return await respond_to_hitl(k, principal, request.id, "approve", "")


def test_without_a_posture_a_two_author_tenant_still_refuses_self_approval() -> None:
    """The precondition. If this ever passes, the test below proves nothing."""
    from fastapi import HTTPException

    async def go():
        k, _ = await _two_author_kernel(None)
        with pytest.raises(HTTPException) as exc:
            await _raise_and_answer(k)
        assert exc.value.status_code == 403
        assert "cannot approve your own request" in str(exc.value.detail)

    asyncio.run(go())


def test_a_declared_posture_admits_it_and_leaves_the_record_behind() -> None:
    """The click is removed. The record is not - in THREE places, because a
    reader should not have to know which one to look in."""
    async def go():
        posture = DevelopmentPosture(
            enabled=True,
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
            declared_by=OP, reason="pre-launch",
        )
        k, store = await _two_author_kernel(posture)
        result = await _raise_and_answer(k)

        # 1. the caller is told
        assert result["development_posture"] is True
        assert "sole_author_exemption" not in result, (
            "the two reliefs mean different things and must not be conflated"
        )

        # 2. the audit chain carries it under its own verb
        rows = [e for e in await store.audit_scan(T, 0, 1000)
                if e.verb == "hitl.development_posture_approval"]
        assert len(rows) == 1
        assert rows[0].detail["development_posture"] is True

        # 3. the tamper-evident security stream carries it
        sec = [s for s in await store.security_scan(T, 0, 1000)
               if s.event_type == SecurityEventType.DEVELOPMENT_POSTURE_APPROVAL]
        assert len(sec) == 1
        assert sec[0].actor == OP

    asyncio.run(go())


def test_the_posture_never_lifts_the_grant_check() -> None:
    """It lifts INDEPENDENCE and never AUTHORITY: a superadmin without the
    verb's grant is refused under a posture exactly as they are without one."""
    from fastapi import HTTPException

    async def go():
        posture = DevelopmentPosture(
            enabled=True, expires_at=datetime.now(timezone.utc) + timedelta(days=7))
        k, store = await _two_author_kernel(posture)
        store.set_tenant_permissions(TenantPermissions(T, GrantSet.of([], deny=["*"])))
        with pytest.raises(HTTPException) as exc:
            await _raise_and_answer(k)
        assert "not authorised" in str(exc.value.detail)

    asyncio.run(go())
