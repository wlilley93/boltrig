"""`/readyz` must not call a live dependency "disabled".

Found on the Classical Visas production tenant, 2026-07-26:

    {"status": "ready", "checks": {..., "model_gateway": "disabled"}}

while BOLTRIG_MODEL_GATEWAY_URL=http://bifrost:8080/v1 - every agent turn routing through it. The
check keyed on the health OPT-INS and not on the var that puts the gateway in the REQUEST PATH, so
the stack read ready with bifrost face-down and every agent turn failing.

"disabled" is indistinguishable from "this stack uses no model gateway". An operator reading it
concludes there is nothing to check. The true state is "there IS one and nothing is watching it" -
a different fact, and the one that would explain the outage.
"""

import pytest

from boltrig.fleet.model_gateway import gateway_posture


@pytest.mark.unit
def test_a_configured_gateway_with_no_probe_is_unchecked_not_disabled():
    # THE live state on CV. The whole point is that these two are not the same word.
    status, reason = gateway_posture({"BOLTRIG_MODEL_GATEWAY_URL": "http://bifrost:8080/v1"})
    assert status == "unchecked", "a gateway in the request path is not 'disabled'"
    assert reason == "configured_but_health_check_disabled"


@pytest.mark.unit
def test_no_gateway_at_all_is_still_disabled():
    # The word has to keep meaning something, or the fix is just a rename.
    assert gateway_posture({}) == ("disabled", "health_check_disabled")


@pytest.mark.unit
@pytest.mark.parametrize(
    "env",
    [
        {"BOLTRIG_MODEL_GATEWAY_HEALTH": "1"},
        {"BOLTRIG_MODEL_GATEWAY_HEALTH_URL": "http://bifrost:8080/healthz"},
        {"BOLTRIG_MODEL_GATEWAY_URL": "http://b", "BOLTRIG_MODEL_GATEWAY_HEALTH": "true"},
    ],
)
def test_an_armed_probe_is_enabled_and_carries_no_excuse(env):
    assert gateway_posture(env) == ("enabled", None)


@pytest.mark.unit
@pytest.mark.invariant("FR-OPS-03")
@pytest.mark.parametrize("disabled", ["0", "false", "off", "no"])
def test_an_explicit_false_health_flag_does_not_arm_a_probe(disabled):
    """Manifest export writes ``0`` for disabled; it is not configuration truth.

    The live failure was a split-brain readiness result: ``gateway_posture``
    treated the non-empty string as enabled while ``ModelGatewayStatusProvider``
    correctly declined to poll it.  Readiness then required an ``ok`` live probe
    which, by configuration, could never exist.
    """

    assert gateway_posture(
        {
            "BOLTRIG_MODEL_GATEWAY_URL": "http://bifrost:8080/v1",
            "BOLTRIG_MODEL_GATEWAY_HEALTH": disabled,
        }
    ) == ("unchecked", "configured_but_health_check_disabled")


@pytest.mark.unit
def test_whitespace_is_not_configuration():
    # Fail-safe direction: a blank-but-present var must not be read as "a gateway is configured",
    # which would report `unchecked` about a stack that genuinely has none.
    assert gateway_posture({"BOLTRIG_MODEL_GATEWAY_URL": "   "}) == (
        "disabled",
        "health_check_disabled",
    )
