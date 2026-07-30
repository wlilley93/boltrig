"""Safe, tenant-scoped platform status projection."""

from __future__ import annotations

import inspect
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any

from fastapi import Request

from boltrig.identity.password_reset_evidence import (
    password_reset_delivery_evidence,
)
from boltrig.observability.platform_policy import platform_policy_fields

from ._shared import can_author_route, platform_state

_STATUS_VALUES = {"ok", "degraded", "down", "unknown"}
_SECRET_KEY_PARTS = (
    "auth",
    "base_url",
    "bearer",
    "credential",
    "dsn",
    "key",
    "password",
    "secret",
    "token",
    "url",
)


def _status(value: Any) -> str:
    status = str(value or "unknown").strip().lower()
    return status if status in _STATUS_VALUES else "unknown"


def _safe_value(value: Any) -> Any:
    if isinstance(value, str):
        lowered = value.lower()
        if lowered.startswith(("http://", "https://")):
            return None
        return value[:512]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, Mapping):
        out = {}
        for key, item in value.items():
            name = str(key)
            if any(part in name.lower() for part in _SECRET_KEY_PARTS):
                continue
            safe = _safe_value(item)
            if safe is not None:
                out[name] = safe
        return out
    if isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray)):
        return [_safe_value(item) for item in list(value)[:20]]
    return str(value)[:512]


def _component(item: Mapping[str, Any]) -> dict[str, Any]:
    meta = _safe_value(item.get("metadata") or item.get("detail") or {})
    return {
        "id": str(item.get("id") or item.get("name") or "unknown")[:80],
        "kind": str(item.get("kind") or item.get("type") or "component")[:40],
        "status": _status(item.get("status")),
        "message": str(item.get("message") or "")[:240],
        "updated_at": str(item.get("updated_at") or item.get("ts") or "")[:80],
        "metadata": meta if isinstance(meta, dict) else {},
    }


def _items(raw: Any, *, limit: int) -> list[dict[str, Any]]:
    if isinstance(raw, Mapping):
        raw = [
            {"id": key, **(value if isinstance(value, Mapping) else {"status": value})}
            for key, value in raw.items()
        ]
    if not isinstance(raw, Iterable) or isinstance(raw, (str, bytes, bytearray)):
        return []
    return [_component(item) for item in list(raw)[:limit] if isinstance(item, Mapping)]


async def _read_status_provider(provider: Any, principal: Any) -> dict[str, Any]:
    if provider is None:
        return {}
    source = getattr(provider, "snapshot", provider)
    try:
        raw = source(
            tenant_id=principal.tenant_id,
            workspace_id=principal.active_workspace_id,
        )
    except TypeError:
        try:
            raw = source(principal)
        except TypeError:
            raw = source()
    if inspect.isawaitable(raw):
        raw = await raw
    return dict(raw or {}) if isinstance(raw, Mapping) else {}


def register(app, P, K) -> None:
    @app.get("/v1/platform/status")
    async def platform_status(request: Request, k=K, p=P) -> dict:
        platform = platform_state(request)
        raw = await _read_status_provider(platform.get("status"), p)
        return {
            "generated_at": datetime.now(UTC).isoformat(),
            "tenant_id": p.tenant_id,
            "workspace_id": p.active_workspace_id,
            "components": _items(raw.get("components", []), limit=20),
            "runtimes": _items(raw.get("runtimes", []), limit=50),
            **(
                await platform_policy_fields(
                    k,
                    p.tenant_id,
                    codex_execution=platform.get("codex_execution"),
                    codex_trusted_provider_configured=(
                        platform.get("codex_trusted_provider_configured") is True
                    ),
                    spawner=platform.get("spawner"),
                    identity_policy=platform.get("identity_policy"),
                )
            ),
            "password_reset_delivery": (
                await password_reset_delivery_evidence(
                    k.store,
                    p.tenant_id,
                    notifier=platform.get("password_reset_notifier"),
                    include_attempt=can_author_route(p),
                )
            ),
        }


__all__ = ["register"]
