"""The claim-time lease token, and the only fenced way to write a claimed row.

[2026] VJS-CC-BOLTRIG-WORK-ITEM-LEASE-FENCE-001, D2/D3/D5/D8/D9.

Two workers can hold the same work item. Nothing renews a lease, so a step that
outruns ``lease_seconds`` is handed to a SECOND executor while the first is still
running, and the loser's write lands on top of the winner's: ``attempts``,
``result`` and the terminal status all clobbered.

The fence is a conditional write evaluated by the backend in the same statement as
the update (``Store.update_work_item_if_leased``). What matters is where its
expected value comes from. An earlier ``_still_leased`` helper compared the row
against the body's OWN read, and a reviewer who applied it reproduced the original
defect exactly: a read-then-write check cannot decide a read-then-write race. So
the expected tuple is MINTED AT CLAIM - it is whatever ``claim_work_item``
returned - and carried to the writing body. It is never re-derived there.

Carried HOW is the part with a trap in it. The durable lane hands the body to a
Hatchet engine in another process, so the token crosses a JSON boundary, and
``lease_expires_at`` is a timestamptz. ``datetime.isoformat`` /
``datetime.fromisoformat`` round-trip microseconds and offset exactly, which
matters because the fence compares for equality: a token that loses a microsecond
in transit refuses every legitimate write instead of only the losing ones.

The token reaches the write sites through a ContextVar rather than through five
signatures. Each asyncio task gets its own copy and ``create_task`` copies the
current context, so concurrent items cannot see each other's token, and a body
that was never bound writes unfenced and SAYS SO in the log rather than pretending.

D9, the honest limit, restated here because this is where a reader would look:
this makes the RECORD single-writer. It does NOT make execution exactly-once. The
worker that lost its lease is still running and has already called out to models,
adapters and the world; all the fence does is stop it landing its answer. Anything
that needs a step to happen once must be idempotent on its own account.
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from boltrig.models import WorkItem
    from boltrig.store import Store

log = logging.getLogger(__name__)

OWNER_KEY = "lease_owner"
EXPIRES_KEY = "lease_expires_at"


@dataclass(frozen=True)
class LeaseToken:
    """The (owner, expiry) pair a claim handed out. Compared for exact equality."""

    owner: str | None
    expires_at: datetime | None


_current: ContextVar[LeaseToken | None] = ContextVar("boltrig_lease_token", default=None)


def encode(item: WorkItem) -> dict[str, Any]:
    """The claim-time token, as payload keys that survive the JSON boundary."""
    expires = item.lease_expires_at
    return {
        OWNER_KEY: item.lease_owner,
        EXPIRES_KEY: expires.isoformat() if expires is not None else None,
    }


def decode(payload: dict[str, Any]) -> LeaseToken | None:
    """Read the token back, or None when the payload predates it.

    A payload without the keys is not an error: an item enqueued by an older
    worker is still in flight during a rolling restart. It writes unfenced, which
    is what it did before, and the write path logs that it was unfenced.
    """
    if OWNER_KEY not in payload and EXPIRES_KEY not in payload:
        return None
    raw = payload.get(EXPIRES_KEY)
    expires: datetime | None = None
    if isinstance(raw, datetime):  # the offline lane never serialises
        expires = raw
    elif isinstance(raw, str):
        try:
            expires = datetime.fromisoformat(raw)
        except ValueError:
            log.warning("undecodable lease expiry %r; writing unfenced", raw)
            return None
    return LeaseToken(owner=payload.get(OWNER_KEY), expires_at=expires)


def bind(token: LeaseToken | None) -> None:
    """Make ``token`` the fence for every write on this task."""
    _current.set(token)


def current() -> LeaseToken | None:
    return _current.get()


def matches(item: WorkItem, token: LeaseToken | None) -> bool:
    """Does this row still carry the lease the token names?

    Used ONLY as an early exit before doing work - never as the fence. It can be
    wrong in the safe direction (the lease is lost a moment after the check) and
    cannot be wrong in the unsafe one.
    """
    if token is None:
        return True
    return item.lease_owner == token.owner and item.lease_expires_at == token.expires_at


async def write(store: Store, item: WorkItem, *, what: str) -> bool:
    """Write a claimed row, fenced on the claim-time token. Returns whether it wrote.

    D5: a refused write is a NO-OP plus a warning, never a raise. An exception
    here would reach ``_record_failure``, which would re-open an item another
    worker has already settled - turning a harmless lost race into a second full
    execution of the work.

    D8: a refusal is never swallowed. Every caller either sees ``False`` or reads
    this log line; no consume-or-delete may be added on the refused path, because
    a cancel that was refused has NOT been recorded and the thing it was going to
    consume is the only evidence left that it was requested.
    """
    token = _current.get()
    if token is None:
        log.warning(
            "unfenced work-item write (%s) for item %s: no claim-time lease token "
            "on this task; a concurrent worker could overwrite it",
            what, item.id,
        )
        await store.update_work_item(item)
        return True
    wrote = await store.update_work_item_if_leased(
        item, lease_owner=token.owner, lease_expires_at=token.expires_at
    )
    if not wrote:
        log.warning(
            "lease lost: refusing the %s write for item %s (tenant %s). Another "
            "worker holds the claim and its record stands; this body is still "
            "running and its effects have already happened",
            what, item.id, item.tenant_id,
        )
    return wrote
