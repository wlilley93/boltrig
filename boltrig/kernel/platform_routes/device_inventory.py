"""Who has the desktop installed, and on how many machines.

``devices`` was already a real install ledger rather than an opt-in power-user
feature: the desktop enrols automatically on sign-in
(apps/worker/src/components/auth/useDesktopAccountBridge.ts). What was missing
was any way to READ it as an administrator - both ``list_devices``
implementations hard-filter to the caller's own ``owner_id``, so the ledger
existed and nobody could ask it a question.

TWO NUMBERS, NOT ONE, AND THE GAP BETWEEN THEM IS THE POINT. Enrolment happens
under the caller's active org, and ``public_key_fingerprint`` is per-keychain,
so one laptop used by a person in two orgs is two rows with one fingerprint.
Reporting seats alone over-counts machines; reporting machines alone cannot
answer "which users". The response therefore carries ``live_installs`` (seats,
the headline), ``distinct_machines``, and ``users_with_desktop``, and where the
first two disagree that is visible rather than reconciled away.

Revoked devices are excluded from all three and counted separately: a revoked
row is a record that something WAS installed, not evidence that it is.

The per-owner rollup is deliberately a rollup. The device rows carry public
keys, session-token hashes and lease key ids, none of which an install census
needs, and a route that returns more than its question requires is how a
reporting endpoint becomes a disclosure.
"""

from __future__ import annotations

from typing import Any

from ._shared import require_author


def _owner_rollup(devices: list[Any]) -> list[dict[str, Any]]:
    owners: dict[str, dict[str, Any]] = {}
    for device in devices:
        row = owners.setdefault(
            device.owner_id,
            {
                "owner_id": device.owner_id,
                "live_installs": 0,
                "revoked_installs": 0,
                "machines": set(),
                "last_seen_at": None,
            },
        )
        if device.revoked_at is not None:
            row["revoked_installs"] += 1
            continue
        row["live_installs"] += 1
        row["machines"].add(device.public_key_fingerprint)
        seen = device.last_seen_at
        if seen is not None and (
            row["last_seen_at"] is None or seen > row["last_seen_at"]
        ):
            row["last_seen_at"] = seen
    return [
        {
            "owner_id": row["owner_id"],
            "live_installs": row["live_installs"],
            "revoked_installs": row["revoked_installs"],
            "distinct_machines": len(row["machines"]),
            "last_seen_at": (
                row["last_seen_at"].isoformat() if row["last_seen_at"] else None
            ),
        }
        for row in sorted(owners.values(), key=lambda item: item["owner_id"])
    ]


def register(app, P, K) -> None:
    @app.get("/v1/admin/devices")
    async def desktop_install_inventory(k=K, p=P) -> dict[str, Any]:
        require_author(p)
        devices = await k.store.list_devices_for_tenant(p.tenant_id)
        live = [device for device in devices if device.revoked_at is None]
        owners = _owner_rollup(devices)
        return {
            "users_with_desktop": len({device.owner_id for device in live}),
            "live_installs": len(live),
            "distinct_machines": len(
                {device.public_key_fingerprint for device in live}
            ),
            "revoked_installs": len(devices) - len(live),
            "owners": owners,
        }


__all__ = ["register"]
