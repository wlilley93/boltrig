"""Bounded, fail-closed ``/readyz`` checks for durable dependencies, governed
control registration, and enabled runtime seams. Responses expose only coarse
reason codes, never deployment secrets or raw probe output."""

from __future__ import annotations

import asyncio
import copy
import inspect
import math
import os
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from boltrig.kernel import Kernel

from .readiness_control import (
    REQUIRED_CONTROL_VERBS as REQUIRED_CONTROL_VERBS,
    control_plane_check,
)

EXPECTED_ALEMBIC_HEAD = "0026_execution_ledger"

_TRUE_VALUES = {"1", "true", "yes", "on", "y", "t"}
_PRODUCTION_NAMES = {"prod", "production", "staging"}
_STACK_TOOL_IDS = frozenset({"herdr", "opencode", "browser-cli"})

PostgresProbe = Callable[[], Awaitable[tuple[bool, tuple[str, ...]]]]
RedisProbe = Callable[[str, float], Awaitable[bool]]
HerdrProbe = Callable[[Mapping[str, str], float], Awaitable[bool]]
FleetReceiptProbe = Callable[[str, str, float, float, bytes], Awaitable[tuple[bool, str]]]


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in _TRUE_VALUES


def _configured(value: str | None) -> bool:
    return bool(str(value or "").strip())


def _production(env: Mapping[str, str]) -> bool:
    if _truthy(env.get("BOLTRIG_PRODUCTION")):
        return True
    return any(
        str(env.get(name) or "").strip().lower() in _PRODUCTION_NAMES
        for name in ("ENV", "BOLTRIG_ENV", "APP_ENV")
    )


def _timeout(env: Mapping[str, str]) -> float:
    try:
        value = float(env.get("BOLTRIG_READINESS_TIMEOUT", "0.75"))
        return max(0.05, min(value, 10.0)) if math.isfinite(value) else 0.75
    except (TypeError, ValueError):
        return 0.75


def _cache_ttl(env: Mapping[str, str]) -> float:
    try:
        value = float(env.get("BOLTRIG_READINESS_CACHE_TTL", "1.0"))
        return max(0.1, min(value, 5.0)) if math.isfinite(value) else 1.0
    except (TypeError, ValueError):
        return 1.0


def _check(
    status: str,
    *,
    required: bool,
    reason: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    value: dict[str, Any] = {"status": status, "required": required}
    if reason:
        value["reason"] = reason
    value.update(extra)
    return value


async def _probe_redis(url: str, timeout_s: float) -> bool:
    """PING the configured Redis using its URL (including TLS/auth/db options)."""
    from redis.asyncio import Redis

    client = Redis.from_url(
        url,
        socket_connect_timeout=timeout_s,
        socket_timeout=timeout_s,
    )
    try:
        return bool(await client.ping())
    finally:
        await client.aclose()


class ReadinessService:
    """Produce one bounded, redacted readiness snapshot."""

    def __init__(
        self,
        kernel: Kernel,
        *,
        tenant_id: str = "default",
        executor: Any = None,
        status_provider: Any = None,
        env: Mapping[str, str] | None = None,
        postgres_probe: PostgresProbe | None = None,
        redis_probe: RedisProbe | None = None,
        herdr_probe: HerdrProbe | None = None,
        fleet_receipt_probe: FleetReceiptProbe | None = None,
    ) -> None:
        self._kernel = kernel
        self._tenant_id = tenant_id
        self._executor = executor
        self._status_provider = status_provider
        self._env = env
        self._postgres_probe = postgres_probe
        self._redis_probe = redis_probe or _probe_redis
        self._herdr_probe = herdr_probe
        self._fleet_receipt_probe = fleet_receipt_probe
        self._cache_lock = asyncio.Lock()
        self._cache: tuple[float, dict[str, Any]] | None = None

    async def check(self) -> dict[str, Any]:
        env = self._env if self._env is not None else os.environ
        cache_ttl = _cache_ttl(env)
        loop = asyncio.get_running_loop()
        cached = self._cache
        if cached is not None and loop.time() - cached[0] < cache_ttl:
            return copy.deepcopy(cached[1])
        # /readyz is deliberately unauthenticated for orchestrators. Coalesce
        # concurrent checks and briefly cache the redacted result so traffic
        # cannot amplify into unbounded Herdr subprocesses or dependency probes.
        async with self._cache_lock:
            cached = self._cache
            if cached is not None and loop.time() - cached[0] < cache_ttl:
                return copy.deepcopy(cached[1])
            report = await self._check_uncached(env)
            self._cache = (loop.time(), report)
            return copy.deepcopy(report)

    async def _check_uncached(self, env: Mapping[str, str]) -> dict[str, Any]:
        timeout_s = _timeout(env)
        production = _production(env)

        postgres, migration = await self._database_checks(env, production, timeout_s)
        redis = await self._redis_check(env, production, timeout_s)
        control = await control_plane_check(self._kernel, self._tenant_id)
        stack_tools, model_gateway = await self._platform_checks(env, timeout_s)
        hatchet = await self._hatchet_check(env, timeout_s)

        checks = {
            "postgres": postgres,
            "redis": redis,
            "migration": migration,
            "control_plane": control,
            "stack_tools": stack_tools,
            "hatchet": hatchet,
            "model_gateway": model_gateway,
        }
        ready = all(not item["required"] or item["status"] == "ok" for item in checks.values())
        return {"status": "ready" if ready else "not_ready", "checks": checks}

    async def _database_checks(
        self, env: Mapping[str, str], production: bool, timeout_s: float
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        configured = _configured(env.get("DATABASE_URL"))
        required = production or configured
        if not required:
            disabled = _check("disabled", required=False, reason="not_configured")
            return disabled, {
                **disabled,
                "expected": EXPECTED_ALEMBIC_HEAD,
            }
        if not configured:
            return (
                _check("failed", required=True, reason="not_configured"),
                _check(
                    "failed",
                    required=True,
                    reason="postgres_unavailable",
                    expected=EXPECTED_ALEMBIC_HEAD,
                ),
            )

        probe = self._postgres_probe or getattr(self._kernel.store, "readiness_snapshot", None)
        if not callable(probe):
            return (
                _check("failed", required=True, reason="wrong_store"),
                _check(
                    "failed",
                    required=True,
                    reason="postgres_unavailable",
                    expected=EXPECTED_ALEMBIC_HEAD,
                ),
            )
        try:
            alive, heads = await asyncio.wait_for(probe(), timeout=timeout_s)
        except Exception:
            return (
                _check("failed", required=True, reason="probe_failed"),
                _check(
                    "failed",
                    required=True,
                    reason="probe_failed",
                    expected=EXPECTED_ALEMBIC_HEAD,
                ),
            )

        postgres = _check(
            "ok" if alive else "failed",
            required=True,
            reason=None if alive else "probe_failed",
        )
        expected = (EXPECTED_ALEMBIC_HEAD,)
        head_ok = tuple(heads) == expected
        migration = _check(
            "ok" if head_ok else "failed",
            required=True,
            reason=None if head_ok else "head_mismatch",
            expected=EXPECTED_ALEMBIC_HEAD,
            current=EXPECTED_ALEMBIC_HEAD if head_ok else "mismatch",
        )
        return postgres, migration

    async def _redis_check(
        self, env: Mapping[str, str], production: bool, timeout_s: float
    ) -> dict[str, Any]:
        url = str(env.get("REDIS_URL") or "").strip()
        required = production or bool(url)
        if not required:
            return _check("disabled", required=False, reason="not_configured")
        if not url:
            return _check("failed", required=True, reason="not_configured")
        try:
            alive = await asyncio.wait_for(self._redis_probe(url, timeout_s), timeout=timeout_s)
        except Exception:
            alive = False
        return _check(
            "ok" if alive else "failed",
            required=True,
            reason=None if alive else "probe_failed",
        )

    async def _platform_checks(
        self, env: Mapping[str, str], timeout_s: float
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        provider = self._status_provider
        if provider is None:
            from boltrig.fleet.stack_tool_status import StackToolStatusProvider

            provider = StackToolStatusProvider(env=env)
        source = getattr(provider, "snapshot", provider)
        try:
            raw = source(tenant_id=self._tenant_id, workspace_id=None)
            if inspect.isawaitable(raw):
                raw = await asyncio.wait_for(raw, timeout=timeout_s)
            components = {
                str(item.get("id")): item
                for item in (raw or {}).get("components", [])
                if isinstance(item, Mapping) and item.get("id")
            }
        except Exception:
            failed = _check("failed", required=True, reason="probe_failed")
            gateway_enabled = self._model_gateway_enabled(env)
            gateway = _check(
                "failed" if gateway_enabled else "disabled",
                required=gateway_enabled,
                reason="probe_failed" if gateway_enabled else "health_check_disabled",
            )
            return failed, gateway

        tool_ok = _STACK_TOOL_IDS <= components.keys() and all(
            components[name].get("status") == "ok" for name in _STACK_TOOL_IDS
        )
        live_health = "not_required"
        stack_reason = None if tool_ok else "posture_failed"
        if tool_ok and (_production(env) or _truthy(env.get("BOLTRIG_REQUIRE_STACK_TOOL_HEALTH"))):
            live_ok, live_reason = await self._stack_tool_live_check(env, timeout_s)
            tool_ok = live_ok
            live_health = "ok" if live_ok else "failed"
            stack_reason = None if live_ok else live_reason
        elif not tool_ok:
            live_health = "not_evaluated"
        stack = _check(
            "ok" if tool_ok else "failed",
            required=True,
            reason=stack_reason,
            expected=len(_STACK_TOOL_IDS),
            registered=len(_STACK_TOOL_IDS & components.keys()),
            live_health=live_health,
        )

        gateway_enabled = self._model_gateway_enabled(env)
        if not gateway_enabled:
            gateway = _check("disabled", required=False, reason="health_check_disabled")
        else:
            component = components.get("bifrost", {})
            metadata = component.get("metadata", {})
            live = metadata.get("live_health") if isinstance(metadata, Mapping) else None
            gateway_ok = component.get("status") == "ok" and live == "ok"
            gateway = _check(
                "ok" if gateway_ok else "failed",
                required=True,
                reason=None if gateway_ok else "probe_failed",
            )
        return stack, gateway

    async def _stack_tool_live_check(
        self, env: Mapping[str, str], timeout_s: float
    ) -> tuple[bool, str | None]:
        """Combine owner-local Herdr proof with the fresh fleet receipt."""
        herdr_probe = self._herdr_probe
        receipt_probe = self._fleet_receipt_probe
        if herdr_probe is None or receipt_probe is None:
            from boltrig.fleet.stack_tool_health import probe_herdr
            from boltrig.fleet.stack_tool_receipts import read_fleet_tool_receipt

            herdr_probe = herdr_probe or probe_herdr
            receipt_probe = receipt_probe or read_fleet_tool_receipt
        try:
            herdr_ok = await asyncio.wait_for(herdr_probe(env, timeout_s), timeout=timeout_s)
        except Exception:
            herdr_ok = False
        if not herdr_ok:
            return False, "herdr_probe_failed"

        redis_url = str(env.get("REDIS_URL") or "").strip()
        if not redis_url:
            return False, "fleet_receipt_not_configured"
        from boltrig.fleet.stack_tool_health import receipt_ttl
        from boltrig.fleet.stack_tool_receipts import receipt_signing_key

        signing_key = receipt_signing_key(env)
        if signing_key is None:
            return False, "fleet_receipt_auth_not_configured"

        try:
            receipt_ok, receipt_reason = await asyncio.wait_for(
                receipt_probe(
                    redis_url,
                    self._tenant_id,
                    timeout_s,
                    receipt_ttl(env),
                    signing_key,
                ),
                timeout=timeout_s,
            )
        except Exception:
            receipt_ok, receipt_reason = False, "unavailable"
        if not receipt_ok:
            safe_reason = (
                receipt_reason
                if receipt_reason
                in {
                    "missing",
                    "malformed",
                    "stale",
                    "future",
                    "degraded",
                    "unauthenticated",
                    "unavailable",
                }
                else "unavailable"
            )
            return False, f"fleet_receipt_{safe_reason}"
        return True, None

    async def _hatchet_check(self, env: Mapping[str, str], timeout_s: float) -> dict[str, Any]:
        enabled = (
            _truthy(env.get("BOLTRIG_HATCHET_HEALTH"))
            or _truthy(env.get("BOLTRIG_REQUIRE_DURABLE"))
            or _configured(env.get("HATCHET_CLIENT_TOKEN"))
        )
        if not enabled:
            return _check("disabled", required=False, reason="health_check_disabled")
        executor = self._executor
        client = getattr(executor, "client", None)
        probe = getattr(client, "aio_get_engine_version", None)
        if not getattr(executor, "durable", False) or not callable(probe):
            return _check("failed", required=True, reason="durable_executor_unavailable")
        try:
            value = probe()
            if inspect.isawaitable(value):
                value = await asyncio.wait_for(value, timeout=timeout_s)
            alive = value is not None
        except Exception:
            alive = False
        return _check(
            "ok" if alive else "failed",
            required=True,
            reason=None if alive else "probe_failed",
        )

    @staticmethod
    def _model_gateway_enabled(env: Mapping[str, str]) -> bool:
        return _truthy(env.get("BOLTRIG_MODEL_GATEWAY_HEALTH")) or _configured(
            env.get("BOLTRIG_MODEL_GATEWAY_HEALTH_URL")
        )
