"""Inbound webhook receiver helper (US-ADP-05).

External systems push events to a webhook endpoint. Before such a payload may
become a work item it must be (a) authenticated and (b) validated. The ingress
layer calls :func:`verify_and_normalise` with the decoded payload, the request
headers and the configured signing secret; it returns a normalised work-item
candidate or raises.

Authentication is an HMAC-SHA256 signature check (the Stripe-style
``t=<unix>,v1=<hex>`` scheme, also accepting ``sha256=<hex>`` for the digest)
performed in constant time. When no secret is configured the signature step is
skipped (running an unauthenticated webhook is a deliberate deployment choice,
recorded by the absence of a secret) but the payload is still validated. The
secret and the raw signature are NEVER logged (SEC-05).

Replay defence (M3 / SEC-66). The timestamp is bound INTO the signed bytes:
the HMAC is taken over ``t + "." + canonical_body`` (Stripe's scheme), never the
body alone. This is what stops a captured request from replaying under a
rewritten ``t`` - rewriting the timestamp invalidates the signature. When a
signing secret is configured a timestamp is therefore REQUIRED (a signed request
without one is refused), and the replay-window check (ADP-08 / SEC-63) still
applies on top. A stable delivery id (an explicit id in the payload, else the
signature) lets the ingress dedup replays so a repeat never mints a second work
item; see :func:`is_duplicate_delivery`. A message with NO stable id (id-less
and unsigned) is deduped by CONTENT within a shorter bounded window instead of
not at all; see :func:`content_delivery_id`.

Note: an HMAC is strictly a function of exact bytes. Where the caller can supply
the raw request body it should HMAC that. Here we receive a decoded payload, so
we sign its canonical JSON form (sorted keys, tight separators). Senders that
sign a canonical body interoperate directly; senders that sign their own raw
bytes should be verified at the byte boundary before decoding.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

from boltrig.models import utcnow

# Signature headers we recognise, in priority order (lower-cased for lookup).
_SIGNATURE_HEADERS = (
    "x-boltrig-signature",
    "x-hub-signature-256",
    "x-signature-256",
    "x-signature",
    "stripe-signature",
)


class WebhookAuthError(Exception):
    """A signed webhook failed its HMAC check (US-ADP-05, SEC-05)."""


class WebhookValidationError(ValueError):
    """A webhook payload was structurally invalid and cannot become a work item."""


def canonical_body(payload: dict[str, Any]) -> bytes:
    """Deterministic byte form of a payload for HMAC over a decoded object."""
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def signed_content(timestamp: int | str, body: bytes) -> bytes:
    """The exact bytes the HMAC binds: ``t + "." + canonical_body`` (M3/SEC-66).

    Binding the timestamp into the signed content is what defeats replay under a
    rewritten ``t``: an attacker who captured a valid signature cannot move the
    timestamp forward without the secret, because the timestamp is part of what
    was signed. This mirrors Stripe's ``signed_payload = timestamp.body`` scheme.
    """
    return f"{timestamp}.".encode("utf-8") + body


def expected_signature(secret: str, body: bytes) -> str:
    """The hex HMAC-SHA256 the sender should have produced over ``body``.

    ``body`` is the exact signed bytes. For a webhook that is the timestamp-bound
    content from :func:`signed_content`, not the bare payload (M3/SEC-66)."""
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


# --- Delivery dedup (M3 / SEC-66): durable store-backed record-and-check -----
# A replayed request carries a valid signature (nothing forged), so the signature
# check alone cannot stop a second ingest. We dedup on a stable delivery id keyed
# by (channel_id, delivery_id) within a short window. The AUTHORITY is the store
# (decision 0003 Phase 2): ``store.record_channel_delivery`` is an atomic
# record-and-check, so dedup holds across worker processes and restarts. The
# bounded PROCESS-LOCAL set below survives only as a first-tier cache: a hot
# replay in the same process is refused without a store round-trip, and a local
# marker is armed only after the store recorded the first sighting.
_SEEN_TTL_SECONDS = 600
_seen_deliveries: dict[tuple[str, str], float] = {}

# Content-hash fallback (SEC-175): a message with NO stable delivery id (no
# explicit id in the payload, unsigned so no signature to reuse) is deduped by
# CONTENT within a shorter, bounded window. The synthesised id hashes
# ``channel_id | sender | canonical_body`` and carries a prefix so
# ``is_duplicate_delivery`` applies the shorter TTL to it. The trade-off,
# stated plainly: a LEGIT rapid repeat of the identical message from the same
# sender inside the window is dropped as a replay - the price of deduping a
# delivery we cannot name.
_CONTENT_SEEN_TTL_SECONDS = 300
_CONTENT_ID_PREFIX = "content:"


def content_delivery_id(
    channel_id: str | None, sender: str | None, body: bytes
) -> str:
    """Synthesise a stable delivery id for a message that carries none (SEC-175).

    sha256 over ``channel_id | sender | canonical_body``: a redelivery of the
    identical body from the same sender on the same channel hashes to the same
    id, so the EXISTING store-backed dedup can refuse it. ``body`` is the
    canonical JSON form from :func:`canonical_body`."""
    digest = hashlib.sha256(
        b"|".join(
            (
                (channel_id or "").encode("utf-8"),
                (sender or "").encode("utf-8"),
                body,
            )
        )
    ).hexdigest()
    return f"{_CONTENT_ID_PREFIX}{digest}"


def _fallback_delivery_id(
    payload: dict[str, Any], channel_id: str | None, sender: str | None
) -> str:
    """The content-hash delivery id for a message with no stable handle: the
    given sender, else the payload's own ``sender``/``from`` field."""
    if sender is None:
        raw_sender = payload.get("sender") or payload.get("from")
        sender = str(raw_sender) if raw_sender is not None else None
    return content_delivery_id(channel_id, sender, canonical_body(payload))


def _locally_seen(channel_id: str, delivery_id: str, *, now: float) -> bool:
    """First-tier cache check: True if this process armed a live marker."""
    key = (str(channel_id), str(delivery_id))
    # opportunistic eviction of expired markers (keeps the set bounded)
    for stale in [k for k, exp in _seen_deliveries.items() if exp <= now]:
        del _seen_deliveries[stale]
    return key in _seen_deliveries


async def is_duplicate_delivery(
    store,
    tenant_id: str,
    channel_id: str,
    delivery_id: str,
    *,
    ttl_seconds: int = _SEEN_TTL_SECONDS,
    now: float | None = None,
) -> bool:
    """Record ``(channel_id, delivery_id)`` and return True if it was already
    seen within the TTL window (i.e. this is a replay).

    The durable store row is the record-and-check authority (M3/SEC-66): the
    first sighting returns False and arms both tiers; a repeat within the window
    returns True so the caller can skip creating a second work item - on any
    worker, after any restart. The process-local set is only a cache in front
    of that authority: a local hit short-circuits the store call, a local miss
    defers to the store.

    A content-synthesised id (``content:``-prefixed, see
    :func:`content_delivery_id`) rides the SAME mechanism under the shorter
    ``_CONTENT_SEEN_TTL_SECONDS`` window, whatever ``ttl_seconds`` was passed."""
    current = now if now is not None else utcnow().timestamp()
    if _locally_seen(channel_id, delivery_id, now=current):
        return True
    ttl = (
        _CONTENT_SEEN_TTL_SECONDS
        if str(delivery_id).startswith(_CONTENT_ID_PREFIX)
        else ttl_seconds
    )
    recorded = await store.record_channel_delivery(
        tenant_id, channel_id, delivery_id, ttl_seconds=ttl
    )
    if not recorded:
        return True  # the store already holds a live marker: a replay
    _seen_deliveries[(str(channel_id), str(delivery_id))] = current + ttl
    return False


def _lower_headers(headers: dict[str, Any] | None) -> dict[str, str]:
    return {str(k).lower(): str(v) for k, v in (headers or {}).items()}


def _find_signature(lower_headers: dict[str, str]) -> str | None:
    for name in _SIGNATURE_HEADERS:
        if name in lower_headers:
            return lower_headers[name]
    return None


def _extract_timestamp(raw_signature: str | None, lower_headers: dict[str, str]) -> int | None:
    """Pull a unix timestamp from the Stripe-style ``t=`` signature part or an
    ``x-boltrig-timestamp`` / ``x-timestamp`` header, for the replay window (ADP-08)."""
    if raw_signature and "t=" in raw_signature:
        for part in raw_signature.split(","):
            part = part.strip()
            if part.startswith("t="):
                try:
                    return int(part[2:])
                except ValueError:
                    return None
    ts = lower_headers.get("x-boltrig-timestamp") or lower_headers.get("x-timestamp")
    if ts:
        try:
            return int(float(ts))
        except ValueError:
            return None
    return None


def _extract_hex(raw_signature: str) -> str:
    """Pull the hex digest out of common signature header encodings.

    Handles ``sha256=<hex>`` (GitHub), a bare ``<hex>``, and the Stripe-style
    ``t=...,v1=<hex>`` comma list.
    """
    sig = raw_signature.strip()
    if "," in sig and "v1=" in sig:
        for part in sig.split(","):
            part = part.strip()
            if part.startswith("v1="):
                return part[3:]
    if "=" in sig and "," not in sig:
        return sig.split("=", 1)[1].strip()
    return sig


def verify_and_normalise(
    payload: dict[str, Any],
    headers: dict[str, Any],
    secret: str | None,
    *,
    replay_window_seconds: int = 300,
    now: float | None = None,
    channel_id: str | None = None,
    sender: str | None = None,
) -> dict[str, Any]:
    """Authenticate and validate an inbound webhook, returning a normalised
    work-item candidate (US-ADP-05).

    Raises :class:`WebhookValidationError` for a malformed payload and
    :class:`WebhookAuthError` for a failed signature, a missing signature, or a
    stale (replayed) request outside the timestamp window (ADP-08).

    ``channel_id``/``sender`` scope the content-hash fallback delivery id; the
    signed ingress path never needs it (a signature IS the stable id)."""
    if not isinstance(payload, dict):
        raise WebhookValidationError("webhook payload must be a JSON object")

    lower = _lower_headers(headers)
    authenticated = False
    signature_hex: str | None = None
    if secret:
        provided = _find_signature(lower)
        if not provided:
            raise WebhookAuthError("signed webhook is missing its signature header")
        # Replay protection (M3/SEC-66, ADP-08): the timestamp is bound INTO the
        # signed bytes, so we must have one to reconstruct the signature. Refuse a
        # signed request that omits it - without this, an attacker replays forever.
        ts = _extract_timestamp(provided, lower)
        if ts is None:
            raise WebhookAuthError("signed webhook is missing its timestamp (replay protection)")
        expected = expected_signature(secret, signed_content(ts, canonical_body(payload)))
        signature_hex = _extract_hex(provided)
        # constant-time compare, unchanged (SEC-05): never branch on secret bytes.
        if not hmac.compare_digest(signature_hex, expected):
            raise WebhookAuthError("webhook signature mismatch")
        # The window check still applies on top: a captured request whose bound
        # timestamp is stale is refused even though its signature is genuine.
        if replay_window_seconds > 0:
            current = now if now is not None else utcnow().timestamp()
            if abs(current - ts) > replay_window_seconds:
                raise WebhookAuthError("stale webhook: replay window exceeded")
        authenticated = True

    source = lower.get("x-boltrig-source") or lower.get("user-agent") or "webhook"
    event_type = (
        payload.get("type")
        or payload.get("event")
        or payload.get("action")
        or lower.get("x-github-event")
        or "event"
    )
    external_id = (
        payload.get("id")
        or payload.get("event_id")
        or lower.get("x-request-id")
        or lower.get("x-github-delivery")
    )
    external_id_str = str(external_id) if external_id is not None else None
    # A stable delivery id for dedup (M3/SEC-66): an explicit id the payload carries
    # if present, otherwise the signature itself (a signed replay reuses it).
    delivery = external_id_str or signature_hex
    if delivery is None:
        # No stable delivery id (an id-less, unsigned message): dedup by CONTENT
        # within a bounded window (SEC-175) instead of not at all. The trade-off,
        # stated plainly: a legit rapid repeat inside the window is dropped too.
        delivery = _fallback_delivery_id(payload, channel_id, sender)
    return {
        "source": str(source),
        "type": str(event_type),
        "external_id": external_id_str,
        "delivery_id": delivery,
        "authenticated": authenticated,
        "received_at": utcnow().isoformat(),
        "payload": payload,
    }
