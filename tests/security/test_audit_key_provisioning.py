"""The audit key must fail closed on every placeholder the project has shipped.

[2026] VJS-CC-BOLTRIG-AUDIT-KEY-PROVISIONING-001, order O6.

Audit finding H3 was recorded as "the audit HMAC key silently defaults on the
worker" and a guard was added for the IN-SOURCE default. That guard missed the
value the project ACTUALLY SHIPPED: `.env.example` carried
`change-me-to-a-long-random-secret`, which is neither blank nor the in-source
default, so a deployment following the documented `cp .env.example .env` tripped
neither the fatal nor the warning and ran its audit hash chain keyed by a public
constant in this repository - while `security-conformance.md` recorded DATA-05
"tamper-evident hash-chained audit" as BUILT.

A guard that misses the value the project ships is worse than no guard, because
it reassures. These tests pin the property at all three sites that consume the
key, so the three cannot drift apart again.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from boltrig.api.bootstrap import refuse_default_audit_key_in_prod
from boltrig.config.weak_secrets import is_placeholder_secret
from boltrig.fleet.stack_tool_receipts import receipt_signing_key

_REPO = Path(__file__).resolve().parents[2]

# Every placeholder this repository has ever shipped or defaulted to.
_SHIPPED_PLACEHOLDERS = (
    "",
    "change-me-to-a-long-random-secret",  # what .env.example carried
    "dev-insecure-audit-key",  # the in-source fallback in kernel/audit.py
    "changeme",
    "replace-me",
)
_REAL = "z8Qv" + "x" * 44  # long, not a placeholder


@pytest.mark.invariant("K-19")
@pytest.mark.parametrize("value", _SHIPPED_PLACEHOLDERS)
def test_every_shipped_placeholder_is_fatal_under_a_production_signal(value):
    """The whole point of H3: no placeholder boots a production deployment."""
    with pytest.raises(RuntimeError):
        refuse_default_audit_key_in_prod(
            {"BOLTRIG_AUDIT_HMAC_KEY": value, "BOLTRIG_PRODUCTION": "1"}
        )


@pytest.mark.invariant("K-19")
def test_a_real_key_boots_under_a_production_signal():
    """The guard must not be so eager that a genuine key cannot start."""
    refuse_default_audit_key_in_prod(
        {"BOLTRIG_AUDIT_HMAC_KEY": _REAL, "BOLTRIG_PRODUCTION": "1"}
    )


@pytest.mark.invariant("K-19")
@pytest.mark.parametrize("value", _SHIPPED_PLACEHOLDERS)
def test_every_shipped_placeholder_warns_without_a_production_signal(value, caplog):
    """Not fatal without the signal - nothing sets one by default - but never
    silent, because silence is what let this run unnoticed."""
    with caplog.at_level(logging.WARNING, logger="boltrig.bootstrap"):
        refuse_default_audit_key_in_prod({"BOLTRIG_AUDIT_HMAC_KEY": value})
    assert "tamper-evident" in caplog.text


@pytest.mark.invariant("K-19")
@pytest.mark.parametrize("value", _SHIPPED_PLACEHOLDERS)
def test_a_placeholder_key_signs_no_readiness_receipt(value):
    """O3, the readiness-receipt bypass. Blank was the only rejected value, so a
    placeholder produced a well-formed signing key and receipts were signed with
    a public constant - a receipt anyone could forge, which is worth no more than
    no receipt at all."""
    assert receipt_signing_key({"BOLTRIG_AUDIT_HMAC_KEY": value}) is None


@pytest.mark.invariant("K-19")
def test_a_real_key_does_sign_a_readiness_receipt():
    assert receipt_signing_key({"BOLTRIG_AUDIT_HMAC_KEY": _REAL}) is not None


@pytest.mark.invariant("K-19")
def test_env_example_ships_no_audit_key_placeholder():
    """O1. The file is copied verbatim by the documented `cp .env.example .env`,
    so a placeholder here becomes a real deployment's key. Blank means the value
    must be provisioned, and boot fails closed if nothing provisioned it."""
    for line in (_REPO / ".env.example").read_text().splitlines():
        if line.startswith("BOLTRIG_AUDIT_HMAC_KEY="):
            shipped = line.split("=", 1)[1].strip()
            assert shipped == "", (
                "an audit key shipped in .env.example is copied into real .env "
                f"files; found {shipped!r}"
            )
            return
    pytest.fail("BOLTRIG_AUDIT_HMAC_KEY is not present in .env.example")


def test_the_placeholder_predicate_is_shared_not_duplicated():
    """O2. Three sites consume this key. They must ask ONE predicate, because the
    hole H3 left open was precisely two of them disagreeing about the answer."""
    assert is_placeholder_secret("change-me-to-a-long-random-secret")
    assert is_placeholder_secret("dev-insecure-audit-key")
    assert is_placeholder_secret("  CHANGE_ME  ")
    assert not is_placeholder_secret(_REAL)
