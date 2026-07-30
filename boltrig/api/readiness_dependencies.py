"""Bounded readiness checks for database and password-reset dependencies."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Mapping
from typing import Any

from boltrig.config.environment import is_truthy


def _check(
    status: str, *, required: bool, reason: str | None = None, **extra: Any
) -> dict[str, Any]:
    value: dict[str, Any] = {"status": status, "required": required}
    if reason:
        value["reason"] = reason
    value.update(extra)
    return value


async def password_reset_check(
    notifier: Any,
    probe: Any,
    env: Mapping[str, str],
    timeout_s: float,
) -> dict[str, Any]:
    required = is_truthy(env.get("BOLTRIG_REQUIRE_PASSWORD_RESET_DELIVERY"))
    notifier_configured = callable(notifier)
    if not notifier_configured and probe is None:
        return _check(
            "failed" if required else "disabled",
            required=required,
            reason="not_configured",
            notifier_configured=False,
            provider_delivery_proven=False,
        )
    if not notifier_configured:
        return _check(
            "failed",
            required=required,
            reason="notifier_not_configured",
            notifier_configured=False,
            provider_delivery_proven=False,
        )
    if not callable(probe):
        return _check(
            "failed" if required else "unchecked",
            required=required,
            reason="readiness_probe_not_configured",
            notifier_configured=True,
            provider_delivery_proven=False,
        )

    async def invoke_probe() -> bool:
        if inspect.iscoroutinefunction(probe):
            return await probe()
        result = await asyncio.to_thread(probe)
        if inspect.isawaitable(result):
            return await result
        return result

    try:
        ready = await asyncio.wait_for(invoke_probe(), timeout=timeout_s) is True
    except Exception:
        ready = False
    return _check(
        "ok" if ready else "failed",
        required=required,
        reason=None if ready else "probe_failed",
        notifier_configured=True,
        provider_delivery_proven=False,
    )


async def database_checks(
    store: Any,
    probe: Any,
    env: Mapping[str, str],
    production: bool,
    timeout_s: float,
    expected_head: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    configured = bool(str(env.get("DATABASE_URL") or "").strip())
    required = production or configured
    if not required:
        disabled = _check("disabled", required=False, reason="not_configured")
        return disabled, {**disabled, "expected": expected_head}
    if not configured:
        return (
            _check("failed", required=True, reason="not_configured"),
            _check(
                "failed",
                required=True,
                reason="postgres_unavailable",
                expected=expected_head,
            ),
        )

    selected_probe = probe or getattr(store, "readiness_snapshot", None)
    if not callable(selected_probe):
        return (
            _check("failed", required=True, reason="wrong_store"),
            _check(
                "failed",
                required=True,
                reason="postgres_unavailable",
                expected=expected_head,
            ),
        )
    try:
        alive, heads = await asyncio.wait_for(selected_probe(), timeout=timeout_s)
    except Exception:
        return (
            _check("failed", required=True, reason="probe_failed"),
            _check(
                "failed",
                required=True,
                reason="probe_failed",
                expected=expected_head,
            ),
        )

    postgres = _check(
        "ok" if alive else "failed",
        required=True,
        reason=None if alive else "probe_failed",
    )
    head_ok = tuple(heads) == (expected_head,)
    migration = _check(
        "ok" if head_ok else "failed",
        required=True,
        reason=None if head_ok else "head_mismatch",
        expected=expected_head,
        current=expected_head if head_ok else "mismatch",
    )
    return postgres, migration
