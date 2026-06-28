"""Inbound webhook receiver helper (US-ADP-05).

External systems push events to a webhook endpoint. Before such a payload may
become a work item it must be (a) authenticated and (b) validated. The ingress
layer calls :func:`verify_and_normalise` with the decoded payload, the request
headers and the configured signing secret; it returns a normalised work-item
candidate or raises.

Authentication is an HMAC-SHA256 signature check (the common GitHub / Stripe
style ``sha256=<hex>`` scheme) performed in constant time. When no secret is
configured the signature step is skipped (running an unauthenticated webhook is
a deliberate deployment choice, recorded by the absence of a secret) but the
payload is still validated. The secret and the raw signature are NEVER logged
(SEC-05).

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

from nankle.models import utcnow

# Signature headers we recognise, in priority order (lower-cased for lookup).
_SIGNATURE_HEADERS = (
    "x-nankle-signature",
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


def expected_signature(secret: str, body: bytes) -> str:
    """The hex HMAC-SHA256 the sender should have produced over ``body``."""
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def _lower_headers(headers: dict[str, Any] | None) -> dict[str, str]:
    return {str(k).lower(): str(v) for k, v in (headers or {}).items()}


def _find_signature(lower_headers: dict[str, str]) -> str | None:
    for name in _SIGNATURE_HEADERS:
        if name in lower_headers:
            return lower_headers[name]
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
) -> dict[str, Any]:
    """Authenticate and validate an inbound webhook, returning a normalised
    work-item candidate (US-ADP-05).

    Raises :class:`WebhookValidationError` for a malformed payload and
    :class:`WebhookAuthError` for a failed signature when a secret is set.
    """
    if not isinstance(payload, dict):
        raise WebhookValidationError("webhook payload must be a JSON object")

    lower = _lower_headers(headers)
    authenticated = False
    if secret:
        provided = _find_signature(lower)
        if not provided:
            raise WebhookAuthError("signed webhook is missing its signature header")
        expected = expected_signature(secret, canonical_body(payload))
        if not hmac.compare_digest(_extract_hex(provided), expected):
            raise WebhookAuthError("webhook signature mismatch")
        authenticated = True

    source = lower.get("x-nankle-source") or lower.get("user-agent") or "webhook"
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
    return {
        "source": str(source),
        "type": str(event_type),
        "external_id": str(external_id) if external_id is not None else None,
        "authenticated": authenticated,
        "received_at": utcnow().isoformat(),
        "payload": payload,
    }
