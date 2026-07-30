"""Safe desired/observed projection for workflow schedules."""

from __future__ import annotations

from typing import Any


def _timestamp(value: Any | None) -> str | None:
    return value.isoformat() if value is not None else None


def workflow_schedule_state(
    schedule: Any | None,
    *,
    legacy_schedule: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Project explicit desired/observed state without pretending metadata runs."""
    if schedule is None and legacy_schedule is None:
        return {
            "desired": {"status": "inactive"},
            "observed": {
                "status": "inactive",
                "reason": None,
                "next_run_at": None,
                "last_scheduled_for": None,
                "observed_at": None,
            },
        }
    if schedule is None:
        assert legacy_schedule is not None
        return {
            "desired": {
                "status": "active",
                "cron": legacy_schedule.get("cron"),
                "timezone": legacy_schedule.get("timezone", "UTC"),
            },
            "observed": {
                "status": "needs_action",
                "reason": "scheduling_authority_not_bound",
                "next_run_at": None,
                "last_scheduled_for": None,
                "observed_at": None,
            },
        }
    return {
        "desired": {
            "status": "active",
            "cron": schedule.cron,
            "timezone": schedule.timezone,
        },
        "observed": {
            "status": schedule.observed_status,
            "reason": schedule.observed_reason,
            "next_run_at": _timestamp(schedule.next_due_at),
            "last_scheduled_for": _timestamp(schedule.last_scheduled_for),
            "observed_at": _timestamp(schedule.observed_at),
        },
    }
