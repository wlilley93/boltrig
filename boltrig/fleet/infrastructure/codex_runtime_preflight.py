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
from .codex_runtime_admission import (
    CodexRuntimeAdmissionError,
    QuarantinedCodexPreflightReceipt,
)
from .skill_discovery import attest_skills_list, force_reload_params

MCP_STATUS_PAGE_LIMIT = 128
DEFAULT_PREFLIGHT_TOTAL_TIMEOUT_SECONDS = 10.0
MAX_PREFLIGHT_TOTAL_TIMEOUT_SECONDS = 30.0
_SKILL_REQUIRED_KEYS = frozenset({"description", "enabled", "name", "path", "scope"})
_SKILL_OPTIONAL_KEYS = frozenset({"dependencies", "interface", "shortDescription"})


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
        if skill.get("dependencies") is not None or skill.get("interface") is not None:
            raise CodexRuntimeAdmissionError("Codex skill dependencies are not quarantined")
        short = skill.get("shortDescription")
        if short is not None and type(short) is not str:
            raise CodexRuntimeAdmissionError("Codex skill metadata is malformed")


def _attest_empty_mcp_inventory(payload: dict[str, object]) -> None:
    root = _exact_keys(payload, frozenset({"data"}), frozenset({"nextCursor"}))
    if _exact_list(root["data"]) or root.get("nextCursor") is not None:
        raise CodexRuntimeAdmissionError("Codex MCP inventory is not empty")


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


async def _attest_no_queued_notifications(client: CodexAppServerClient) -> None:
    try:
        await client.next_notification(timeout=0)
    except TimeoutError:
        return
    raise CodexRuntimeAdmissionError("Codex pre-thread state changed during preflight")


__all__ = [
    "DEFAULT_PREFLIGHT_TOTAL_TIMEOUT_SECONDS",
    "MAX_PREFLIGHT_TOTAL_TIMEOUT_SECONDS",
    "MCP_STATUS_PAGE_LIMIT",
    "QuarantinedCodexPreflightProbe",
]
