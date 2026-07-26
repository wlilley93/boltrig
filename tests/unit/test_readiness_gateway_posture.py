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
def test_whitespace_is_not_configuration():
    # Fail-safe direction: a blank-but-present var must not be read as "a gateway is configured",
    # which would report `unchecked` about a stack that genuinely has none.
    assert gateway_posture({"BOLTRIG_MODEL_GATEWAY_URL": "   "}) == (
        "disabled",
        "health_check_disabled",
    )
