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
        out[k] = _scrub_value(v)
    return out


def _scrub_value(v: Any) -> Any:
    if isinstance(v, str):
        if pii.contains_secret(v):
            digest = hashlib.sha256(v.encode()).hexdigest()[:16]
            return {"_scrubbed": True, "digest": digest, "size": len(v)}
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
) -> tuple[bool, int | None]:
    """Re-derive a tamper-evidence hash chain for a tenant from seq 1 upward.

    Pages ASCENDING through the store's scan seam (rows with seq > after, oldest
    first), so the ENTIRE chain is re-derived no matter its length (SEC-168). A
    bounded tail window would both cry wolf on an untampered long chain (the
    window's first row chains to a hash outside it while ``prev`` seeds None)
    and never see tampering below the window. ``scan`` is ``store.audit_scan``
    or ``store.security_scan``; ``canonical`` is the matching serialiser.
    Returns (ok, first_bad_seq)."""
    prev: str | None = None
    after = 0
    page = max(1, page_size)
    while True:
        events = await scan(tenant_id, after, page)
        if not events:
            return (True, None)
        for e in events:
            expected = hmac.new(_HMAC_KEY, canonical(e).encode(), hashlib.sha256).hexdigest()
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

    async def verify(self, tenant_id: str, *, page_size: int = 1000) -> tuple[bool, int | None]:
        """Re-derive the WHOLE chain from seq 1 (SEC-168). Returns (ok, first_bad_seq)."""
        return await verify_chain(self._store.audit_scan, _canonical, tenant_id, page_size)
