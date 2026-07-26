"""`boltrig fleet-health` - a readiness probe for a process that serves no HTTP.

The fleet worker's container healthcheck was `python -c "import boltrig"`. That
proves an interpreter can import a module. It does not prove the pump is claiming
work, that the store is reachable, or that the worker's own tools are present -
and it cannot go red for any outage that matters. It was recorded as an open debt
in docs/refactoring/health-claim-exemptions.json rather than fixed, because
`python -m boltrig.api.worker` exposes no endpoint to point a probe at.

It does, however, already publish evidence. Every heartbeat the worker signs a
short-lived receipt into Redis saying which of its tools probed ok
(`fleet/stack_tool_receipts.py`), and the KERNEL's /readyz already consumes it.
So the readiness surface existed; nothing on the worker side read it back.

This reads its own receipt and exits:

    0  the receipt is present, authentic for this tenant, FRESH, and every tool
       reported ok - which means the heartbeat loop ran within the TTL, so the
       worker is alive AND its tools are sound
    1  missing, stale, unauthenticated, degraded, or Redis unreachable

WHAT IT DELIBERATELY DOES NOT DO. When REDIS_URL is unset the heartbeat is
disabled by design and no receipt will ever exist. Exiting 1 there would make the
healthcheck permanently red on every offline deployment, which teaches operators
to ignore it - so it exits 0 and SAYS the check was not applicable. That is the
honest answer, and it is the one case where a green here means "could not look".
Setting BOLTRIG_FLEET_HEALTH_REQUIRE_RECEIPT=1 turns that into a failure for a
deployment that considers the heartbeat mandatory.
"""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import Mapping

_REQUIRE_ENV = "BOLTRIG_FLEET_HEALTH_REQUIRE_RECEIPT"


def _tenant(env: Mapping[str, str]) -> str:
    """The tenant the worker publishes under: the manifest's, else the default."""
    from boltrig.api.bootstrap import _DEFAULT_TENANT, _find_manifest

    path = _find_manifest()
    if path:
        try:
            from boltrig.config import load_manifest

            manifest = load_manifest(path)
        except Exception:  # a broken manifest is the worker's problem, not ours
            return _DEFAULT_TENANT
        return getattr(manifest, "tenant_id", None) or _DEFAULT_TENANT
    return _DEFAULT_TENANT


async def _check(env: Mapping[str, str]) -> tuple[int, str]:
    redis_url = str(env.get("REDIS_URL") or "").strip()
    if not redis_url:
        if env.get(_REQUIRE_ENV):
            return 1, "no REDIS_URL, and the receipt is required by configuration"
        return 0, (
            "NOT CHECKED: no REDIS_URL, so the heartbeat is disabled and no receipt "
            f"can exist. Set {_REQUIRE_ENV}=1 to treat this as a failure."
        )

    from boltrig.fleet.stack_tool_health import receipt_ttl
    from boltrig.fleet.stack_tool_receipts import (
        read_fleet_tool_receipt,
        receipt_signing_key,
    )

    signing_key = receipt_signing_key(env)
    if signing_key is None:
        # Same reasoning as the missing REDIS_URL above, and it is not theoretical:
        # a placeholder BOLTRIG_AUDIT_HMAC_KEY is REJECTED by design (an
        # audit-key-provisioning ruling - a receipt signed with the constant this
        # repository ships is forgeable by anyone who has cloned it), so on every
        # dev box the heartbeat is deliberately off and no receipt exists. Failing
        # here would paint those permanently red.
        if env.get(_REQUIRE_ENV):
            return 1, "audit HMAC key unusable, and the receipt is required"
        return 0, (
            "NOT CHECKED: the audit HMAC key is absent or a placeholder, so the "
            "heartbeat is disabled and no receipt can exist. Set "
            f"{_REQUIRE_ENV}=1 to treat this as a failure."
        )

    tenant = _tenant(env)
    # The TTL is the freshness bound the publisher writes under, so a receipt that
    # is merely PRESENT is not enough: an expired heartbeat loop leaves a readable
    # value behind until Redis evicts it.
    ok, reason = await read_fleet_tool_receipt(
        redis_url, tenant, 3.0, receipt_ttl(env), signing_key
    )
    if ok:
        return 0, f"fleet receipt ok (tenant={tenant})"
    return 1, f"fleet receipt {reason} (tenant={tenant})"


def main(argv: list[str] | None = None) -> int:
    code, message = asyncio.run(_check(os.environ))
    print(message, file=sys.stderr if code else sys.stdout)
    return code
