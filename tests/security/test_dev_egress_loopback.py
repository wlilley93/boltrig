"""The five conditions of [2026] VJS-CC-BOLTRIG-DEV-EGRESS-LOOPBACK-001.

The court PERMITTED diverting governed outbound egress into the stack's own
intake under a declared development tag, on five conditions, ALL of which must
hold before the diversion may run once. Each is seeded here: the mechanism is
removed and the test is confirmed red, because a condition nothing can fail is
not a condition.

The RATIO is C3, and it is the one worth restating: a control may be narrowed by
a declared posture where the narrowing removes the protected exposure entirely;
but where the narrowing makes a human's approval mean something other than what
the human is being asked to approve, the narrowing must be disclosed at the point
of approval, IN THE APPROVAL ITSELF. An approval obtained on a false description
of its effect is not an approval.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from boltrig.config.dev_egress import (
    DIVERTED_STATUS,
    DevEgressPosture,
    Diversion,
    diversion_block,
)

pytestmark = pytest.mark.security

NOW = datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)
LOOPBACK = "https://kernel.internal/v1/channels/loopback"


def _posture(**over) -> DevEgressPosture:
    base = dict(
        enabled=True,
        expires_at=NOW + timedelta(days=7),
        loopback_url=LOOPBACK,
        declared_by="will.lilley93@gmail.com",
        reason="dev",
    )
    base.update(over)
    return DevEgressPosture(**base)


def _channel(**over):
    from boltrig.models import Channel

    base = dict(
        id="c1", tenant_id="acme", platform="webhook", name="ops",
        transport="webhook", enabled=True,
    )
    base.update(over)
    return Channel(**base)


def _block(**over) -> str | None:
    args = dict(
        now=NOW,
        production_signal=None,
        development_signal="dev",
        real_ingress=False,
    )
    posture = over.pop("posture", _posture())
    args.update(over)
    return diversion_block(posture, **args)


def test_a_fully_declared_posture_permits_the_diversion() -> None:
    """The negative control for every refusal below.

    Without it, a diversion_block that returned a reason unconditionally would
    pass all five condition tests while permitting nothing at all.
    """
    assert _block() is None


# --- C1: an AFFIRMATIVE development signal ---------------------------------


def test_c1_absence_of_a_production_signal_does_not_enable_the_diversion() -> None:
    """Four unset variables are the state of every unconfigured environment.

    This is the exact defect [2026] VJS-CC-BOLTRIG-DEVELOPMENT-POSTURE-001 D5
    refused on the sibling posture, and the court imported it here by name.
    """
    reason = _block(development_signal=None)
    assert reason is not None and "affirmative development signal" in reason


def test_c1_an_undeclared_posture_permits_nothing() -> None:
    assert diversion_block(
        None,
        now=NOW,
        production_signal=None,
        development_signal="dev",
        real_ingress=False,
    ) is not None
    assert _block(posture=_posture(enabled=False)) is not None


def test_c1_a_production_signal_beats_the_declaration() -> None:
    """Checked BEFORE the declared condition on purpose: a tenant that says it is
    development AND production is not one whose own declaration breaks the tie."""
    reason = _block(production_signal="BOLTRIG_PRODUCTION")
    assert reason is not None and "never applies in production" in reason


# --- C2: no real ingress posture -------------------------------------------


def test_c2_real_ingress_refuses_the_diversion_regardless_of_the_dev_tag() -> None:
    """The limb the sibling posture was refused for DROPPING (D2).

    A tenant with real users at a real door is in service, and its outbound sends
    are real sends - whatever the manifest says.
    """
    reason = _block(real_ingress=True)
    assert reason is not None and "real ingress posture" in reason


def test_c2_the_runtime_reads_all_three_ingress_limbs() -> None:
    """Not one limb, not two. Dropping any single one is what got the sibling
    posture refused, and it must be visible that none was quietly lost."""
    import inspect

    from boltrig.kernel import dev_egress_runtime

    source = inspect.getsource(dev_egress_runtime.DiversionResolver.block_reason)
    for limb in ("oidc_configured", "cf_access_configured", "session_auth_configured"):
        assert limb in source, f"the {limb} ingress limb is not read"


# --- C5: a mandatory, honoured expiry ---------------------------------------


def test_c5_an_unbounded_posture_is_refused() -> None:
    reason = _block(posture=_posture(expires_at=None))
    assert reason is not None and "no expires_at" in reason


def test_c5_an_expired_posture_fails_closed_to_normal_sending() -> None:
    reason = _block(posture=_posture(expires_at=NOW - timedelta(seconds=1)))
    assert reason is not None and "expired" in reason


def test_c5_an_unparseable_expiry_reads_as_no_bound_not_as_no_limit() -> None:
    """A typo in the ONE field that bounds the diversion must not read as
    "unbounded is fine". It parses to None, and None is refused by C5."""
    from boltrig.kernel.dev_egress_runtime import build_diversion_resolver

    class _M:
        def section(self, _name):
            return {
                "enabled": "true",
                "expires_at": "next tuesday",
                "loopback_url": LOOPBACK,
            }

    assert build_diversion_resolver(_M()).block_reason() is not None


def test_a_diversion_with_nowhere_to_go_is_refused() -> None:
    """Silently dropping the message is the one outcome worse than sending it."""
    reason = _block(posture=_posture(loopback_url="  "))
    assert reason is not None and "nowhere to divert" in reason


# --- C3: the disclosure, on all three surfaces -----------------------------


def test_c3_the_notice_names_both_the_true_destination_and_the_silence() -> None:
    notice = Diversion("info@classicalvisas.com", LOOPBACK).notice()
    assert LOOPBACK in notice, "the notice must name the ACTUAL recipient"
    assert "info@classicalvisas.com" in notice
    assert "will NOT be messaged" in notice, (
        "naming the loopback is only half: the approver must be told the declared "
        "recipient is not messaged"
    )


def test_c3_the_adapter_discloses_the_diversion_to_the_approval_gate() -> None:
    from boltrig.adapters.builtin.channel_send import build_channel_send
    from boltrig.kernel.approval_gate import APPROVAL_NOTICE_KEY

    adapter = build_channel_send(
        store=None,
        diversion=lambda target: Diversion(target, LOOPBACK),
    )
    ctx = adapter.approval_context(
        "channel.send", {"target": "info@classicalvisas.com"}, None
    )
    assert ctx is not None
    assert LOOPBACK in ctx[APPROVAL_NOTICE_KEY]
    assert ctx["egress"]["will_reach_declared_recipient"] is False


async def _pend_a_send(*, diverted: bool):
    """Drive the REAL chokepoint to the point of pause and return the request row.

    Not ``_approval_question`` directly. An earlier version of this test asserted
    on that helper, and reverting the CALL SITE in ``enforce_approval`` left it
    green - it proved the helper formatted a string and nothing about whether any
    approver would ever see it. The only assertion worth making is on the row the
    notification is built from.
    """
    from boltrig.adapters.builtin.channel_send import build_channel_send
    from boltrig.kernel import Kernel
    from boltrig.models import (
        Channel,
        GrantSet,
        InvocationContext,
        PendingHuman,
        TenantPermissions,
    )
    from boltrig.store import InMemoryStore

    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions("acme", GrantSet.of(["*"])))
    kernel = Kernel(store)
    await store.upsert_channel(
        Channel(
            id="c1", tenant_id="acme", platform="webhook", name="ops",
            transport="webhook", enabled=True,
            config={"outbound_url": "https://real.example/hook"},
        )
    )
    await kernel.register_adapter(
        "acme",
        build_channel_send(
            store,
            diversion=(lambda t: Diversion(t, LOOPBACK)) if diverted else None,
        ),
    )
    context = InvocationContext(
        tenant_id="acme", grants=GrantSet.of(["*"]), actor="agent-1", run_id="run-1"
    )
    with pytest.raises(PendingHuman) as pending:
        await kernel.invoke(
            "channel",
            "channel.send",
            {"channel_id": "c1", "text": "hi", "target": "info@classicalvisas.com"},
            context,
        )
    return await store.get_hitl_request("acme", pending.value.hitl_request_id)


@pytest.mark.asyncio
async def test_c3_the_request_row_the_notification_is_built_from_names_the_diversion() -> None:
    """A log line does not satisfy C3, and neither does the card alone.

    ``HITLManager._notify_request`` sends ``req.question`` to every eligible
    approver, so the QUESTION is the field that decides whether the notification
    surface carries the disclosure at all.
    """
    request = await _pend_a_send(diverted=True)
    assert LOOPBACK in request.question, "the notification surface would say nothing"
    assert "will NOT be messaged" in request.question
    # and the card, which renders the display context
    assert LOOPBACK in request.context
    assert '"will_reach_declared_recipient":false' in request.context.replace(" ", "")


@pytest.mark.asyncio
async def test_c3_an_undiverted_send_says_nothing_about_a_loopback() -> None:
    """The negative control: a notice appended unconditionally would satisfy the
    test above while telling every approver of every real send something untrue."""
    request = await _pend_a_send(diverted=False)
    assert request.question == "Approve channel.send?"
    assert "loopback" not in request.context.lower()


def test_c3_an_ordinary_send_gets_no_notice_and_no_egress_block() -> None:
    """The negative control: a notice appended unconditionally would pass the
    test above while telling every approver of every verb something untrue."""
    from boltrig.adapters.builtin.channel_send import build_channel_send
    from boltrig.kernel.approval_gate import _approval_question

    adapter = build_channel_send(store=None)
    assert adapter.approval_context("channel.send", {"target": "x"}, None) is None
    assert _approval_question("channel.send", None) == "Approve channel.send?"


def test_c3_the_disclosure_is_part_of_the_approval_fingerprint() -> None:
    """The ratio made structural: an approval given on the diverted description
    cannot be redeemed for a real send, because the description is bound in.

    The resource context feeds ``approval_request_fingerprint``, so the two
    fingerprints must differ. Were they equal, an approval collected under the
    loopback would satisfy the gate for an identical un-diverted send.
    """
    from boltrig.kernel.hitl import approval_request_fingerprint
    from boltrig.models import InvocationContext

    context = InvocationContext(tenant_id="acme", actor="a", run_id="r")
    params = {"channel_id": "c1", "text": "hi", "target": "info@classicalvisas.com"}
    common = dict(noun="channel", verb="channel.send", params=params, context=context)
    diverted = approval_request_fingerprint(
        resource_context=Diversion(params["target"], LOOPBACK).as_context(), **common
    )
    real = approval_request_fingerprint(resource_context=None, **common)
    assert diverted != real


# --- C4: the record says diverted, and no reader can read "sent" -----------


@pytest.mark.asyncio
async def test_c4_a_diverted_send_reports_diverted_and_never_sent() -> None:
    """No reader may obtain the string ``sent`` for a diverted message.

    The failure mode the court named runs THIS way round: a sender who believes
    a message was delivered when it never left. ``diverted`` is a distinct status
    rather than a flag beside ``sent`` precisely because the readers that matter
    check the status and nothing else.
    """
    from boltrig.adapters.builtin.channel_send import _default_deliver

    posted: list[str] = []

    class _Resp:
        status_code = 202

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return False

        async def post(self, url, json=None):
            posted.append(url)
            return _Resp()

    import boltrig.adapters.egress as egress

    original = egress.pinned_async_client
    egress.pinned_async_client = lambda url, timeout=10: _Client()
    try:
        channel = _channel(config={"outbound_url": "https://real.example/hook"})
        out = await _default_deliver(
            None, channel, "hello", "info@classicalvisas.com",
            Diversion("info@classicalvisas.com", LOOPBACK),
        )
    finally:
        egress.pinned_async_client = original

    assert out["status"] == DIVERTED_STATUS
    assert "sent" not in str(out).lower().split("status")[0] or out["status"] != "sent"
    assert out["status"] != "sent"
    assert out["will_reach_declared_recipient"] is False
    assert posted == [LOOPBACK], "the real outbound_url must not be contacted"


@pytest.mark.asyncio
async def test_c4_the_diversion_beats_the_socket_outbox_branch() -> None:
    """A socket channel diverting into its own outbox row would be
    indistinguishable from a real queued send at every reader downstream, so the
    diversion is taken BEFORE the transport branch."""
    from boltrig.adapters.builtin.channel_send import _default_deliver

    enqueued: list[object] = []

    class _Store:
        async def enqueue_channel_outbox(self, message):
            enqueued.append(message)

    class _Resp:
        status_code = 202

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return False

        async def post(self, url, json=None):
            return _Resp()

    import boltrig.adapters.egress as egress

    original = egress.pinned_async_client
    egress.pinned_async_client = lambda url, timeout=10: _Client()
    try:
        channel = _channel(transport="socket")
        out = await _default_deliver(
            _Store(), channel, "hello", "someone", Diversion("someone", LOOPBACK)
        )
    finally:
        egress.pinned_async_client = original

    assert out["status"] == DIVERTED_STATUS
    assert enqueued == [], "a diverted send must not leave an outbox row"


@pytest.mark.asyncio
async def test_an_undiverted_send_still_reports_sent() -> None:
    """The negative control for C4: a deliver seam that returned ``diverted``
    unconditionally would pass both tests above and break every real send."""
    from boltrig.adapters.builtin.channel_send import _default_deliver

    class _Resp:
        status_code = 200

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return False

        async def post(self, url, json=None):
            return _Resp()

    import boltrig.adapters.egress as egress

    original = egress.pinned_async_client
    egress.pinned_async_client = lambda url, timeout=10: _Client()
    try:
        channel = _channel(config={"outbound_url": "https://real.example/hook"})
        out = await _default_deliver(None, channel, "hello", "someone", None)
    finally:
        egress.pinned_async_client = original

    assert out["status"] == "sent"


# --- the diversion is unreachable without a declaration --------------------


def test_the_adapter_cannot_divert_without_an_injected_resolver() -> None:
    """C1 enforced by construction rather than by a check.

    A registration with no manifest gets no resolver at all, so the demo tenant
    and every bare boot have no code path to a diversion regardless of what the
    environment says.
    """
    from boltrig.adapters.builtin.channel_send import build_channel_send

    adapter = build_channel_send(store=None)
    assert adapter._diversion_for({"target": "x"}) is None
