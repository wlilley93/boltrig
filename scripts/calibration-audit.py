#!/usr/bin/env python3
"""Consequence-calibration audit ([2026] VJS-APPEAL 1, obiter of LJ-2).

The Court of Appeal affirmed that LOW-consequence verbs run with no synchronous
human veto BY DESIGN, and that the one residual concern is a genuinely
effect-bearing verb mistakenly sitting at LOW (so no human is ever asked before it
acts). This audit surfaces those candidates for HUMAN review; it does NOT auto-
escalate (which verbs deserve a human gate is a policy call). To act on a finding,
recalibrate as DATA: mark the verb ``consequence: HIGH`` or add it to
``manifest.hitl.blocking_verbs`` - never a codex-side gate.

It only REPORTS (exit 0). Run it periodically, or wire it into a review cadence.

Usage:
  scripts/calibration-audit.py                 # audit the default tenant
  scripts/calibration-audit.py --tenant acme
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import re

# Action segments that suggest a real, non-idempotent side effect. Matched against
# the verb's LAST dotted segment (the ACTION), not the whole id, so a read like
# opbox.charge.list or opbox.agent.grant.get is NOT flagged for a side-effect word
# in its noun. A LOW verb whose action is one of these is a candidate for review
# (it may be a legitimate LOW operation, but a human should confirm it is not a
# destructive write running with no veto).
_SIDE_EFFECT_TOKENS = (
    "delete", "destroy", "drop", "remove", "purge", "terminate", "kill", "cancel",
    "create", "write", "update", "upsert", "insert", "set", "put", "patch", "post",
    "send", "email", "publish", "deploy", "release", "pay", "charge", "transfer",
    "grant", "revoke", "approve", "reject", "escalate", "submit", "execute", "run",
    "provision", "deprovision", "rotate", "reset", "invite", "assign",
)
_TOKEN_RE = re.compile(r"(?:^|[._-])(" + "|".join(_SIDE_EFFECT_TOKENS) + r")(?:$|[._-])")


async def _run(tenant: str) -> int:
    from boltrig.api.bootstrap import build_store
    from boltrig.config import load_settings
    from boltrig.models import Consequence
    from boltrig.store.postgres import set_current_tenant

    settings = load_settings()
    blocking = set(getattr(settings, "blocking_verbs", None) or [])
    # blocking_verbs lives on the manifest; load it if the settings object lacks it.
    if not blocking:
        try:
            from boltrig.config.manifest import load_manifest

            from boltrig.api.bootstrap import _find_manifest  # type: ignore[attr-defined]

            path = _find_manifest()
            if path:
                blocking = load_manifest(path).blocking_verbs()
        except Exception:
            blocking = set()

    store = await build_store()
    try:
        set_current_tenant(tenant)
        verbs = await store.list_verbs(tenant)
        candidates = [
            v for v in verbs
            if v.consequence == Consequence.LOW
            and v.id not in blocking
            and _TOKEN_RE.search(v.id.rsplit(".", 1)[-1].lower())
        ]
        total = len(verbs)
        high = sum(1 for v in verbs if v.consequence == Consequence.HIGH)
        print(f"calibration-audit (tenant '{tenant}'): {total} verbs, "
              f"{high} HIGH, {len(blocking)} blocking-listed.")
        if not candidates:
            print("  no LOW verbs with side-effect-suggesting names outside the "
                  "blocking list. Calibration looks sane.")
            return 0
        print(f"  {len(candidates)} LOW verb(s) whose NAME suggests a side effect - "
              "REVIEW whether each should be HIGH / blocking:")
        for v in sorted(candidates, key=lambda x: x.id):
            print(f"    - {v.id}")
        print("  To gate one: set its consequence: HIGH, or add it to "
              "manifest.hitl.blocking_verbs (data recalibration, no code).")
        return 0
    finally:
        close = getattr(store, "close", None)
        if close is not None:
            result = close()
            if inspect.isawaitable(result):
                await result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Consequence-calibration audit.")
    parser.add_argument("--tenant", default=None, help="tenant (default: session tenant)")
    args = parser.parse_args(argv)
    from boltrig.config import load_settings

    tenant = args.tenant or load_settings().session_tenant or "default"
    return asyncio.run(_run(tenant))


if __name__ == "__main__":
    raise SystemExit(main())
