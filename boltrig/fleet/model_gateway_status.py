"""Safe platform-status snapshot for the optional model gateway."""

from __future__ import annotations

import inspect
import json
import os
from collections.abc import Awaitable, Callable, Mapping
from typing import Any
from urllib.parse import urlsplit

_INTERNAL_HOSTS = {"localhost", "127.0.0.1", "::1", "bifrost", "local-model"}
_TRUE_VALUES = {"1", "true", "yes", "on", "y", "t"}
HealthProbe = Callable[[str, float], Awaitable[tuple[str, Mapping[str, Any]]]]


def _profile_count(raw: str | None) -> int:
    if not raw:
        return 0
    try:
        data = json.loads(raw)
    except ValueError:
        return 0
    if not isinstance(data, dict):
        return 0
    return sum(
        1
        for cfg in data.values()
        if isinstance(cfg, dict) and cfg.get("provider") and cfg.get("model")
    )


def _int_env(env: Mapping[str, str], name: str, default: int) -> int:
    try:
        return max(1, int(env.get(name, str(default))))
    except (TypeError, ValueError):
        return default


def _float_env(env: Mapping[str, str], name: str, default: float) -> float:
    try:
        return max(0.05, float(env.get(name, str(default))))
    except (TypeError, ValueError):
        return default


def _bool_env(env: Mapping[str, str], name: str) -> bool:
    return str(env.get(name) or "").strip().lower() in _TRUE_VALUES


def _internal_host(host: str | None) -> bool:
    if not host:
        return False
    name = host.lower()
    return name in _INTERNAL_HOSTS or "." not in name


def _gateway_posture(base_url: str | None) -> tuple[str, str, dict[str, Any]]:
    if not base_url:
        return "unknown", "not configured; cache/cost seam inert", {
            "configured": False,
            "routing": "direct",
            "live_health": "not_polled",
        }
    split = urlsplit(base_url)
    valid = bool(split.scheme and split.netloc)
    internal = valid and _internal_host(split.hostname)
    v1_base = base_url.rstrip("/").endswith("/v1")
    metadata = {
        "configured": True,
        "routing": "gateway",
        "internal_route": internal,
        "v1_base": v1_base,
        "live_health": "not_polled",
    }
    if valid and internal and v1_base:
        return "ok", "configured for standard-data routing", metadata
    return "degraded", "configured but deployment posture needs review", metadata


def _health_url(
    base_url: str | None, env: Mapping[str, str]
) -> tuple[str | None, str, str | None]:
    explicit = (env.get("BOLTRIG_MODEL_GATEWAY_HEALTH_URL") or "").strip()
    if explicit:
        return explicit, "explicit", None
    path = (env.get("BOLTRIG_MODEL_GATEWAY_HEALTH_PATH") or "/health").strip()
    if not base_url:
        return None, "derived", "not_configured"
    if not path.startswith("/"):
        return None, "derived", "invalid_path"
    root = base_url.rstrip("/")
    if root.endswith("/v1"):
        root = root[:-3]
    return f"{root}{path}", "derived", None


def _safe_health_metrics(raw: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    cache = raw.get("cache") if isinstance(raw.get("cache"), Mapping) else raw
    for source_key, output_key in (
        ("hit_rate", "cache_hit_rate"),
        ("cache_hit_rate", "cache_hit_rate"),
        ("hits", "cache_hits"),
        ("cache_hits", "cache_hits"),
        ("misses", "cache_misses"),
        ("cache_misses", "cache_misses"),
    ):
        value = cache.get(source_key) if isinstance(cache, Mapping) else None
        if isinstance(value, (int, float)):
            out[output_key] = value
    providers = raw.get("providers")
    if isinstance(providers, list):
        out["provider_count"] = min(len(providers), 1000)
    elif isinstance(raw.get("provider_count"), int):
        out["provider_count"] = max(0, min(int(raw["provider_count"]), 1000))
    return out


def _merge_status(static: str, live: str) -> str:
    if static in {"unknown", "down"}:
        return static
    if live == "ok" or live == "not_polled":
        return static
    return "degraded"


async def _probe_health(url: str, timeout_s: float) -> tuple[str, Mapping[str, Any]]:
    import httpx

    async with httpx.AsyncClient(timeout=timeout_s, follow_redirects=False) as client:
        resp = await client.get(url)
    status = "ok" if 200 <= resp.status_code < 300 else "degraded"
    try:
        data = resp.json()
    except ValueError:
        data = {}
    return status, data if isinstance(data, Mapping) else {}


def _items(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, Mapping):
        return [
            {"id": str(key), **(dict(value) if isinstance(value, Mapping) else {"status": value})}
            for key, value in raw.items()
        ]
    if isinstance(raw, list):
        return [dict(item) for item in raw if isinstance(item, Mapping)]
    return []


class ModelGatewayStatusProvider:
    """Merge a bounded Bifrost/model-gateway snapshot into platform status."""

    def __init__(
        self,
        base: Any = None,
        *,
        env: Mapping[str, str] | None = None,
        health_probe: HealthProbe | None = None,
    ) -> None:
        self._base = base
        self._env = env
        self._health_probe = health_probe or _probe_health

    async def snapshot(self, *, tenant_id: str, workspace_id: str | None) -> dict[str, Any]:
        raw = await self._base_snapshot(tenant_id=tenant_id, workspace_id=workspace_id)
        components = _items(raw.get("components", []))
        runtimes = _items(raw.get("runtimes", []))
        env = self._env or os.environ
        status, message, metadata = _gateway_posture(env.get("BOLTRIG_MODEL_GATEWAY_URL"))
        live_health, live_metadata = await self._live_health(env, env.get("BOLTRIG_MODEL_GATEWAY_URL"))
        metadata.update({
            **live_metadata,
            "live_health": live_health,
            "cache_ttl_seconds": _int_env(env, "BOLTRIG_MODEL_GATEWAY_TTL", 900),
            "profile_count": _profile_count(env.get("BOLTRIG_MODEL_PROFILES")),
        })
        status = _merge_status(status, live_health)
        components.append({
            "id": "bifrost",
            "kind": "model_gateway",
            "status": status,
            "message": message,
            "metadata": metadata,
        })
        runtimes.append({
            "id": "model-gateway",
            "kind": "runtime",
            "status": status,
            "message": message,
            "metadata": {
                "provider": "bifrost",
                "cache": "conversation_binding",
                "live_health": live_health,
            },
        })
        return {"components": components, "runtimes": runtimes}

    async def _live_health(
        self, env: Mapping[str, str], base_url: str | None
    ) -> tuple[str, dict[str, Any]]:
        enabled = (
            _bool_env(env, "BOLTRIG_MODEL_GATEWAY_HEALTH")
            or bool(env.get("BOLTRIG_MODEL_GATEWAY_HEALTH_URL"))
        )
        if not enabled:
            return "not_polled", {}
        url, source, error = _health_url(base_url, env)
        meta = {"health_source": source}
        if error or not url:
            return "degraded", {**meta, "health_error": error or "missing_url"}
        split = urlsplit(url)
        if not (split.scheme and split.netloc):
            return "degraded", {**meta, "health_error": "invalid_url"}
        if not _internal_host(split.hostname):
            return "degraded", {**meta, "health_error": "external_host_rejected"}
        try:
            health, raw = await self._health_probe(
                url, _float_env(env, "BOLTRIG_MODEL_GATEWAY_HEALTH_TIMEOUT", 0.75)
            )
        except Exception:
            return "down", {**meta, "health_error": "probe_failed"}
        return health if health in {"ok", "degraded", "down"} else "degraded", {
            **meta,
            **_safe_health_metrics(raw),
        }

    async def _base_snapshot(
        self, *, tenant_id: str, workspace_id: str | None
    ) -> dict[str, Any]:
        if self._base is None:
            return {}
        source = getattr(self._base, "snapshot", self._base)
        try:
            raw = source(tenant_id=tenant_id, workspace_id=workspace_id)
        except TypeError:
            raw = source()
        if inspect.isawaitable(raw):
            raw = await raw
        return dict(raw or {}) if isinstance(raw, Mapping) else {}
