"""`boltrig audit-verify` runs ``AuditWriter.verify`` from a shell, so a cron or a
probe can re-derive the tamper-evidence chain without a Python session.

WHY THIS EXISTS. The audit chain is the system's claim to tamper evidence, and
until 2026-07-30 NOTHING READ IT. AuditWriter.verify was reachable only from
Python; there was no subcommand and no schedule. The beelink's chain had been
failing since 2026-07-24 - 38 rows, six days - and nobody knew, because a ledger
nobody re-derives supplies the appearance of tamper evidence and none of it.

An immutable ledger is not evidence. A ledger somebody CHECKS is evidence.

Exit codes are the point, because this is meant to be run by a cron or a probe:

    0  every row from seq 1 re-derives under the key that was current when it
       was written (retired epochs honoured)
    1  a row does not re-derive - either the chain was altered, or a key was
       rotated without recording BOLTRIG_AUDIT_HMAC_RETIRED
    2  the check could not run at all (no DATABASE_URL, store unreachable)

Exit 2 is deliberately NOT 0. A check that cannot look must not report success -
that is the failure this whole file exists to answer.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys


async def _verify(tenant_id: str, from_seq: int = 0) -> tuple[int, str]:
    dsn = os.environ.get("DATABASE_URL") or os.environ.get("BOLTRIG_DATABASE_URL")
    if not dsn:
        return 2, "no DATABASE_URL: cannot verify, and cannot call that success"

    from boltrig.kernel.audit import AuditWriter, _retired_epochs
    from boltrig.store.postgres import PostgresStore, normalize_dsn

    try:
        store = await PostgresStore.connect(
            normalize_dsn(dsn),
            apply_schema=False,
            rls=os.environ.get("BOLTRIG_RLS") == "1",
        )
    except Exception as exc:  # unreachable store is "could not look", not "fine"
        return 2, f"store unreachable: {type(exc).__name__}: {exc}"

    try:
        epochs = _retired_epochs()
        writer = AuditWriter(store)
        seed = None
        skipped = ""
        if from_seq > 1:
            # Seed prev from the row BEFORE the segment. Without it the segment's
            # first row chains to a hash outside the window and a sound chain
            # reports a break - the cry-wolf verify_chain's docstring warns of.
            rows = await store.audit_scan(tenant_id, from_seq - 2, 1)
            if not rows:
                return 2, f"no row at seq {from_seq - 1} to seed the segment from"
            seed = rows[0].hash
            skipped = (
                f"  SEGMENT ONLY: rows 1..{from_seq - 1} were NOT CHECKED. "
                f"This says nothing about them.\n"
            )
        ok, first_bad = await writer.verify(
            tenant_id, start_after=max(0, from_seq - 1), seed_prev=seed
        )
    finally:
        await store.close()

    epoch_note = (
        f" ({len(epochs)} retired key epoch(s), boundaries "
        f"{[b for b, _ in epochs]})"
        if epochs
        else " (no retired key epochs registered)"
    )
    if ok:
        scope = f"from seq {from_seq} " if from_seq > 1 else ""
        return 0, f"{skipped}audit chain verifies {scope}for tenant={tenant_id}{epoch_note}"
    return 1, skipped + (
        f"AUDIT CHAIN DOES NOT VERIFY for tenant={tenant_id}: first bad seq "
        f"{first_bad}{epoch_note}. Either the chain was altered, or a key was "
        f"rotated without recording it in BOLTRIG_AUDIT_HMAC_RETIRED."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="boltrig audit-verify")
    parser.add_argument(
        "--from-seq",
        type=int,
        default=0,
        help=(
            "verify only from this seq upward, seeded from the preceding row. "
            "Use when an UNREPAIRABLE break below it would otherwise abort the "
            "walk and leave every later row permanently unchecked. It prints the "
            "skipped range, because skipping is exactly how a real break gets missed."
        ),
    )
    parser.add_argument(
        "--tenant",
        default=os.environ.get("BOLTRIG_TENANT_ID", "default"),
        help="tenant whose chain to re-derive (default: default)",
    )
    args = parser.parse_args(argv)
    code, message = asyncio.run(_verify(args.tenant, args.from_seq))
    print(message, file=sys.stderr if code else sys.stdout)
    return code
