"""Incomplete, quarantined 0.144.3 probes run before ``thread/start``."""

from __future__ import annotations

import asyncio
import math
from collections.abc import Mapping
from typing import cast

from boltrig.fleet.domain import CanonicalJSON, JSONValue
from boltrig.fleet.domain.skill_attestation import SkillAttestationPlan

from . import codex_protocol as wire
from .codex_app_server import CodexAppServerClient
from .codex_kernel_tools_phase import codex_mcp_tool_name
from .codex_runtime_admission import (
    CodexRuntimeAdmissionError,
    QuarantinedCodexPreflightReceipt,
)
from .codex_runtime_config_toml import CODEX_MCP_SERVER_NAME
from .skill_discovery import attest_skills_list, force_reload_params

MCP_STATUS_PAGE_LIMIT = 128
DEFAULT_PREFLIGHT_TOTAL_TIMEOUT_SECONDS = 10.0
MAX_PREFLIGHT_TOTAL_TIMEOUT_SECONDS = 30.0
_SKILL_REQUIRED_KEYS = frozenset({"description", "enabled", "name", "path", "scope"})
_SKILL_OPTIONAL_KEYS = frozenset({"dependencies", "interface", "shortDescription"})
_MCP_SERVER_REQUIRED_KEYS = frozenset(
    {"authStatus", "name", "resourceTemplates", "resources", "tools"}
)
_MCP_SERVER_OPTIONAL_KEYS = frozenset({"serverInfo"})
_MCP_TOOL_REQUIRED_KEYS = frozenset({"inputSchema", "name"})
_MCP_TOOL_OPTIONAL_KEYS = frozenset(
    {"_meta", "annotations", "description", "icons", "outputSchema", "title"}
)


class QuarantinedCodexPreflightProbe:
    """Probe skills and empty MCP/hooks without claiming full effective config.

    Provider, tool, app, plugin, external-agent, and complete generated-schema
    state remain explicit production blockers in the returned receipt.
    """

    def __init__(
        self,
        *,
        total_timeout_seconds: float = DEFAULT_PREFLIGHT_TOTAL_TIMEOUT_SECONDS,
    ) -> None:
        if type(total_timeout_seconds) not in {int, float}:
            raise TypeError("preflight timeout must be a finite positive number")
        timeout = float(total_timeout_seconds)
        if not math.isfinite(timeout) or not 0 < timeout <= MAX_PREFLIGHT_TOTAL_TIMEOUT_SECONDS:
            raise ValueError("preflight timeout is outside its bounded range")
        self._total_timeout = timeout

    async def probe(
        self,
        client: CodexAppServerClient,
        plan: SkillAttestationPlan,
    ) -> QuarantinedCodexPreflightReceipt:
        if type(client) is not CodexAppServerClient:
            raise TypeError("client must be an exact CodexAppServerClient")
        if type(plan) is not SkillAttestationPlan:
            raise TypeError("plan must be an exact SkillAttestationPlan")
        try:
            async with asyncio.timeout(self._total_timeout):
                _require_ready(client)
                skill_payload = await _call(client, "skills/list", force_reload_params(plan))
                _validate_skills_shape(skill_payload)
                skill_attestation = await asyncio.to_thread(
                    attest_skills_list,
                    skill_payload,
                    plan,
                )
                mcp_payload = await _call(
                    client,
                    "mcpServerStatus/list",
                    {"detail": "toolsAndAuthOnly", "limit": MCP_STATUS_PAGE_LIMIT},
                )
                _attest_empty_mcp_inventory(mcp_payload)
                hook_payload = await _call(
                    client,
                    "hooks/list",
                    {"cwds": [plan.workspace_path]},
                )
                _attest_empty_hooks(hook_payload, plan.workspace_path)
                await _attest_no_queued_notifications(client)
                _require_ready(client)
        except asyncio.CancelledError:
            raise
        except Exception:
            raise CodexRuntimeAdmissionError("Codex quarantined preflight failed") from None
        return QuarantinedCodexPreflightReceipt(skill_attestation)


async def _call(
    client: CodexAppServerClient,
    method: str,
    params: Mapping[str, object],
) -> dict[str, object]:
    document = CanonicalJSON.from_mapping(cast(Mapping[str, JSONValue], params))
    result = await client._call(method, document)  # noqa: SLF001
    payload = result.payload.to_mapping()
    if type(payload) is not dict:
        raise CodexRuntimeAdmissionError("Codex quarantined response is malformed")
    return cast(dict[str, object], payload)


def _require_ready(client: CodexAppServerClient) -> None:
    if client.state is not wire.ClientState.READY:
        raise CodexRuntimeAdmissionError("Codex client left its initialized state")


def _exact_keys(
    value: object,
    required: frozenset[str],
    optional: frozenset[str] = frozenset(),
) -> dict[str, object]:
    if type(value) is not dict:
        raise CodexRuntimeAdmissionError("Codex quarantined response is malformed")
    result = cast(dict[str, object], value)
    keys = set(result)
    if not required <= keys or not keys <= required | optional:
        raise CodexRuntimeAdmissionError("Codex quarantined response keys are not exact")
    return result


def _exact_list(value: object) -> list[object]:
    if type(value) is not list:
        raise CodexRuntimeAdmissionError("Codex quarantined response is malformed")
    return cast(list[object], value)


def _validate_skills_shape(payload: dict[str, object]) -> None:
    root = _exact_keys(payload, frozenset({"data"}))
    data = _exact_list(root["data"])
    if len(data) != 1:
        raise CodexRuntimeAdmissionError("Codex skills response is not one workspace")
    entry = _exact_keys(data[0], frozenset({"cwd", "errors", "skills"}))
    _exact_list(entry["errors"])
    for value in _exact_list(entry["skills"]):
        skill = _exact_keys(value, _SKILL_REQUIRED_KEYS, _SKILL_OPTIONAL_KEYS)
        if type(skill["description"]) is not str or type(skill["enabled"]) is not bool:
            raise CodexRuntimeAdmissionError("Codex skill metadata is malformed")
        # The quarantine is that no ACTIVE skill carries dependencies (e.g. an MCP
        # server) or an interface. Real Codex 0.144.3 ships its system skills with
        # display interface metadata (and some with declared dependencies), all
        # enabled=false; a disabled skill is inert, so only an ENABLED one with
        # either field is a breach. attest_skills_list independently rejects any
        # enabled skill outside the (empty read-only) plan, and the MCP inventory is
        # separately attested empty, so a disabled skill's metadata is harmless.
        if skill["enabled"] and (
            skill.get("dependencies") is not None or skill.get("interface") is not None
        ):
            raise CodexRuntimeAdmissionError(
                "Codex enabled a skill with unquarantined dependencies or interface"
            )
        short = skill.get("shortDescription")
        if short is not None and type(short) is not str:
            raise CodexRuntimeAdmissionError("Codex skill metadata is malformed")


def _attest_empty_mcp_inventory(payload: dict[str, object]) -> None:
    root = _exact_keys(payload, frozenset({"data"}), frozenset({"nextCursor"}))
    if _exact_list(root["data"]) or root.get("nextCursor") is not None:
        raise CodexRuntimeAdmissionError("Codex MCP inventory is not empty")


def _attest_kernel_tools_mcp_inventory(
    payload: dict[str, object], expected_tools: frozenset[str]
) -> None:
    """The kernel-tools lane's inventory is EXACTLY the kernel's own face.

    One server, named ``boltrig``, bearer-token auth (the run-scoped token the
    config names by env var), no resources, and every advertised tool within
    the admitted wire-name ceiling (mapped through the same
    ``codex_mcp_tool_name`` the ceiling was compiled with). Anything else - a
    second server, a missing one, another auth shape, a tool outside the
    ceiling - fails closed.
    """

    root = _exact_keys(payload, frozenset({"data"}), frozenset({"nextCursor"}))
    data = _exact_list(root["data"])
    if len(data) != 1 or root.get("nextCursor") is not None:
        raise CodexRuntimeAdmissionError("Codex kernel-tools MCP inventory is not exact")
    server = _exact_keys(data[0], _MCP_SERVER_REQUIRED_KEYS, _MCP_SERVER_OPTIONAL_KEYS)
    if server["name"] != CODEX_MCP_SERVER_NAME or server["authStatus"] != "bearerToken":
        raise CodexRuntimeAdmissionError("Codex kernel-tools MCP server is not the kernel face")
    if _exact_list(server["resources"]) or _exact_list(server["resourceTemplates"]):
        raise CodexRuntimeAdmissionError("Codex kernel-tools MCP server advertises resources")
    tools = server["tools"]
    if type(tools) is not dict:
        raise CodexRuntimeAdmissionError("Codex kernel-tools MCP tools are malformed")
    for tool_name, tool in tools.items():
        if type(tool_name) is not str or codex_mcp_tool_name(tool_name) not in expected_tools:
            raise CodexRuntimeAdmissionError("Codex MCP tool is outside the admitted ceiling")
        _exact_keys(tool, _MCP_TOOL_REQUIRED_KEYS, _MCP_TOOL_OPTIONAL_KEYS)


class KernelToolsCodexPreflightProbe:
    """The kernel-tools lane's quarantined probes (skills, hooks, ONE MCP face).

    Identical in shape to :class:`QuarantinedCodexPreflightProbe` except the
    MCP inventory attestation: the lane's one declared server must be present
    and exact. The receipt records ``observed_mcp_server_count=1``;
    ``AdmittedCodexCell`` binds that count to the admission's lane.
    """

    def __init__(
        self,
        expected_tools: tuple[str, ...],
        *,
        total_timeout_seconds: float = DEFAULT_PREFLIGHT_TOTAL_TIMEOUT_SECONDS,
    ) -> None:
        if type(expected_tools) is not tuple or any(
            type(item) is not str for item in expected_tools
        ):
            raise TypeError("expected kernel tools must be an exact tuple of strings")
        self._expected_tools = frozenset(expected_tools)
        if type(total_timeout_seconds) not in {int, float}:
            raise TypeError("preflight timeout must be a finite positive number")
        timeout = float(total_timeout_seconds)
        if not math.isfinite(timeout) or not 0 < timeout <= MAX_PREFLIGHT_TOTAL_TIMEOUT_SECONDS:
            raise ValueError("preflight timeout is outside its bounded range")
        self._total_timeout = timeout

    async def probe(
        self,
        client: CodexAppServerClient,
        plan: SkillAttestationPlan,
    ) -> QuarantinedCodexPreflightReceipt:
        if type(client) is not CodexAppServerClient:
            raise TypeError("client must be an exact CodexAppServerClient")
        if type(plan) is not SkillAttestationPlan:
            raise TypeError("plan must be an exact SkillAttestationPlan")
        try:
            async with asyncio.timeout(self._total_timeout):
                _require_ready(client)
                skill_payload = await _call(client, "skills/list", force_reload_params(plan))
                _validate_skills_shape(skill_payload)
                skill_attestation = await asyncio.to_thread(
                    attest_skills_list,
                    skill_payload,
                    plan,
                )
                mcp_payload = await _call(
                    client,
                    "mcpServerStatus/list",
                    {"detail": "toolsAndAuthOnly", "limit": MCP_STATUS_PAGE_LIMIT},
                )
                _attest_kernel_tools_mcp_inventory(mcp_payload, self._expected_tools)
                hook_payload = await _call(
                    client,
                    "hooks/list",
                    {"cwds": [plan.workspace_path]},
                )
                _attest_empty_hooks(hook_payload, plan.workspace_path)
                await _attest_no_queued_notifications(client)
                _require_ready(client)
        except asyncio.CancelledError:
            raise
        except Exception:
            raise CodexRuntimeAdmissionError("Codex quarantined preflight failed") from None
        return QuarantinedCodexPreflightReceipt(skill_attestation, observed_mcp_server_count=1)


def _attest_empty_hooks(payload: dict[str, object], workspace: str) -> None:
    root = _exact_keys(payload, frozenset({"data"}))
    data = _exact_list(root["data"])
    if len(data) != 1:
        raise CodexRuntimeAdmissionError("Codex hooks inventory is malformed")
    entry = _exact_keys(data[0], frozenset({"cwd", "errors", "hooks", "warnings"}))
    if (
        entry["cwd"] != workspace
        or _exact_list(entry["hooks"])
        or _exact_list(entry["errors"])
        or _exact_list(entry["warnings"])
    ):
        raise CodexRuntimeAdmissionError("Codex hooks inventory is not empty")


# Real Codex 0.144.3 emits a remoteControl/status/changed notification at startup
# reporting whether the App Server can be driven remotely, plus benign install/
# server identity. For a locked-down read-only cell the only acceptable state is
# remote control DISABLED, so draining this one notification is not a relaxation:
# it verifies remote control is off. Any other status, any unexpected field, or any
# other notification method is a security-relevant pre-thread state change, rejected
# fail-closed.
_REMOTE_CONTROL_NOTIFICATION = "remoteControl/status/changed"
_REMOTE_CONTROL_BENIGN_KEYS = frozenset(
    {"environmentId", "installationId", "serverName", "status"}
)


def _is_disabled_remote_control(note: wire.NotificationMessage) -> bool:
    if note.method != _REMOTE_CONTROL_NOTIFICATION:
        return False
    params = note.params.to_mapping()
    return (
        isinstance(params, Mapping)
        and set(params) <= _REMOTE_CONTROL_BENIGN_KEYS
        and params.get("status") == "disabled"
    )


async def _attest_no_queued_notifications(client: CodexAppServerClient) -> None:
    while True:
        try:
            note = await client.next_notification(timeout=0)
        except TimeoutError:
            return
        if not _is_disabled_remote_control(note):
            raise CodexRuntimeAdmissionError(
                "Codex pre-thread state changed during preflight"
            )


__all__ = [
    "DEFAULT_PREFLIGHT_TOTAL_TIMEOUT_SECONDS",
    "KernelToolsCodexPreflightProbe",
    "MAX_PREFLIGHT_TOTAL_TIMEOUT_SECONDS",
    "MCP_STATUS_PAGE_LIMIT",
    "QuarantinedCodexPreflightProbe",
]
