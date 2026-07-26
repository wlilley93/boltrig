"""`boltrig fleet-health`: a readiness probe for a process that serves no HTTP.

The fleet worker's container healthcheck was `python -c "import boltrig"` - it
proves an interpreter can import a module and cannot go red for any outage that
matters. It was recorded as open debt rather than fixed, because
`python -m boltrig.api.worker` exposes no endpoint.

It does publish evidence, though: a signed, short-lived receipt in Redis naming
which of its tools probed ok, which the KERNEL's /readyz already consumes. The
readiness surface existed; nothing on the worker side read it back.

Every branch is exercised, and the OK path is driven through a real
publish/validate round-trip rather than a stub - a probe that only ever proves
refusals would be satisfied by `return 1`.
"""

from __future__ import annotations

import time

import pytest

from boltrig.api import fleet_health
from boltrig.fleet.stack_tool_receipts import (
    _FLEET_TOOL_IDS,
    _receipt_key,
    _receipt_payload,
    receipt_signing_key,
    validate_fleet_tool_receipt,
)

pytestmark = pytest.mark.security

REAL_KEY = "b9f2c1a4e7d38650f1c2b3a4958d6e7f0a1b2c3d4e5f60718293a4b5c6d7e8f9"


async def _check(**env: str) -> tuple[int, str]:
    return await fleet_health._check(env)


@pytest.mark.invariant("FR-OPS-05")
async def test_no_redis_is_reported_as_not_checked_not_as_healthy() -> None:
    """Green here means "could not look", and it says so.

    Exiting 1 would paint every offline deployment permanently red, which teaches
    operators to ignore the signal - the failure mode this whole probe exists to
    remove.
    """
    code, message = await _check()
    assert code == 0
    assert "NOT CHECKED" in message and "REDIS_URL" in message


@pytest.mark.invariant("FR-OPS-05")
async def test_a_deployment_may_declare_the_receipt_mandatory() -> None:
    code, message = await _check(BOLTRIG_FLEET_HEALTH_REQUIRE_RECEIPT="1")
    assert code == 1 and "required" in message


@pytest.mark.invariant("FR-OPS-05")
async def test_a_placeholder_audit_key_is_not_checked_rather_than_failed() -> None:
    """A placeholder key is REJECTED by design - a receipt signed with the
    constant this repository ships is forgeable by anyone who cloned it - so on a
    dev box no receipt can exist and the probe must not claim an outage."""
    code, message = await _check(
        REDIS_URL="redis://localhost:6379",
        BOLTRIG_AUDIT_HMAC_KEY="change-me-to-a-long-random-secret",
    )
    assert code == 0
    assert "NOT CHECKED" in message and "placeholder" in message


@pytest.mark.invariant("FR-OPS-05")
async def test_a_placeholder_key_DOES_fail_when_the_receipt_is_required() -> None:
    code, message = await _check(
        REDIS_URL="redis://localhost:6379",
        BOLTRIG_AUDIT_HMAC_KEY="change-me-to-a-long-random-secret",
        BOLTRIG_FLEET_HEALTH_REQUIRE_RECEIPT="1",
    )
    assert code == 1 and "unusable" in message


@pytest.mark.invariant("FR-OPS-05")
async def test_an_unreachable_redis_is_a_failure(monkeypatch) -> None:
    """Configured and unreachable is the outage case - not "not checked"."""

    async def _unreachable(*a, **kw):
        return False, "unavailable"

    monkeypatch.setattr(
        "boltrig.fleet.stack_tool_receipts.read_fleet_tool_receipt", _unreachable
    )
    code, message = await _check(
        REDIS_URL="redis://127.0.0.1:1/0", BOLTRIG_AUDIT_HMAC_KEY=REAL_KEY
    )
    assert code == 1 and "unavailable" in message


# --- the OK path, through a REAL receipt ------------------------------------
def _signed_receipt(*, tenant: str, age_s: float, ok: bool = True) -> str:
    """Exactly what the publisher writes, aged by `age_s`."""
    key = receipt_signing_key({"BOLTRIG_AUDIT_HMAC_KEY": REAL_KEY})
    assert key is not None
    return _receipt_payload(
        {tool_id: ok for tool_id in _FLEET_TOOL_IDS},
        key,
        tenant,
        now=time.time() - age_s,
    )


@pytest.mark.invariant("FR-OPS-05")
def test_a_fresh_signed_receipt_validates() -> None:
    """The OK path proven against the real validator: without this, a probe that
    always refused would pass every other test in this file."""
    key = receipt_signing_key({"BOLTRIG_AUDIT_HMAC_KEY": REAL_KEY})
    assert key is not None
    ok, reason = validate_fleet_tool_receipt(
        _signed_receipt(tenant="acme", age_s=1.0),
        max_age_s=60.0,
        signing_key=key,
        tenant_id="acme",
    )
    assert ok and reason == "ok"


@pytest.mark.invariant("FR-OPS-05")
def test_a_receipt_that_is_merely_PRESENT_is_not_enough() -> None:
    """Freshness is the liveness half. A dead heartbeat loop leaves a perfectly
    readable, perfectly signed receipt behind until Redis evicts it, so a probe
    that only checked the signature would call a stopped worker healthy."""
    key = receipt_signing_key({"BOLTRIG_AUDIT_HMAC_KEY": REAL_KEY})
    assert key is not None
    ok, reason = validate_fleet_tool_receipt(
        _signed_receipt(tenant="acme", age_s=3600.0),
        max_age_s=60.0,
        signing_key=key,
        tenant_id="acme",
    )
    assert not ok and reason == "stale"


@pytest.mark.invariant("FR-OPS-05")
def test_another_tenants_receipt_does_not_answer_for_this_one() -> None:
    key = receipt_signing_key({"BOLTRIG_AUDIT_HMAC_KEY": REAL_KEY})
    assert key is not None
    ok, reason = validate_fleet_tool_receipt(
        _signed_receipt(tenant="other", age_s=1.0),
        max_age_s=60.0,
        signing_key=key,
        tenant_id="acme",
    )
    assert not ok, f"a receipt for another tenant validated ({reason})"


@pytest.mark.invariant("FR-OPS-05")
def test_the_receipt_key_is_namespaced_per_tenant() -> None:
    key = receipt_signing_key({"BOLTRIG_AUDIT_HMAC_KEY": REAL_KEY})
    assert key is not None
    assert _receipt_key("acme", key) != _receipt_key("other", key)
