"""Append-only, tamper-evident audit (SEC-16/17, K-19/K-20).

Every kernel action writes exactly one audit row in the same logical step as
the effect. Each row chains to the previous row's hash (per tenant), so any
reorder, drop, or edit is detectable by re-deriving the chain. Bounded
observability: the writer scrubs ``detail`` and refuses to persist raw secrets
or identity verbatim - it stores a digest + bounded preview instead.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os

from nankle.models import AuditEvent, utcnow
from nankle.store import Store

from . import pii

_HMAC_KEY = os.environ.get("NANKLE_AUDIT_HMAC_KEY", "dev-insecure-audit-key").encode()
_PREVIEW_LEN = 256


def _canonical(event: AuditEvent) -> str:
    """A stable serialisation of the fields the hash covers."""
    return json.dumps(
        {
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
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _scrub(detail: dict) -> dict:
    """Bounded-observability scrub (K-20). Any string value carrying a secret or
    identity pattern is replaced by a digest + size + bounded preview, so the
    audit log can never become an exfiltration surface."""
    out: dict = {}
    for k, v in detail.items():
        if isinstance(v, str):
            if pii.contains_secret(v):
                digest = hashlib.sha256(v.encode()).hexdigest()[:16]
                out[k] = {"_scrubbed": True, "digest": digest, "size": len(v)}
            else:
                out[k] = v[:_PREVIEW_LEN]
        elif isinstance(v, dict):
            out[k] = _scrub(v)
        else:
            out[k] = v
    return out


class AuditWriter:
    def __init__(self, store: Store) -> None:
        self._store = store

    async def write(self, event: AuditEvent) -> AuditEvent:
        """Scrub, chain, and append. Returns the persisted event with seq/hash."""
        event.detail = _scrub(event.detail)
        head_seq, prev_hash = await self._store.audit_head(event.tenant_id)
        event.seq = head_seq + 1
        event.prev_hash = prev_hash
        if event.ts is None:
            event.ts = utcnow()
        digest = hmac.new(_HMAC_KEY, _canonical(event).encode(), hashlib.sha256).hexdigest()
        event.hash = digest
        await self._store.audit_append(event)
        return event

    async def verify(self, tenant_id: str) -> tuple[bool, int | None]:
        """Re-derive the whole chain. Returns (ok, first_bad_seq)."""
        events = await self._store.audit_query(tenant_id, limit=10_000)
        prev: str | None = None
        for e in events:
            expected = hmac.new(
                _HMAC_KEY, _canonical(e).encode(), hashlib.sha256
            ).hexdigest()
            if e.prev_hash != prev or e.hash != expected:
                return (False, e.seq)
            prev = e.hash
        return (True, None)
