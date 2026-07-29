"""A declared development posture lifts INDEPENDENCE, and nothing else.

Binds [2026] VJS-CC-BOLTRIG-DEVELOPMENT-POSTURE-001 D2, D3, D4 and D5. Its D6
lives in test_hitl_notification_routing.py, alongside the notification order it
repairs. D1 (withdraw the posture from Classical Visas) is discharged on the
operative tenant, not here: it is a fact about a manifest on a box, and the
order's implementation_note records the verification against the running kernel.
D7 (put the act to the client) and D8 (correct the record) are record repair.


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
# The declaration now names the authors it covers (D3). "op" alone is the shape a
# lawful declaration takes: one operator, on a tenant with no other author.
LIVE = DevelopmentPosture(
    enabled=True, expires_at=NOW + timedelta(days=7), declared_by="op", covers=("op",)
)


def _block(**over):
    """The ADMITTING baseline, with every condition satisfied.

    Each condition is a parameter rather than an ambient read, so this helper is
    the one place a new condition has to be defaulted - and until it is, every
    test in the file fails loudly rather than one caller silently defaulting to
    permissive. That is deliberate: the first version of this posture shipped
    with a missing limb precisely because nothing forced the question.
    """
    kwargs = dict(
        posture=LIVE, now=NOW,
        production_signal=None,
        development_signal="BOLTRIG_ENV=dev",
        real_ingress=False,
        credential_kind="session",
        active_author_ids=["op"],
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


# --- D5: the environment must SAY development, not merely fail to say prod ---


def test_an_unconfigured_environment_refuses() -> None:
    """DEVELOPMENT-POSTURE-001 D5. The absence of a production signal is not evidence of development.

    production_signal() reads four operator-set variables and returns None when
    all are unset, so a control that read "no production signal" as permission
    permitted on every environment nobody had configured. Classical Visas
    returned no production signal while serving a real client on a public domain.
    """
    assert "neither development nor production" in (_block(development_signal=None) or "")


@pytest.mark.parametrize("signal", ["ENV=dev", "BOLTRIG_ENV=development", "APP_ENV=local"])
def test_an_affirmative_development_signal_admits(signal) -> None:
    assert _block(development_signal=signal) is None


def test_the_development_signal_is_read_from_the_environment_not_invented() -> None:
    """The parameter is not decoration: development_signal() must actually find
    these, or posture_block would be gated on a value nothing ever produces."""
    from boltrig.config.environment import development_signal

    assert development_signal({"BOLTRIG_ENV": "dev"}) == "BOLTRIG_ENV=dev"
    assert development_signal({"APP_ENV": "test"}) == "APP_ENV=test"
    assert development_signal({}) is None
    assert development_signal({"ENV": "production"}) is None


# --- D2: the limb the precedent requires and this posture had dropped --------


def test_a_real_ingress_posture_refuses() -> None:
    """DEVELOPMENT-POSTURE-001 D2. require_codex_trusted_posture, the wall this was modelled on, refuses a
    production signal AND a real ingress posture. Only the first limb was
    reproduced, and the dropped one is exactly the limb that would have refused
    the tenant this was actually declared on: Classical Visas runs
    BOLTRIG_AUTH_MODE=session.
    """
    blocked = _block(real_ingress=True) or ""
    assert "real ingress" in blocked
    assert "in service" in blocked


def test_the_ingress_limb_is_computed_from_settings_not_assumed() -> None:
    """The caller derives real_ingress the same way the codex wall does. If this
    drifts, posture_block is being handed a constant and the limb is theatre."""
    from boltrig.config.settings import load_settings

    session_env = {"BOLTRIG_AUTH_MODE": "session"}
    s = load_settings(session_env)
    assert (s.oidc_configured or s.cf_access_configured or s.session_auth_configured)

    dev_env = {"BOLTRIG_DEV_AUTH": "1"}
    s = load_settings(dev_env)
    assert not (s.oidc_configured or s.cf_access_configured or s.session_auth_configured)


# --- D4: a credential class, not an actor tier ------------------------------


@pytest.mark.parametrize("kind", ["pat", "machine", "", "agent"])
def test_a_non_interactive_credential_refuses(kind) -> None:
    """DEVELOPMENT-POSTURE-001 D4. resolve_pat_principal stamps actor_tier="human" on every machine bearer,
    so actor_tier could never have carried this. "machine" is the Principal
    default, which means a resolver nobody labelled is refused, not admitted."""
    assert "person at a door" in (_block(credential_kind=kind) or "")


@pytest.mark.parametrize("kind", ["session", "federated", "dev-header"])
def test_an_interactive_credential_admits(kind) -> None:
    assert _block(credential_kind=kind) is None


# --- D3: it lapses when a party it does not name appears --------------------


def test_an_author_the_declaration_does_not_name_lapses_it() -> None:
    """DEVELOPMENT-POSTURE-001 D3: an author the declaration does not name is a
    party the independence rule exists to protect, so the posture has lapsed."""
    blocked = _block(active_author_ids=["op", "client@example.com"]) or ""
    assert "does not cover every active author" in blocked
    assert "client@example.com" in blocked


def test_a_declaration_naming_nobody_covers_nobody() -> None:
    """The failure mode of a malformed `covers` must be full four-eyes."""
    empty = DevelopmentPosture(enabled=True, expires_at=NOW + timedelta(days=7))
    assert _block(posture=empty) is not None


def test_covers_is_parsed_from_the_manifest() -> None:
    parsed = _parse_development_posture({"development_posture": {
        "enabled": True, "expires_at": "2026-08-05", "covers": ["a@x", " b@x "],
    }})
    assert parsed.covers == ("a@x", "b@x")
    malformed = _parse_development_posture({"development_posture": {
        "enabled": True, "expires_at": "2026-08-05", "covers": "a@x",
    }})
    assert malformed.covers == ()


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


@pytest.fixture(autouse=True)
def _a_development_environment(monkeypatch):
    """The end-to-end cases need what the ruling now requires of a real one: an
    AFFIRMATIVE development signal (D5) and no real ingress posture (D2).

    Setting it here rather than defaulting it inside posture_block is the whole
    point. An unset environment must refuse, so the tests have to state the
    environment they are testing in, exactly as a deployment does.
    """
    monkeypatch.setenv("BOLTRIG_ENV", "dev")
    for key in ("BOLTRIG_OIDC_ISSUER", "CF_ACCESS_TEAM_DOMAIN", "BOLTRIG_AUTH_MODE"):
        monkeypatch.delenv(key, raising=False)


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


async def _raise_and_answer(k, credential_kind: str = "session"):
    request = await k.hitl.create(
        tenant_id=T, run_id="r1", type=HITLType.APPROVAL,
        question="Approve control.adapter.activate?",
        context='{"version": 1, "inputs": {"adapter_id": "opbox"}}',
        options=["approve", "reject"], verb="control.adapter.activate",
        requested_by=OP, request_fingerprint="fp",
    )
    user = await k.store.get_user(T, OP)
    principal = Principal(tenant_id=T, subject=OP, grants=current_grants_for_user(user),
                          role=user.role, actor_tier="human", scope=user.scope,
                          credential_kind=credential_kind)
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


def test_it_lapses_when_an_author_it_does_not_name_exists() -> None:
    """DEVELOPMENT-POSTURE-001 D3, and this assertion USED to be the opposite.

    The shipped posture admitted a self-approval on this exact tenant: two active
    authors, one of them a client, and a declaration that named nobody. The court
    held that independence may be suspended only where there is no party for
    independence to protect, so a declaration must name the authors it was made
    in respect of and lapse when anyone else appears - exactly as the sole-author
    exemption lapses the moment a second author exists.
    """
    from fastapi import HTTPException

    async def go():
        posture = DevelopmentPosture(
            enabled=True,
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
            declared_by=OP, reason="pre-launch", covers=(OP,),
        )
        k, _ = await _two_author_kernel(posture)
        with pytest.raises(HTTPException) as exc:
            await _raise_and_answer(k)
        assert exc.value.status_code == 403

    asyncio.run(go())


def test_a_machine_bearer_is_refused_even_under_a_live_posture() -> None:
    """DEVELOPMENT-POSTURE-001 D4, and the court proved this by execution against
    the shipped code.

    ``resolve_pat_principal`` stamps ``actor_tier="human"`` on every PAT, because
    a PAT carries its owner's authority. Reading that as a humanity check meant a
    machine bearer answered its own control approval on a live client tenant with
    nobody present. The posture reads the CREDENTIAL CLASS instead.
    """
    from fastapi import HTTPException

    async def go():
        posture = DevelopmentPosture(
            enabled=True,
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
            declared_by=OP, reason="pre-launch", covers=(OP, CLIENT),
        )
        k, _ = await _two_author_kernel(posture)
        with pytest.raises(HTTPException) as exc:
            await _raise_and_answer(k, credential_kind="pat")
        assert exc.value.status_code == 403

    asyncio.run(go())


def test_a_declared_posture_admits_it_and_leaves_the_record_behind() -> None:
    """The click is removed. The record is not - in THREE places, because a
    reader should not have to know which one to look in.

    The declaration must now name every active author, which on this tenant means
    naming the client too. That is the point: suspending independence is only
    lawful where the parties it protects are known and accounted for, not where
    the operator has simply not looked.
    """
    async def go():
        posture = DevelopmentPosture(
            enabled=True,
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
            declared_by=OP, reason="pre-launch", covers=(OP, CLIENT),
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
