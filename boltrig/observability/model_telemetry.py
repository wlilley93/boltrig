"""Bounded model/provider telemetry reconstructed from audit rows."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from boltrig.models import ActionType, AuditEvent


_MODEL_ACTIONS = {ActionType.AGENT_SPAWN, ActionType.MODEL_CALL}


@dataclass
class _Bucket:
    provider: str
    model: str
    runtime: str
    profile: str | None
    calls: int = 0
    tokens: int = 0
    cost_micros: int = 0
    latency_total: int = 0
    latency_count: int = 0
    last_seen: str = ""
    statuses: dict[str, int] = field(default_factory=dict)

    def add(self, event: AuditEvent) -> None:
        self.calls += 1
        self.tokens += int(event.tokens_used or 0)
        self.cost_micros += int(event.cost_micros or 0)
        if event.latency_ms is not None:
            self.latency_total += int(event.latency_ms)
            self.latency_count += 1
        self.last_seen = max(self.last_seen, event.ts.isoformat())
        status = str(event.status or "unknown")[:40]
        self.statuses[status] = self.statuses.get(status, 0) + 1

    def row(self) -> dict[str, Any]:
        avg_latency = (
            round(self.latency_total / self.latency_count, 2)
            if self.latency_count
            else None
        )
        out: dict[str, Any] = {
            "provider": self.provider,
            "model": self.model,
            "runtime": self.runtime,
            "calls": self.calls,
            "tokens": self.tokens,
            "cost_micros": self.cost_micros,
            "avg_latency_ms": avg_latency,
            "last_seen": self.last_seen,
            "statuses": dict(sorted(self.statuses.items())),
        }
        if self.profile:
            out["profile"] = self.profile
        return out


def _safe_text(value: Any, default: str) -> str:
    text = str(value or default).strip()
    return (text or default)[:120]


def _route(event: AuditEvent) -> tuple[str, str, str, str | None] | None:
    detail = event.detail if isinstance(event.detail, dict) else {}
    route = detail.get("model_route")
    if not isinstance(route, dict):
        route = {}
    has_signal = bool(route or event.tokens_used or event.cost_micros or event.latency_ms)
    if event.action_type not in _MODEL_ACTIONS or not has_signal:
        return None
    provider = _safe_text(route.get("provider") or detail.get("provider"), "unknown")
    model = _safe_text(route.get("model") or detail.get("model"), "unknown")
    runtime = _safe_text(route.get("runtime") or detail.get("runtime"), "unknown")
    profile = route.get("profile") or detail.get("profile")
    return provider, model, runtime, _safe_text(profile, "") or None


def model_telemetry(events: Iterable[AuditEvent], *, limit: int = 50) -> list[dict[str, Any]]:
    """Aggregate provider/model usage from audit rows without exposing connection data."""
    buckets: dict[tuple[str, str, str, str | None], _Bucket] = {}
    for event in events:
        route = _route(event)
        if route is None:
            continue
        bucket = buckets.setdefault(route, _Bucket(*route))
        bucket.add(event)
    rows = [bucket.row() for bucket in buckets.values()]
    rows.sort(key=lambda row: (row["last_seen"], row["cost_micros"]), reverse=True)
    return rows[: max(0, min(limit, 200))]
