"""Append-only, tamper-evident audit (SEC-16/17, K-19/K-20).

Every kernel action writes exactly one audit row in the same logical step as
the effect. Each row chains to the previous row's hash (per tenant), so any
reorder, drop, or edit is detectable by re-deriving the chain. Bounded
observability: the writer scrubs ``detail`` and refuses to persist raw secrets
or identity verbatim - it stores a digest + bounded preview instead.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
from collections.abc import Awaitable, Callable
from typing import Any

from boltrig.models import AuditEvent, utcnow
from boltrig.store import Store

from . import pii

_HMAC_KEY = os.environ.get("BOLTRIG_AUDIT_HMAC_KEY", "dev-insecure-audit-key").encode()
_PREVIEW_LEN = 256

# ── Key epochs: rotation without destroying the history you rotated away from ─────────────
# The chain is re-derived from seq 1 under ONE key, so rotating BOLTRIG_AUDIT_HMAC_KEY made
# every pre-rotation row fail verification for good. Observed live on the Classical Visas
# tenant 2026-07-26: its key was the shipped `.env.example` placeholder, so the chain was
# forgeable by anyone with the repo; re-keying it was plainly right, and it cost verification
# of all 111 prior rows.
#
# That cost is the real defect, because it prices rotation at "lose your history" and so
# argues for never rotating a LEAKED key. It also destroys signal: a permanently failing
# verify is indistinguishable from tampering, and a check that always fails is one people
# learn to ignore.
#
# An epoch fixes both. A retired key is kept for VERIFICATION ONLY and is bounded by the seq
# at which it was retired: a row below that boundary may verify under it, a row at or above
# it may not. The bound is load-bearing, not bookkeeping - without it, anyone holding a
# retired key (and here one of them is a PUBLIC constant) could append new rows that verify
# perfectly. Writes always use the current key; only reads consult the epochs.
#
#   BOLTRIG_AUDIT_HMAC_RETIRED="<retired_at_seq>:<key>[,<retired_at_seq>:<key>...]"
#
# Unset => one key, exactly the previous behaviour.
_RETIRED_ENV = "BOLTRIG_AUDIT_HMAC_RETIRED"


def _retired_epochs() -> list[tuple[int, bytes]]:
    """[(retired_at_seq, key)] oldest boundary first; malformed entries are ignored.

    Parsed per verification rather than at import so a rotation is picked up without a
    restart, and so a test can set it. Ignoring a malformed entry is the fail-safe
    direction: the row then falls through to the current key and fails honestly, which is
    the pre-epoch behaviour - never a silent accept.
    """
    raw = os.environ.get(_RETIRED_ENV, "").strip()
    if not raw:
        return []
    epochs: list[tuple[int, bytes]] = []
    for part in raw.split(","):
        boundary, _, key = part.strip().partition(":")
        if not key or not boundary.strip().isdigit():
            continue
        epochs.append((int(boundary.strip()), key.encode()))
    return sorted(epochs, key=lambda e: e[0])


def _key_for_seq(seq: int | None, epochs: list[tuple[int, bytes]]) -> bytes:
    """The ONE key a row at ``seq`` is allowed to verify under.

    The first epoch whose boundary the row predates wins; a row at or after every boundary
    belongs to the live key. Exactly one key per row - never "try them all" - so a retired
    key can only ever vouch for the range it actually sealed.
    """
    if seq is not None:
        for boundary, key in epochs:
            if seq < boundary:
                return key
    return _HMAC_KEY


def key_in_force_at(seq: int | None) -> bytes:
    """The audit HMAC key that sealed - and therefore verifies - anything covering row ``seq``.

    Public because the ROLLUP ANCHOR (kernel/security_events.py) is keyed by the same secret and
    needs the same epoch answer. It did not have it, and that was a live defect: rotating the key
    on Classical Visas left the chain verifying row by row while `/v1/audit/verify` reported
    `anchor_intact: false`, so the endpoint said the audit was broken over an audit that was
    perfectly intact. A verifier that cries wolf after every rotation trains an operator to
    ignore it, which is worse than not having one.

    Both the WRITE and the READ side must call this with the segment's ``seq_end`` so they agree
    by construction. Anchoring a range that predates a boundary therefore seals with the retired
    key - which is not a new weakness, because those rows' own hashes are already under it.
    """
    return _key_for_seq(seq, _retired_epochs())


def _canonical(event: AuditEvent) -> str:
    """A stable serialisation of the fields the hash covers.

    The Opbox-depth fields ([2026] VJS-COUNTY 9, D1) are folded in ONLY when
    non-None. This keeps the change strictly additive: a row written before those
    fields existed (all None) canonicalises byte-for-byte identically to before,
    so its hash still verifies and the existing chain (and its tests) is
    unchanged. A row that actually carries e.g. an ip_address hashes WITH it, so
    tampering with the new fields is detected too."""
    body: dict = {
        "tenant_id": event.tenant_id,
        "seq": event.seq,
        "ts": event.ts.isoformat(),
        "run_id": event.run_id,
        "parent_run_id": event.parent_run_id,
        "actor": event.actor,
        "actor_tier": event.actor_tier,
        "depth": event.depth,
        "action_type": event.action_type.value,
        "noun": event.noun,
        "verb": event.verb,
        "target_adapter": event.target_adapter,
        "on_behalf_of": event.on_behalf_of,
        "status": event.status,
        "latency_ms": event.latency_ms,
        "tokens_used": event.tokens_used,
        "cost_micros": event.cost_micros,
        "skills_loaded": event.skills_loaded,
        "detail": event.detail,
        "prev_hash": event.prev_hash,
    }
    for key, val in (
        ("ip_address", event.ip_address),
        ("user_agent", event.user_agent),
        ("resource", event.resource),
        ("resource_id", event.resource_id),
        ("workspace_id", event.workspace_id),
    ):
        if val is not None:
            body[key] = val
    return json.dumps(body, sort_keys=True, separators=(",", ":"))


def _scrub(detail: dict) -> dict:
    """Bounded-observability scrub (K-20). Any string value carrying a secret or
    identity pattern is replaced by a digest + size + bounded preview, so the
    audit log can never become an exfiltration surface. Recurses through nested
    dicts AND list/tuple values - a secret inside a list-typed detail value is
    scrubbed too, not passed verbatim."""
    out: dict = {}
    for k, v in detail.items():
        out[_scrub_key(k)] = _scrub_value(v)
    return out


def _scrub_key(k: Any) -> Any:
    """Bring the KEY within the scrub.

    County Court, variation of CP3 on SUBMISSION-2026-07-27-124116 (CONVENING-county-2026-07-27-125100), head 5.
    This loop previously copied keys verbatim while scanning only values, so a
    caller-supplied dict key carrying a secret went into an append-only store
    untouched. The principal ratio reaches it without extension: a record of a
    failure is composed from what the system asserted, never from what the caller
    supplied.

    A key must stay a string (it is a dict key, and the known consumer at
    observability.py reads `id`/`verb_id`/`verb` by name), so a secret-bearing key
    collapses to a stable marker rather than to the digest DICT a value would get.
    """
    if not isinstance(k, str):
        return k
    if kind := pii.contains_secret(k):
        return f"[scrubbed:{kind}]"
    if pii.contains_identity(k):
        return pii.redact_identity(k)
    return k


def _scrub_value(v: Any) -> Any:
    if isinstance(v, str):
        # A SECRET taints its whole context: digest the value entire. An adjacent
        # fragment can carry the rest of the credential, so span substitution is
        # not enough here.
        if pii.contains_secret(v):
            digest = hashlib.sha256(v.encode()).hexdigest()[:16]
            return {"_scrubbed": True, "digest": digest, "size": len(v)}
        # IDENTITY data does not taint its context: cut out the span and leave the
        # rest readable. County Court, variation of CP3. Digesting the whole
        # value on an ipv4 false positive would make the record less legible than
        # leaving it alone, which is the opposite of what the order is for.
        if pii.contains_identity(v):
            return pii.redact_identity(v)[:_PREVIEW_LEN]
        return v[:_PREVIEW_LEN]
    if isinstance(v, dict):
        return _scrub(v)
    if isinstance(v, (list, tuple)):
        return [_scrub_value(item) for item in v]
    return v


async def verify_chain(
    scan: Callable[[str, int, int], Awaitable[list[Any]]],
    canonical: Callable[[Any], str],
    tenant_id: str,
    page_size: int,
    *,
    start_after: int = 0,
    seed_prev: str | None = None,
) -> tuple[bool, int | None]:
    """Re-derive a tamper-evidence hash chain for a tenant from seq 1 upward.

    Pages ASCENDING through the store's scan seam (rows with seq > after, oldest
    first), so the ENTIRE chain is re-derived no matter its length (SEC-168). A
    bounded tail window would both cry wolf on an untampered long chain (the
    window's first row chains to a hash outside it while ``prev`` seeds None)
    and never see tampering below the window. ``scan`` is ``store.audit_scan``
    or ``store.security_scan``; ``canonical`` is the matching serialiser.
    ``start_after``/``seed_prev`` verify a SEGMENT instead, and exist because this
    function returns at the FIRST bad row - so one unrepairable break makes every
    later row permanently unchecked. The beelink is the live case: a key rotated
    on 2026-07-24 without a recorded epoch left rows 368-405 unverifiable for good,
    and the walk aborts there, so the 300 rows written since say nothing about
    themselves. A check that can never speak about current data is one people stop
    reading.

    ``seed_prev`` is not optional decoration when ``start_after`` is set. The
    segment's first row chains to a hash OUTSIDE the segment, so seeding ``prev``
    as None would report a break on a sound chain - the exact cry-wolf this
    docstring warns about above. Pass the preceding row's stored hash.

    Returns (ok, first_bad_seq)."""
    prev: str | None = seed_prev
    after = max(0, int(start_after))
    page = max(1, page_size)
    # Resolved once per verification, not per row: a rotation cannot move mid-scan, and the
    # bound must be the same for every row or the answer depends on when it was read.
    epochs = _retired_epochs()
    while True:
        events = await scan(tenant_id, after, page)
        if not events:
            return (True, None)
        for e in events:
            key = _key_for_seq(e.seq, epochs)
            expected = hmac.new(key, canonical(e).encode(), hashlib.sha256).hexdigest()
            if e.prev_hash != prev or e.hash != expected:
                return (False, e.seq)
            prev = e.hash
        nxt = events[-1].seq or 0
        if nxt <= after:  # a misbehaving scan page must never loop forever
            return (False, events[-1].seq)
        after = nxt


class AuditWriter:
    def __init__(self, store: Store) -> None:
        self._store = store
        # SEC-16: serialise the read-head -> append per tenant so two concurrent
        # writes cannot both claim seq=N+1 (a unique-violation on Postgres thrown
        # from dispatch's finally, or a forked hash chain on the in-memory store).
        # One lock per tenant; for a multi-process deployment the Postgres
        # UNIQUE(tenant_id, seq) is the backstop.
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock(self, tenant_id: str) -> asyncio.Lock:
        lk = self._locks.get(tenant_id)
        if lk is None:
            lk = asyncio.Lock()
            self._locks[tenant_id] = lk
        return lk

    async def write(self, event: AuditEvent) -> AuditEvent:
        """Scrub, chain, and append. Returns the persisted event with seq/hash.
        The chain step is serialised per tenant so concurrent writes do not collide
        on the seq (SEC-16)."""
        event.detail = _scrub(event.detail)
        async with self._lock(event.tenant_id):
            head_seq, prev_hash = await self._store.audit_head(event.tenant_id)
            event.seq = head_seq + 1
            event.prev_hash = prev_hash
            if event.ts is None:
                event.ts = utcnow()
            digest = hmac.new(_HMAC_KEY, _canonical(event).encode(), hashlib.sha256).hexdigest()
            event.hash = digest
            await self._store.audit_append(event)
        return event

    async def verify(
        self,
        tenant_id: str,
        *,
        page_size: int = 1000,
        start_after: int = 0,
        seed_prev: str | None = None,
    ) -> tuple[bool, int | None]:
        """Re-derive the WHOLE chain from seq 1 (SEC-168). Returns (ok, first_bad_seq).

        ``start_after``/``seed_prev`` narrow it to a segment; see ``verify_chain``
        for why the seed is mandatory rather than convenient.
        """
        return await verify_chain(
            self._store.audit_scan,
            _canonical,
            tenant_id,
            page_size,
            start_after=start_after,
            seed_prev=seed_prev,
        )
