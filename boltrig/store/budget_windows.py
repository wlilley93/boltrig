"""Exact UTC budget-window identities shared by both stores."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from boltrig.models import Budget, BudgetWindowRef, BudgetWindowUnavailable

_WINDOWS = frozenset({"run", "daily", "monthly"})


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("budget window timestamp must be timezone-aware")
    return value.astimezone(timezone.utc)


def window_ref(
    scope_id: str,
    window: str,
    *,
    run_id: str | None,
    at: datetime,
    reset_generation: int = 0,
) -> BudgetWindowRef:
    """Derive the exact bucket for one policy without storing a raw run id."""
    observed = _utc(at)
    if window not in _WINDOWS:
        raise ValueError("budget window must be run, daily, or monthly")
    if window == "run":
        identity = str(run_id or "").strip()
        if not identity:
            raise BudgetWindowUnavailable(
                f"run-window budget '{scope_id}' requires an exact run id"
            )
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]
        return BudgetWindowRef(
            scope_id, window, f"run:{digest}", observed, None, reset_generation
        )
    if window == "daily":
        start = observed.replace(hour=0, minute=0, second=0, microsecond=0)
        return BudgetWindowRef(
            scope_id,
            window,
            f"day:{start.date().isoformat()}",
            start,
            start + timedelta(days=1),
            reset_generation,
        )
    start = observed.replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return BudgetWindowRef(
        scope_id,
        window,
        f"month:{start.year:04d}-{start.month:02d}",
        start,
        end,
        reset_generation,
    )


def usage_view(
    policy: Budget,
    ref: BudgetWindowRef | None,
    *,
    spent_tokens: int = 0,
    spent_micros: int = 0,
) -> Budget:
    if ref is None:
        return replace(
            policy,
            spent_tokens=0,
            spent_micros=0,
            usage_state="run_context_required",
            window_key=None,
            window_started_at=None,
            window_ends_at=None,
            reset_generation=0,
        )
    return replace(
        policy,
        spent_tokens=max(0, int(spent_tokens)),
        spent_micros=max(0, int(spent_micros)),
        usage_state="current",
        window_key=ref.window_key,
        window_started_at=ref.started_at,
        window_ends_at=ref.ends_at,
        reset_generation=ref.reset_generation,
    )
