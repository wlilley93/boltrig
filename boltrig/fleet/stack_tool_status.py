"""Safe platform-status snapshot for shipped Herdr/OpenCode/browser tools."""

from __future__ import annotations

import inspect
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from boltrig.api.doctor_stack_state import (
    _is_personal_tool_state,
    _references_user_home,
)

_BROWSER_CLOUD_STACK = {"stack", "stack-owned", "stack_owned"}
_BROWSER_CLOUD_DISABLED = {"", "0", "false", "no", "off", "disabled", "none"}
_BROWSER_CLOUD_KEYS = (
    "BOLTRIG_BROWSER_CLOUD_API_KEY",
    "BOLTRIG_BROWSER_CLOUD_PROFILE_ID",
    "BOLTRIG_BROWSER_CLOUD_PROJECT_ID",
    "BOLTRIG_BROWSER_CLOUD_TEAM_ID",
)


@dataclass(frozen=True)
class _Tool:
    id: str
    kind: str
    home_env: str
    default_home: str
    bin_env: str
    default_bin: str
    container: str


_TOOLS = (
    _Tool(
        "herdr",
        "operator_cockpit",
        "BOLTRIG_HERDR_HOME",
        "/var/lib/boltrig/herdr",
        "HERDR_BIN",
        "herdr",
        "kernel",
    ),
    _Tool(
        "opencode",
        "coding_agent",
        "BOLTRIG_OPENCODE_HOME",
        "/var/lib/boltrig/opencode",
        "BOLTRIG_OPENCODE_BIN",
        "opencode",
        "fleet-worker",
    ),
    _Tool(
        "browser-cli",
        "browser_automation",
        "BOLTRIG_BROWSER_CLI_HOME",
        "/var/lib/boltrig/browser-cli",
        "BOLTRIG_BROWSER_CLI_BIN",
        "browser-use",
        "fleet-worker",
    ),
)


def _items(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, Mapping):
        return [
            {"id": str(key), **(dict(value) if isinstance(value, Mapping) else {"status": value})}
            for key, value in raw.items()
        ]
    if isinstance(raw, list):
        return [dict(item) for item in raw if isinstance(item, Mapping)]
    return []


def _safe_state_root(raw: str | None, tool: _Tool) -> tuple[bool, str]:
    value = (raw or tool.default_home).strip()
    if _references_user_home(value) or _is_personal_tool_state(value, tool.id):
        return False, "personal_state_rejected"
    try:
        path = Path(value).expanduser()
    except RuntimeError:
        return False, "invalid_state_root"
    if not path.is_absolute():
        return False, "relative_state_rejected"
    return True, "env" if raw else "compose_default"


def _safe_binary(raw: str | None, tool: _Tool) -> tuple[bool, str]:
    value = (raw or tool.default_bin).strip()
    if not value:
        return False, "empty_binary"
    if _references_user_home(value) or _is_personal_tool_state(value, tool.id):
        return False, "personal_binary_rejected"
    if "/" in value or "\\" in value:
        try:
            if not Path(value).expanduser().is_absolute():
                return False, "relative_binary_rejected"
        except RuntimeError:
            return False, "invalid_binary"
    return True, "env" if raw else "image_default"


def _allowed_domain_count(env: Mapping[str, str]) -> int:
    raw = env.get("BOLTRIG_BROWSER_ALLOWED_DOMAINS") or ""
    return len([item for item in (part.strip() for part in raw.split(",")) if item])


def _browser_cloud_policy(env: Mapping[str, str]) -> tuple[str, bool]:
    raw = (env.get("BOLTRIG_BROWSER_CLOUD_POLICY") or "disabled").strip().lower()
    configured = any(bool((env.get(key) or "").strip()) for key in _BROWSER_CLOUD_KEYS)
    if raw in _BROWSER_CLOUD_DISABLED:
        return "disabled", configured
    if raw in _BROWSER_CLOUD_STACK:
        return "stack_owned", configured
    return "rejected", configured


def _tool_component(tool: _Tool, env: Mapping[str, str]) -> dict[str, Any]:
    state_ok, state_source = _safe_state_root(env.get(tool.home_env), tool)
    binary_ok, binary_source = _safe_binary(env.get(tool.bin_env), tool)
    status = "ok" if state_ok and binary_ok else "degraded"
    issues = [
        label
        for ok, label in (
            (state_ok, state_source),
            (binary_ok, binary_source),
        )
        if not ok
    ]
    metadata: dict[str, Any] = {
        "install_mode": "first_party_image",
        "runtime_container": tool.container,
        "state_root_configured": bool(env.get(tool.home_env)),
        "state_root_stack_owned": state_ok,
        "state_source": state_source,
        "binary_configured": bool(env.get(tool.bin_env)),
        "binary_stack_owned": binary_ok,
        "binary_source": binary_source,
        "profile_state": "stack_owned" if state_ok else "rejected",
        "live_health": "not_polled",
    }
    if tool.id == "browser-cli":
        cloud_policy, cloud_configured = _browser_cloud_policy(env)
        metadata["allowed_domain_count"] = _allowed_domain_count(env)
        metadata["cloud_profile_policy"] = cloud_policy
        metadata["cloud_profile_configured"] = cloud_configured
    return {
        "id": tool.id,
        "kind": tool.kind,
        "status": status,
        "message": "stack-owned image tool" if status == "ok" else "; ".join(issues),
        "metadata": metadata,
    }


class StackToolStatusProvider:
    """Merge Herdr/OpenCode/Browser CLI stack posture into platform status."""

    def __init__(
        self,
        base: Any = None,
        *,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self._base = base
        self._env = env

    async def snapshot(self, *, tenant_id: str, workspace_id: str | None) -> dict[str, Any]:
        raw = await self._base_snapshot(tenant_id=tenant_id, workspace_id=workspace_id)
        env = self._env or os.environ
        components = _items(raw.get("components", []))
        runtimes = _items(raw.get("runtimes", []))
        for tool in _TOOLS:
            component = _tool_component(tool, env)
            components.append(component)
            runtimes.append({
                "id": f"{tool.id}-cli",
                "kind": "runtime",
                "status": component["status"],
                "message": component["message"],
                "metadata": {
                    "component": tool.id,
                    "install_mode": "first_party_image",
                    "runtime_container": tool.container,
                    "profile_state": component["metadata"]["profile_state"],
                    "live_health": "not_polled",
                },
            })
        return {"components": components, "runtimes": runtimes}

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
