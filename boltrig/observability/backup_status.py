"""Bounded, content-free scheduled-backup freshness evidence."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import time
from typing import Any


def backup_status(
    marker_path: str | None,
    *,
    interval_seconds: int,
    grace_seconds: int,
    now_epoch: int | None = None,
) -> dict[str, Any]:
    """Read only the sidecar's atomic epoch marker, never backup artifacts."""

    base = {
        "evidence_kind": "shared_success_marker",
        "maximum_age_seconds": interval_seconds + grace_seconds,
        "last_success_at": None,
        "age_seconds": None,
        "off_box_state": "unknown_not_in_marker",
        "encryption_state": "unknown_not_in_marker",
        "restore_readiness": "unavailable_no_restore_drill_receipt",
        "liveness_claimed": False,
    }
    if not marker_path:
        return {"state": "unconfigured", **base}
    if interval_seconds <= 0 or grace_seconds < 0:
        return {"state": "configuration_invalid", **base}
    try:
        path = Path(marker_path)
        if not path.is_file():
            return {"state": "never_observed", **base}
        with path.open("r", encoding="ascii") as marker:
            raw = marker.read(33)
    except OSError:
        return {"state": "unavailable", **base}
    value = raw.strip()
    if len(raw) > 32 or not value.isascii() or not value.isdigit():
        return {"state": "invalid_marker", **base}
    last_success = int(value)
    now = int(time.time()) if now_epoch is None else now_epoch
    age = now - last_success
    if age < 0:
        return {"state": "invalid_marker", **base}
    last_success_at = datetime.fromtimestamp(
        last_success, tz=timezone.utc
    ).isoformat()
    maximum_age = interval_seconds + grace_seconds
    return {
        "state": "fresh" if age <= maximum_age else "stale",
        **base,
        "last_success_at": last_success_at,
        "age_seconds": age,
    }


__all__ = ["backup_status"]
