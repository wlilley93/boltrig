"""Cron parsing and stable identities for workflow scheduling."""

from __future__ import annotations

import hashlib
import json
import os
import socket
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

DEFAULT_INTERVAL_SECONDS = 15.0

_MONTH_NAMES = {
    name: index
    for index, name in enumerate(
        ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"),
        start=1,
    )
}
_DAY_NAMES = {
    name: index
    for index, name in enumerate(
        ("SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT")
    )
}


def _number(token: str, names: dict[str, int]) -> int:
    normalized = token.strip().upper()
    if normalized in names:
        return names[normalized]
    try:
        return int(normalized)
    except ValueError as exc:
        raise ValueError(f"invalid cron value {token!r}") from exc


def _cron_field(
    raw: str,
    minimum: int,
    maximum: int,
    *,
    names: dict[str, int] | None = None,
    sunday_seven: bool = False,
) -> tuple[frozenset[int], bool]:
    names = names or {}
    values: set[int] = set()
    wildcard = raw == "*"
    for part in raw.split(","):
        base, separator, step_raw = part.partition("/")
        if separator:
            try:
                step = int(step_raw)
            except ValueError as exc:
                raise ValueError(f"invalid cron step {step_raw!r}") from exc
            if step <= 0:
                raise ValueError("cron steps must be positive")
        else:
            step = 1
        if base == "*":
            start, end = minimum, maximum
        elif "-" in base:
            start_raw, end_raw = base.split("-", 1)
            start = _number(start_raw, names)
            end = _number(end_raw, names)
            if sunday_seven:
                start = 0 if start == 7 else start
                end = 0 if end == 7 else end
            if start > end:
                raise ValueError("cron ranges must be ascending")
        else:
            value = _number(base, names)
            if sunday_seven and value == 7:
                value = 0
            start = end = value
        if start < minimum or end > maximum:
            raise ValueError(f"cron value outside {minimum}-{maximum}: {part!r}")
        values.update(range(start, end + 1, step))
    if not values:
        raise ValueError("cron field selects no values")
    return frozenset(values), wildcard


@dataclass(frozen=True)
class CronExpression:
    seconds: frozenset[int]
    minutes: frozenset[int]
    hours: frozenset[int]
    days: frozenset[int]
    months: frozenset[int]
    weekdays: frozenset[int]
    day_wildcard: bool
    weekday_wildcard: bool

    @classmethod
    def parse(cls, expression: str) -> "CronExpression":
        fields = (expression or "").split()
        if len(fields) == 5:
            second, minute, hour, day, month, weekday = ("0", *fields)
        elif len(fields) == 6:
            second, minute, hour, day, month, weekday = fields
        else:
            raise ValueError("cron expression must have 5 or 6 fields")
        seconds, _ = _cron_field(second, 0, 59)
        minutes, _ = _cron_field(minute, 0, 59)
        hours, _ = _cron_field(hour, 0, 23)
        days, day_wildcard = _cron_field(day, 1, 31)
        months, _ = _cron_field(month, 1, 12, names=_MONTH_NAMES)
        weekdays, weekday_wildcard = _cron_field(
            weekday, 0, 6, names=_DAY_NAMES, sunday_seven=True
        )
        return cls(
            seconds,
            minutes,
            hours,
            days,
            months,
            weekdays,
            day_wildcard,
            weekday_wildcard,
        )

    def _date_matches(self, candidate: date) -> bool:
        if candidate.month not in self.months:
            return False
        day_match = candidate.day in self.days
        weekday_match = (candidate.weekday() + 1) % 7 in self.weekdays
        if self.day_wildcard and self.weekday_wildcard:
            return True
        if self.day_wildcard:
            return weekday_match
        if self.weekday_wildcard:
            return day_match
        return day_match or weekday_match

    def next_after(self, base: datetime, timezone: str) -> datetime:
        """Return the first real UTC instant after ``base`` matching local cron."""
        if base.tzinfo is None:
            raise ValueError("cron base must be timezone-aware")
        zone = ZoneInfo(timezone)
        base_utc = base.astimezone(UTC)
        local_day = base_utc.astimezone(zone).date()
        for day_offset in range(366 * 5 + 2):
            candidate_day = date.fromordinal(local_day.toordinal() + day_offset)
            if not self._date_matches(candidate_day):
                continue
            candidates: set[datetime] = set()
            for hour in self.hours:
                for minute in self.minutes:
                    for second in self.seconds:
                        wall = datetime.combine(candidate_day, time(hour, minute, second))
                        for fold in (0, 1):
                            local = wall.replace(tzinfo=zone, fold=fold)
                            instant = local.astimezone(UTC)
                            if instant.astimezone(zone).replace(tzinfo=None) == wall:
                                candidates.add(instant)
            for instant in sorted(candidates):
                if instant > base_utc:
                    return instant
        raise ValueError("cron expression has no occurrence within five years")


def next_cron_occurrence(cron: str, timezone: str, after: datetime) -> datetime:
    ZoneInfo(timezone)
    return CronExpression.parse(cron).next_after(after, timezone)


def scheduler_interval_from_env() -> float:
    try:
        return max(
            0.0,
            float(
                os.environ.get(
                    "BOLTRIG_WORKFLOW_SCHEDULER_INTERVAL",
                    DEFAULT_INTERVAL_SECONDS,
                )
            ),
        )
    except (TypeError, ValueError):
        return DEFAULT_INTERVAL_SECONDS


def scheduler_worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def scheduled_run_id(
    tenant_id: str, workflow_id: str, scheduled_for: datetime
) -> str:
    value = f"{tenant_id}\0{workflow_id}\0{scheduled_for.astimezone(UTC).isoformat()}"
    return f"wfs_{hashlib.sha256(value.encode()).hexdigest()}"


def workflow_schedule_digest(schedule: Any) -> str:
    """Bind an occurrence to authority-bearing schedule desired state."""
    body = {
        "tenant_id": schedule.tenant_id,
        "workflow_id": schedule.workflow_id,
        "workspace_id": schedule.workspace_id,
        "cron": schedule.cron,
        "timezone": schedule.timezone,
        "authority_subject": schedule.authority_subject,
        "grant_allow": list(schedule.grant_ceiling.allow),
        "grant_deny": list(schedule.grant_ceiling.deny),
    }
    encoded = json.dumps(
        body,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
