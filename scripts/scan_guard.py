#!/usr/bin/env python3
"""A scan that finds nothing must not report PASS.

Every gate in this directory works the same way: glob a tree, examine what comes
back, fail on the offenders. Which means every one of them has the same silent
failure available to it - if the glob returns an EMPTY list, there are no
offenders, and the gate prints PASS and exits 0 having verified nothing at all.

That is not hypothetical. It is one directory rename, one sparse checkout, one
`docker build` with a narrow context, one sdist that ships `boltrig/` and not
`deploy/`, away. The gate does not go red and tell you it could not look; it goes
green and tells you everything is fine. A gate whose whole purpose is refusing to
be reassuring when it should not be is the last place that belongs.

So the floor is explicit: a scan declares what it expects to find, and finding
nothing is a FAILURE with its own message, distinct from finding nothing WRONG.
The two outcomes read identically today and mean opposite things.

This exits the process rather than raising, because every caller is a CLI gate
whose only response would be to print and exit anyway, and because an exception
that a caller could swallow reintroduces exactly the silence being closed.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from typing import TypeVar

T = TypeVar("T")


def require_scanned(items: Sequence[T], what: str, *, minimum: int = 1) -> Sequence[T]:
    """Return ``items``, or exit 1 saying the scan found nothing to check.

    ``what`` names what was being looked for, in the terms a reader would need to
    go and check it themselves - "compose manifests under deploy/", not "files".
    """
    if len(items) >= minimum:
        return items
    print(
        f"FAIL: scanned nothing - expected at least {minimum} {what}, found "
        f"{len(items)}.\n"
        "      This is NOT 'nothing is wrong'. The gate could not look, which in a\n"
        "      truncated checkout or a narrow build context is exactly when a green\n"
        "      result is most misleading.",
        file=sys.stderr,
    )
    raise SystemExit(1)
