"""The distinct SecurityEvent stream + the audit rollup anchor ([2026] VJS-COUNTY 9).

D3 - a SEPARATE, tamper-evident (hash-chained) stream for security SIGNALS
(login failures, rate-limit trips, permission denials, MCP auth failures). It
uses the SAME chaining pattern as the business audit log (SEC-16/K-19) - one lock
per tenant serialises read-head -> append so two concurrent writes cannot fork
the chain - but it is its own table so signals never dilute the action trail and
can be watched on their own. Keys-only (K-20): the writer scrubs ``detail`` and a
row never carries a secret / password / session token.

D4 - a periodic ROLLUP ANCHOR over a contiguous audit-chain segment. The root
hash is a deterministic digest over the row hashes in the segment, so an anchor
lets a verifier confirm a segment has not been rewritten. The LOCAL dev-fallback
writes the anchor with no external call (``is_dev_fallback=True``); the RFC3161
TSA timestamp + external KMS signature are a clean seam left NULL until a
Principal wires the external credential (documented, never called live here).
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import os
import uuid

from boltrig.models import AuditEvent, AuditRollupAnchor, SecurityEvent, utcnow
from boltrig.store import Store

from .audit import _HMAC_KEY, _scrub, _scrub_free_text, key_in_force_at, verify_chain

log = logging.getLogger("boltrig.security")

# Dropped-signal counter (D3): a security_append failure must not break the
# guarded path, but swallowing it with no trace let a failing append silently
# disable the whole security stream - login-failure and permission-denial
# signals vanished with no symptom. The counter is the operator's symptom.
_dropped_signals = 0


def dropped_signal_count() -> int:
    """Security signals dropped by ``record()`` since process start."""
    return _dropped_signals

# Whether an external anchoring credential is configured. When absent (the
# default), the anchorer writes a LOCAL dev-fallback anchor and leaves the
# RFC3161 / KMS fields NULL. Wiring a live TSA/KMS is a Principal dependency: set
# these to point the seam at real infrastructure (not called from this module).
_TSA_URL_ENV = "BOLTRIG_AUDIT_TSA_URL"
_KMS_KEY_ENV = "BOLTRIG_AUDIT_KMS_KEY_ID"


def _security_canonical(event: SecurityEvent) -> str:
    """A stable serialisation of the fields the security-chain hash covers."""
    import json

    return json.dumps(
        {
            "tenant_id": event.tenant_id,
            "seq": event.seq,
            "ts": event.ts.isoformat(),
            "event_type": event.event_type.value,
            "reason": event.reason,
            "actor": event.actor,
            "actor_tier": event.actor_tier,
            "workspace_id": event.workspace_id,
            "ip_address": event.ip_address,
            "user_agent": event.user_agent,
            "resource": event.resource,
            "resource_id": event.resource_id,
            "on_behalf_of": event.on_behalf_of,
            "detail": event.detail,
            "prev_hash": event.prev_hash,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


class SecurityWriter:
    """Scrub, chain, and append a security signal. Mirrors ``AuditWriter`` (same
    per-tenant serialisation so the chain never forks under concurrency)."""

    def __init__(self, store: Store) -> None:
        self._store = store
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock(self, tenant_id: str) -> asyncio.Lock:
        lk = self._locks.get(tenant_id)
        if lk is None:
            lk = asyncio.Lock()
            self._locks[tenant_id] = lk
        return lk

    async def write(self, event: SecurityEvent) -> SecurityEvent:
        event.detail = _scrub(event.detail or {})
        event.user_agent = _scrub_free_text(event.user_agent, field="user_agent")
        async with self._lock(event.tenant_id):
            head_seq, prev_hash = await self._store.security_head(event.tenant_id)
            event.seq = head_seq + 1
            event.prev_hash = prev_hash
            if event.ts is None:
                event.ts = utcnow()
            digest = hmac.new(
                _HMAC_KEY, _security_canonical(event).encode(), hashlib.sha256
            ).hexdigest()
            event.hash = digest
            await self._store.security_append(event)
        return event

    async def verify(self, tenant_id: str, *, page_size: int = 1000) -> tuple[bool, int | None]:
        """Re-derive the WHOLE security chain from seq 1 (SEC-168).
        Returns (ok, first_bad_seq)."""
        return await verify_chain(
            self._store.security_scan, _security_canonical, tenant_id, page_size
        )

    async def record(
        self,
        tenant_id: str,
        event_type,
        reason: str,
        *,
        actor: str | None = None,
        actor_tier: str | None = None,
        workspace_id: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        resource: str | None = None,
        resource_id: str | None = None,
        on_behalf_of: str | None = None,
        detail: dict | None = None,
    ) -> None:
        """Fail-safe convenience the auth / ratelimit / grant paths call. Like the
        run-event relay, recording a security signal must NEVER break the caller's
        path - a write error is swallowed (the signal is best-effort observability,
        not a gate)."""
        try:
            await self.write(
                SecurityEvent(
                    tenant_id=tenant_id,
                    ts=utcnow(),
                    event_type=event_type,
                    reason=reason,
                    actor=actor,
                    actor_tier=actor_tier,
                    workspace_id=workspace_id,
                    ip_address=ip_address,
                    user_agent=user_agent,
                    resource=resource,
                    resource_id=resource_id,
                    on_behalf_of=on_behalf_of,
                    detail=detail or {},
                )
            )
        except Exception:  # a security signal must never break the guarded path
            global _dropped_signals
            _dropped_signals += 1
            log.exception(
                "security signal dropped (type=%s reason=%s tenant=%s)",
                getattr(event_type, "value", event_type),
                reason,
                tenant_id,
            )


def segment_root_hash(events: list[AuditEvent], key: bytes | None = None) -> str:
    """The deterministic rollup root over a contiguous audit-chain segment (D4).

    A single HMAC over the ordered per-row hashes of the segment. Because each
    row hash already chains in every field of that row (SEC-16), a digest over the
    row hashes covers the whole segment: rewriting any row in the range changes
    its hash, which changes the root. Recomputing this over the same seq range on
    read is how the verify endpoint confirms an anchor still matches.

    ``key`` is the audit HMAC key that seals this segment, and callers MUST pass
    ``key_in_force_at(seq_end)`` rather than take the default. This used to have no
    parameter at all and always used the live key, so the FIRST key rotation made every
    pre-rotation anchor un-verifiable: on Classical Visas `/v1/audit/verify` returned
    `chain_intact: true` beside `anchor_intact: false, intact: false` - reporting a broken
    audit over an intact one. The default is retained only so an un-migrated caller keeps the
    old behaviour instead of crashing."""
    mac = hmac.new(key or _HMAC_KEY, b"boltrig-audit-rollup-v1", hashlib.sha256)
    for e in events:
        mac.update((e.hash or "").encode())
        mac.update(b"\x1e")  # record separator so concatenation is unambiguous
    return mac.hexdigest()


class AuditAnchorer:
    """Computes + writes a rollup anchor over the audit-chain segment for a
    tenant/workspace (D4). Ships the local dev-fallback now; the RFC3161/KMS
    signing is a clean seam gated on an external credential."""

    def __init__(self, store: Store) -> None:
        self._store = store

    @staticmethod
    def _external_configured() -> bool:
        return bool(os.environ.get(_TSA_URL_ENV) or os.environ.get(_KMS_KEY_ENV))

    async def anchor(
        self, tenant_id: str, *, workspace_id: str | None = None
    ) -> AuditRollupAnchor | None:
        """Anchor the un-anchored tail of the audit chain for a tenant (optionally
        one workspace). Returns the written anchor, or None when there is nothing
        new to anchor. Idempotent-ish: the next call anchors only rows after the
        previous anchor's ``seq_end``.

        STREAMED (2026-08-16): this used to ``audit_query(limit=1_000_000)`` -
        the newest million rows, whole, into process memory - on every anchor
        cycle for every tenant, workspace filter applied after the load. It now
        pages the un-anchored tail ASC via ``audit_scan`` in bounded batches,
        feeding the rollup MAC row-hash by row-hash, so a long tail costs one
        batch of memory at a time instead of the chain's whole history."""
        _ANCHOR_PAGE = 10_000
        prior = await self._store.latest_audit_anchor(tenant_id, workspace_id=workspace_id)
        floor = prior.seq_end if prior else 0
        cursor = floor
        row_hashes: list[str] = []
        seq_start: int | None = None
        while True:
            page = await self._store.audit_scan(tenant_id, cursor, _ANCHOR_PAGE)
            if not page:
                break
            cursor = page[-1].seq or cursor
            scoped = (
                [e for e in page if e.workspace_id == workspace_id]
                if workspace_id is not None else page
            )
            for e in scoped:
                row_hashes.append(e.hash or "")
            if seq_start is None and scoped:
                seq_start = scoped[0].seq or 0
            if len(page) < _ANCHOR_PAGE:
                break
        if seq_start is None or not row_hashes:
            return None
        seq_end = cursor
        # The key in force at the segment's newest row - the SAME resolution the verify side
        # uses, so write and read agree by construction across a rotation.
        mac = hmac.new(
            key_in_force_at(seq_end) or _HMAC_KEY,
            b"boltrig-audit-rollup-v1",
            hashlib.sha256,
        )
        for row_hash in row_hashes:
            mac.update(row_hash.encode())
            mac.update(b"\x1e")  # record separator so concatenation is unambiguous
        root = mac.hexdigest()
        # LOCAL dev-fallback: flagged, no external call. The RFC3161 TSA token +
        # KMS signature are left NULL - wiring them to a live external service is a
        # Principal dependency (see _TSA_URL_ENV / _KMS_KEY_ENV above).
        anchor = AuditRollupAnchor(
            id=uuid.uuid4().hex,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            seq_start=seq_start,
            seq_end=seq_end,
            rollup_root_hash=root,
            anchored_at=utcnow(),
            is_dev_fallback=not self._external_configured(),
            rfc3161_token=None,
            kms_signature=None,
        )
        await self._store.add_audit_anchor(anchor)
        return anchor

    async def verify_latest(
        self, tenant_id: str, *, workspace_id: str | None = None
    ) -> tuple[bool, AuditRollupAnchor | None]:
        """Recompute the root over the anchored segment and compare to the stored
        anchor. Returns (matches, anchor). No anchor -> (True, None) (nothing to
        contradict). A mismatch means the segment was rewritten after anchoring."""
        anchor = await self._store.latest_audit_anchor(tenant_id, workspace_id=workspace_id)
        if anchor is None:
            return (True, None)
        events = await self._store.audit_query(tenant_id, limit=1_000_000)
        if workspace_id is not None:
            events = [e for e in events if e.workspace_id == workspace_id]
        segment = [e for e in events if anchor.seq_start <= (e.seq or 0) <= anchor.seq_end]
        return (
            segment_root_hash(segment, key=key_in_force_at(anchor.seq_end))
            == anchor.rollup_root_hash,
            anchor,
        )
