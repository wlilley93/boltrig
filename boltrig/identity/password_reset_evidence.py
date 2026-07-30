"""Safe password-reset notifier posture and bounded delivery-attempt evidence."""

from __future__ import annotations

from typing import Any


_AUDIT_TAIL_LIMIT = 500
_SAFE_OUTCOMES = {
    "accepted_by_notifier": "accepted_by_notifier",
    # Legacy rows used ``sent`` before the boundary was named precisely. It
    # meant only that the injected notifier returned success.
    "sent": "accepted_by_notifier",
    # ``not_sent`` also covers ineligible identities where the notifier was
    # deliberately never called, so attributing it to provider failure would
    # overclaim what the audit row proves.
    "not_sent": "not_accepted_by_notifier",
    "unavailable": "notifier_unavailable",
}


async def password_reset_delivery_evidence(
    store: Any,
    tenant_id: str,
    *,
    notifier: Any,
    include_attempt: bool,
) -> dict[str, Any]:
    """Project no recipient, provider, address, exception, or message content.

    A notifier accepting a call is not evidence that a message reached an
    inbox. The audit tail is deliberately bounded and an absent row therefore
    remains ``not_observed_in_bounded_tail`` rather than "never attempted".
    """

    configured = callable(notifier)
    base: dict[str, Any] = {
        "configuration": "configured" if configured else "unavailable",
        "configuration_reason": None if configured else "not_configured",
        "evidence_kind": "bounded_audit_attempt_not_provider_receipt",
        "proves_recipient_delivery": False,
        "target_disclosed": False,
        "audit_tail_limit": _AUDIT_TAIL_LIMIT,
    }
    if not include_attempt:
        return {
            **base,
            "evidence_status": "restricted",
            "last_attempt_at": None,
            "last_outcome": None,
        }

    events = await store.audit_query(tenant_id, limit=_AUDIT_TAIL_LIMIT)
    latest = next(
        (
            event
            for event in reversed(events)
            if event.verb == "auth.password_reset.delivery"
        ),
        None,
    )
    if latest is None:
        return {
            **base,
            "evidence_status": "not_observed_in_bounded_tail",
            "last_attempt_at": None,
            "last_outcome": None,
        }
    raw_outcome = (
        latest.detail.get("outcome")
        if isinstance(latest.detail, dict)
        else None
    )
    return {
        **base,
        "evidence_status": "available",
        "last_attempt_at": latest.ts.isoformat(),
        "last_outcome": _SAFE_OUTCOMES.get(
            str(raw_outcome), "not_accepted_by_notifier"
        ),
    }


__all__ = ["password_reset_delivery_evidence"]
