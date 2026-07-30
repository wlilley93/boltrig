"""Safe Worker projection of process-local Langfuse delivery attempts."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

_STATES = {"enabled", "disabled"}
_REASONS = {
    "configured",
    "disabled_by_config",
    "missing_keys",
    "package_unavailable",
    "client_initialization_failed",
}
_MAX_COUNTER = 9_007_199_254_740_991


def _counter(value: Any) -> int:
    if type(value) is not int:
        return 0
    return min(max(value, 0), _MAX_COUNTER)


def _timestamp(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text[:64] if text else None


def _unavailable() -> dict[str, Any]:
    return {
        "status": "unavailable",
        "evidence_kind": "process_local_attempt_counters_not_sink_health",
        "process_coverage": "api_spawner_only_not_replica_inventory",
        "sink_state": "unavailable",
        "reason": "status_source_unavailable",
        "attempt_count": 0,
        "success_count": 0,
        "failure_count": 0,
        "last_attempt_at": None,
        "last_success_at": None,
        "last_failure_at": None,
        "delivery_lag": "unavailable",
        "liveness_claimed": False,
        "sensitive_values_redacted": True,
    }


def langfuse_delivery_projection(spawner: Any) -> dict[str, Any]:
    source = getattr(spawner, "observability_status", None)
    if not callable(source):
        return _unavailable()
    try:
        raw = source()
    except Exception:
        raw = None
    if not isinstance(raw, Mapping):
        return _unavailable()
    state = raw.get("sink_state")
    reason = raw.get("reason")
    if state not in _STATES or reason not in _REASONS:
        return _unavailable()
    return {
        "status": "available",
        "evidence_kind": "process_local_attempt_counters_not_sink_health",
        "process_coverage": "api_spawner_only_not_replica_inventory",
        "sink_state": state,
        "reason": reason,
        "attempt_count": _counter(raw.get("attempt_count")),
        "success_count": _counter(raw.get("success_count")),
        "failure_count": _counter(raw.get("failure_count")),
        "last_attempt_at": _timestamp(raw.get("last_attempt_at")),
        "last_success_at": _timestamp(raw.get("last_success_at")),
        "last_failure_at": _timestamp(raw.get("last_failure_at")),
        "delivery_lag": "unavailable",
        "liveness_claimed": False,
        "sensitive_values_redacted": True,
    }


__all__ = ["langfuse_delivery_projection"]
