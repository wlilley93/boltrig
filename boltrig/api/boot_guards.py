"""The two boot guards that ABORT rather than warn on a production signal.

Lifted out of the composition root on 2026-07-31 because they are not wiring:
each is a self-contained refusal with its own precedent, its own tests, and no
dependency on anything the root assembles. bootstrap.py carries a structural
debt ratchet, and a module that grows every time an unrelated rule is added is
how a composition root becomes 700 lines of everything.

Both fail HARD. A warning is what you emit when the operator still has a choice;
neither of these leaves one - a header-trusting auth bypass and a forgeable audit
chain are both states in which the system's own claims about itself are false.
"""

from __future__ import annotations

import logging

from boltrig.config import production_signal

log = logging.getLogger("boltrig.api")

__all__ = ["refuse_default_audit_key_in_prod", "refuse_dev_auth_in_prod"]


def refuse_dev_auth_in_prod(env: dict | None = None) -> None:
    """Abort if dev auth is enabled with any production signal (IAM-09).

    The header-trusting resolver is a debug bypass; leaving it reachable in
    production is the #1 fast-build failure. Fail hard, do not merely warn."""
    signal = production_signal(env)
    if signal is not None:
        raise RuntimeError(
            f"FATAL: BOLTRIG_DEV_AUTH is set with a production signal ({signal}). "
            "Dev auth is a header-trusting bypass and must never run in production "
            "(IAM-09). Unset BOLTRIG_DEV_AUTH and configure OIDC_*."
        )


def refuse_default_audit_key_in_prod(env: dict | None = None) -> None:
    """Abort if the audit-chain HMAC key is unset/default with a production signal
    (K-19). The hash chain is only tamper-evident while the key is secret; shipping
    the in-source `dev-insecure-audit-key` in prod makes the chain forgeable. Fail
    hard, mirroring refuse_dev_auth_in_prod."""
    import os

    from boltrig.config.weak_secrets import is_placeholder_secret

    e = env if env is not None else os.environ
    signal = production_signal(e)
    key = e.get("BOLTRIG_AUDIT_HMAC_KEY")
    # [2026] VJS-CC-BOLTRIG-AUDIT-KEY-PROVISIONING-001. This used to compare
    # against the IN-SOURCE default and blank only, so the value .env.example
    # actually shipped (change-me-to-a-long-random-secret) tripped NEITHER this
    # fatal nor the warning below. A deployment following the documented
    # `cp .env.example .env` therefore ran the audit chain keyed by a public
    # constant in this repository while reporting itself tamper-evident. The
    # shared predicate knows every placeholder the project has ever shipped.
    if signal is not None and is_placeholder_secret(key):
        raise RuntimeError(
            f"FATAL: BOLTRIG_AUDIT_HMAC_KEY is unset/default with a production signal "
            f"({signal}). The audit chain is forgeable without a secret key (K-19). "
            "Set a strong BOLTRIG_AUDIT_HMAC_KEY."
        )
    if is_placeholder_secret(key):
        # No production signal, so this is not fatal - but the 2026-07-02 audit
        # called H3 "silently defaults", and the silence is the part that makes it
        # dangerous. Nothing sets a production signal by default (compose emits an
        # empty BOLTRIG_PRODUCTION), so a real deployment can reach here and run a
        # hash chain keyed by a public constant in this repository, believing the
        # audit log is tamper-evident. Say so, every boot.
        log.warning(
            "audit chain is using the IN-SOURCE default HMAC key: it is NOT "
            "tamper-evident. Anyone with this repository can forge the chain. "
            "Set BOLTRIG_AUDIT_HMAC_KEY (and a production signal) before trusting it."
        )
