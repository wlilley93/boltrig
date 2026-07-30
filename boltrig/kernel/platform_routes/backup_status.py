"""Authenticated backup-freshness projection."""

from __future__ import annotations

import os
from typing import Any

from boltrig.observability.backup_status import backup_status


def _integer(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return -1


def register(app, P, K) -> None:
    @app.get("/v1/backup/status")
    async def get_backup_status(p=P) -> dict[str, Any]:
        return {
            "backup": backup_status(
                os.environ.get("BOLTRIG_BACKUP_HEALTH_FILE"),
                interval_seconds=_integer("BACKUP_INTERVAL", 86_400),
                grace_seconds=_integer("BACKUP_HEALTH_GRACE", 3_600),
            )
        }


__all__ = ["register"]
