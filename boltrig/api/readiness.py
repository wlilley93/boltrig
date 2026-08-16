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

from boltrig.config.environment import is_truthy
from boltrig.fleet.model_gateway import gateway_posture
from boltrig.kernel import Kernel

from .readiness_control import (
    REQUIRED_CONTROL_VERBS as REQUIRED_CONTROL_VERBS,
    control_plane_check,
)
from .background_readiness import read_background_job_readiness
from .codex_readiness import codex_runtime_check
from .readiness_dependencies import database_checks, password_reset_check

EXPECTED_ALEMBIC_HEAD = "0076_typed_memory_ledger"

_PRODUCTION_NAMES = {"prod", "production", "staging"}
# Browser automation is the only separately shipped stack tool. Codex has its
# own admission check and no retired agent runtime participates in readiness.
_STACK_TOOL_IDS = frozenset({"browser-cli"})


def _required_stack_tool_ids(
    manifest: Any, env: Mapping[str, str]
) -> frozenset[str]:
    """The stack tools THIS tenant's readiness may require.

    Browser CLI is required only where the manifest declares automation, because
    the fleet entrypoint starts
    Chromium on exactly that predicate - a fixed required set would gate /readyz
    on a tool the deployment deliberately no longer runs, which is an outage
    dressed as a health check.

    ``browser_automation_wanted`` answers False for an unreadable manifest, so a
    kernel that cannot see one requires no stack tools. The failure it can cause
    is a browser-using tenant reporting ready
    without its browser, which surfaces loudly at first use, against a whole
    deployment stuck at 503 for a capability nobody asked for.
    """
    if manifest is not None:
        from boltrig.api.doctor_stack_state import needs_browser_cli

        return _STACK_TOOL_IDS if needs_browser_cli(manifest) else frozenset()
    if is_truthy(env.get("BOLTRIG_REQUIRE_STACK_TOOL_HEALTH")):
        return _STACK_TOOL_IDS

    from boltrig.fleet.browser_runtime import browser_automation_wanted

    if browser_automation_wanted():
        return _STACK_TOOL_IDS
    return frozenset()

PostgresProbe = Callable[[], Awaitable[tuple[bool, tuple[str, ...]]]]
RedisProbe = Callable[[str, float], Awaitable[bool]]
FleetReceiptProbe = Callable[[str, str, float, float, bytes], Awaitable[tuple[bool, str]]]
PasswordResetProbe = Callable[[], bool | Awaitable[bool]]


def _configured(value: str | None) -> bool:
    return bool(str(value or "").strip())


def _production(env: Mapping[str, str]) -> bool:
    if is_truthy(env.get("BOLTRIG_PRODUCTION")):
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


def _check(status: str, *, required: bool, reason: str | None = None,
           **extra: Any) -> dict[str, Any]:
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
        manifest: Any = None,
        env: Mapping[str, str] | None = None,
        postgres_probe: PostgresProbe | None = None,
        redis_probe: RedisProbe | None = None,
        fleet_receipt_probe: FleetReceiptProbe | None = None,
        password_reset_notifier: Any = None,
        password_reset_probe: PasswordResetProbe | None = None,
    ) -> None:
        self._kernel = kernel
        self._tenant_id = tenant_id
        self._executor = executor
        self._status_provider = status_provider
        self._manifest = manifest
        self._env = env
        self._postgres_probe = postgres_probe
        self._redis_probe = redis_probe or _probe_redis
        self._fleet_receipt_probe = fleet_receipt_probe
        self._password_reset_notifier = password_reset_notifier
        self._password_reset_probe = password_reset_probe
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
        # cannot amplify into unbounded dependency probes.
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
        codex_runtime = codex_runtime_check(
            env, production, manifest=self._manifest
        )
        password_reset = await self._password_reset_check(env, timeout_s)
        background_jobs = await read_background_job_readiness(
            self._kernel.store, self._tenant_id, timeout_s=timeout_s)

        checks = {
            "postgres": postgres,
            "redis": redis,
            "migration": migration,
            "control_plane": control,
            "stack_tools": stack_tools,
            "hatchet": hatchet,
            "model_gateway": model_gateway,
            "codex_runtime": codex_runtime,
            "password_reset_delivery": password_reset,
            **background_jobs,
        }
        ready = all(not item["required"] or item["status"] == "ok" for item in checks.values())
        return {"status": "ready" if ready else "not_ready", "checks": checks}

    async def _password_reset_check(
        self,
        env: Mapping[str, str],
        timeout_s: float,
    ) -> dict[str, Any]:
        return await password_reset_check(
            self._password_reset_notifier,
            self._password_reset_probe,
            env,
            timeout_s,
        )

    async def _database_checks(
        self, env: Mapping[str, str], production: bool, timeout_s: float
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        return await database_checks(
            self._kernel.store,
            self._postgres_probe,
            env,
            production,
            timeout_s,
            EXPECTED_ALEMBIC_HEAD,
        )

    async def _redis_check(
        self, env: Mapping[str, str], production: bool, timeout_s: float
    ) -> dict[str, Any]:
        url = str(env.get("REDIS_URL") or "").strip()
        required = production or bool(url)
        if not required:
            return _check("disabled", required=False, reason="not_configured")
        if not url:
            return _check("failed", required=True, reason="not_configured")
        if production and not self._kernel.events.shared:
            return _check("failed", required=True, reason="wrong_backend")
        reason = "probe_failed"
        try:
            alive = await asyncio.wait_for(self._redis_probe(url, timeout_s), timeout=timeout_s)
            if alive and self._kernel.events.shared:
                reason = "capability_failed"
                alive = await asyncio.wait_for(self._kernel.events.readiness(), timeout=timeout_s)
        except Exception:
            alive = False
        return _check("ok" if alive else "failed", required=True, reason=None if alive else reason)
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
            posture, posture_reason = gateway_posture(env)
            armed = posture == "enabled"
            gateway = _check(
                "failed" if armed else posture,
                required=armed,
                reason="probe_failed" if armed else posture_reason,
            )
            return failed, gateway

        required_tools = _required_stack_tool_ids(self._manifest, env)
        tool_ok = required_tools <= components.keys() and all(
            components[name].get("status") == "ok" for name in required_tools
        )
        live_health = "not_required"
        stack_reason = None if tool_ok else "posture_failed"
        if required_tools and tool_ok and (
            _production(env) or is_truthy(env.get("BOLTRIG_REQUIRE_STACK_TOOL_HEALTH"))
        ):
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
            expected=len(required_tools),
            registered=len(required_tools & components.keys()),
            live_health=live_health,
        )

        posture, posture_reason = gateway_posture(env)
        if posture != "enabled":
            # "unchecked" rather than "disabled" when a gateway IS configured but no probe is armed:
            # disabled reads as "this stack uses no gateway", which is a different fact and the one
            # that stops an operator looking. `required` is unchanged - see gateway_posture.
            gateway = _check(posture, required=False, reason=posture_reason)
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
        """Verify the fresh, authenticated fleet-owned browser receipt."""
        receipt_probe = self._fleet_receipt_probe
        if receipt_probe is None:
            from boltrig.fleet.stack_tool_receipts import read_fleet_tool_receipt

            receipt_probe = read_fleet_tool_receipt

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
            is_truthy(env.get("BOLTRIG_HATCHET_HEALTH"))
            or is_truthy(env.get("BOLTRIG_REQUIRE_DURABLE"))
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
