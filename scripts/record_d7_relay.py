#!/usr/bin/env python3
"""Record the D7 notice relay on the cv tenant's security stream (D7-V2).

[2026] VJS-CC-BOLTRIG-D7-DISCHARGE-001 varied D7 of the development-posture
order: the Principal relays the drafted notice himself (V1), and the stack then
writes a host-boundary security event in the CLIENT'S OWN tenant database
recording that the relay happened (V2). The row is the varied checkable - it
keeps the property the original outbox row had, that the client can discover the
record from her own deployment - and it asserts the RELAY, never a delivery the
stack did not perform.

ORDER OF OPERATIONS IS THE POINT. This runs only AFTER the Principal states the
relay happened, because a row asserting a relay that has not happened is the
inverse of the expired-unheard defect the original order refused, and worse than
it. That is why --relay-date and --channel-class are REQUIRED with no defaults:
they are the V1 facts only the Principal can supply, and their absence means V1
has not been stated.

Run inside the cv kernel container (the host boundary), e.g.:

    docker exec cv-boltrig-kernel-1 python scripts/record_d7_relay.py \
        --relay-date 2026-08-01 --channel-class in-person
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import sys
from pathlib import Path

# The facts the ORDER fixes, not parameters. The notice path and the audit range
# are part of the directive's text; making them flags would let a later run
# record the relay of a different document under this order's name.
NOTICE_PATH = Path("docs/findings/2026-07-31-cv-client-notice-D7.md")
AUDIT_SEQ_RANGE = "262-266"
SUBJECT = "info@classicalvisas.com"
REASON = "d7_notice_relayed"
ORDER = "2026-VJS-CC-BOLTRIG-D7-DISCHARGE-001"


def notice_sha256(root: Path) -> str:
    """The digest V1 pins at the moment of relay - of the file as it stands."""
    return hashlib.sha256((root / NOTICE_PATH).read_bytes()).hexdigest()


def relay_detail(
    *, digest: str, relay_date: str, channel_class: str
) -> dict[str, str]:
    """The exact detail shape D7-V2 names. One place, so the test and the run
    cannot drift: a row missing any of these fields is not the checkable."""
    return {
        "order": ORDER,
        "notice_sha256": digest,
        "channel_class": channel_class,
        "relay_date": relay_date,
        "audit_seq_range": AUDIT_SEQ_RANGE,
    }


async def _run(relay_date: str, channel_class: str, root: Path) -> int:
    from boltrig.api.bootstrap import build_store
    from boltrig.api.host_boundary import write_host_boundary_security_event
    from boltrig.store.postgres import set_current_tenant

    digest = notice_sha256(root)
    store = await build_store()
    try:
        set_current_tenant("default")
        await write_host_boundary_security_event(
            store,
            tenant="default",
            subject=SUBJECT,
            reason=REASON,
            detail=relay_detail(
                digest=digest, relay_date=relay_date, channel_class=channel_class
            ),
        )
    finally:
        close = getattr(store, "close", None)
        if close is not None:
            result = close()
            if asyncio.iscoroutine(result):
                await result
    print(f"recorded {REASON}: notice sha256={digest} relayed {relay_date} via {channel_class}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--relay-date",
        required=True,
        help="the date the Principal states the relay happened (V1 fact; no default)",
    )
    parser.add_argument(
        "--channel-class",
        required=True,
        help="the channel class the Principal states was used (V1 fact; no default)",
    )
    parser.add_argument("--root", default=".", help="repo root holding the notice file")
    args = parser.parse_args(argv)
    if not (args.relay_date or "").strip() or not (args.channel_class or "").strip():
        print("record_d7_relay: the V1 facts may not be blank", file=sys.stderr)
        return 2
    return asyncio.run(_run(args.relay_date.strip(), args.channel_class.strip(), Path(args.root)))


if __name__ == "__main__":
    raise SystemExit(main())
