"""Post-initialize, pre-thread probes for locally observable Codex surfaces."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import cast

from boltrig.fleet.domain.skill_attestation import SkillAttestationPlan

from .codex_app_server import CodexAppServerClient
from .codex_runtime_admission import (
    CodexPreflightProbe,
    CodexRuntimeAdmissionError,
    QuarantinedCodexPreflightReceipt,
)
from .codex_runtime_config import CodexRuntimeConfigReceipt
from .codex_runtime_config_toml import (
    CODEX_MODEL_PROVIDER_ID,
    CODEX_RUNTIME_DISABLED_FEATURES,
    CODEX_RUNTIME_PROVIDER_NAME,
    CODEX_RUNTIME_WIRE_API,
)
from .codex_runtime_preflight import _attest_no_queued_notifications, _call, _require_ready
from .codex_runtime_surface_evidence import (
    QuarantinedCodexSurfaceEvidence,
    canonical_surface_digest,
)

SURFACE_PREFLIGHT_TIMEOUT_SECONDS = 10.0
APP_PAGE_LIMIT = 128


class BoundCodexSurfacePreflightProbe:
    """Bind observable surfaces to the exact config and admitted tool ceiling."""

    def __init__(
        self,
        base: CodexPreflightProbe,
        config: CodexRuntimeConfigReceipt,
        effective_tools: tuple[str, ...],
    ) -> None:
        if type(config) is not CodexRuntimeConfigReceipt:
            raise TypeError("config must be an exact CodexRuntimeConfigReceipt")
        if type(effective_tools) is not tuple or any(
            type(item) is not str for item in effective_tools
        ):
            raise TypeError("effective tools must be an exact tuple of strings")
        self._base = base
        self._config = config
        self._effective_tools = tuple(sorted(effective_tools))

    async def probe(
        self,
        client: CodexAppServerClient,
        plan: SkillAttestationPlan,
    ) -> QuarantinedCodexPreflightReceipt:
        try:
            async with asyncio.timeout(SURFACE_PREFLIGHT_TIMEOUT_SECONDS):
                base = await self._base.probe(client, plan)
                _require_ready(client)
                config = await _call(
                    client,
                    "config/read",
                    {"cwd": plan.workspace_path, "includeLayers": True},
                )
                _attest_effective_config(config, self._config)
                apps = await _call(
                    client,
                    "app/list",
                    {
                        "cursor": None,
                        "forceRefetch": True,
                        "limit": APP_PAGE_LIMIT,
                        "threadId": None,
                    },
                )
                _attest_empty_apps(apps)
                plugins = await _call(
                    client,
                    "plugin/list",
                    {"cwds": [plan.workspace_path], "marketplaceKinds": ["local"]},
                )
                _attest_empty_plugins(plugins)
                external = await _call(
                    client,
                    "externalAgentConfig/detect",
                    {"cwds": [plan.workspace_path], "includeHome": True},
                )
                _attest_empty_external_agents(external)
                await _attest_no_queued_notifications(client)
                _require_ready(client)
        except asyncio.CancelledError:
            raise
        except Exception:
            raise CodexRuntimeAdmissionError("Codex quarantined surface preflight failed") from None
        evidence = QuarantinedCodexSurfaceEvidence(
            effective_config_digest=canonical_surface_digest(config),
            composed_config_digest=self._config.config_digest,
            apps_inventory_digest=canonical_surface_digest(apps),
            plugins_inventory_digest=canonical_surface_digest(plugins),
            external_agents_inventory_digest=canonical_surface_digest(external),
            effective_tools_digest=canonical_surface_digest(self._effective_tools),
        )
        return QuarantinedCodexPreflightReceipt(
            base.skill_attestation,
            surface_evidence=evidence,
            observed_mcp_server_count=base.observed_mcp_server_count,
            observed_hook_count=base.observed_hook_count,
            protocol_version=base.protocol_version,
            protocol_bundle_digest=base.protocol_bundle_digest,
            production_blockers=base.production_blockers,
        )


def _mapping(value: object) -> dict[str, object]:
    if type(value) is not dict:
        raise CodexRuntimeAdmissionError("Codex surface response is malformed")
    return cast(dict[str, object], value)


def _list(value: object) -> list[object]:
    if type(value) is not list:
        raise CodexRuntimeAdmissionError("Codex surface response is malformed")
    return cast(list[object], value)


def _attest_effective_config(
    payload: dict[str, object], receipt: CodexRuntimeConfigReceipt
) -> None:
    if set(payload) != {"config", "layers", "origins"}:
        raise CodexRuntimeAdmissionError("Codex effective config response is not exact")
    config = _mapping(payload["config"])
    origins = _mapping(payload["origins"])
    layers = _list(payload["layers"])
    if not layers or any(not _permitted_config_layer(item) for item in layers):
        raise CodexRuntimeAdmissionError("Codex effective config has an unreviewed layer")
    if any(not isinstance(value, Mapping) for value in origins.values()):
        raise CodexRuntimeAdmissionError("Codex effective config origins are malformed")
    expected = {
        "approval_policy": "never",
        "model": receipt.model_id,
        "model_provider": receipt.provider_id,
        "model_reasoning_effort": receipt.reasoning_effort.value,
        "sandbox_mode": "read-only",
        "web_search": "disabled",
    }
    if any(config.get(key) != value for key, value in expected.items()):
        raise CodexRuntimeAdmissionError("Codex effective config differs from its receipt")
    for key in ("compact_prompt", "developer_instructions", "instructions"):
        if config.get(key) is not None:
            raise CodexRuntimeAdmissionError("Codex effective config injected instructions")
    _attest_features(config.get("features"), receipt)
    _attest_provider(config.get("model_providers"), receipt)
    _attest_policy_tables(config, receipt)


def _permitted_config_layer(value: object) -> bool:
    layer = _mapping(value)
    if set(layer) - {"config", "disabledReason", "name", "version"}:
        return False
    if not {"config", "name", "version"} <= set(layer):
        return False
    name = _mapping(layer["name"])
    return name.get("type") in {
        "legacyManagedConfigTomlFromFile",
        "sessionFlags",
        "system",
        "user",
    }


def _attest_features(value: object, receipt: CodexRuntimeConfigReceipt) -> None:
    features = _mapping(value)
    expected = dict(CODEX_RUNTIME_DISABLED_FEATURES)
    expected["multi_agent"] = receipt.native_subagents.max_total > 0
    if any(features.get(name) is not enabled for name, enabled in expected.items()):
        raise CodexRuntimeAdmissionError("Codex enabled an unreviewed feature")
    if features.get("remote_control") not in {None, False}:
        raise CodexRuntimeAdmissionError("Codex remote control is enabled")


def _attest_provider(value: object, receipt: CodexRuntimeConfigReceipt) -> None:
    providers = _mapping(value)
    if set(providers) != {CODEX_MODEL_PROVIDER_ID}:
        raise CodexRuntimeAdmissionError("Codex model-provider inventory is not exact")
    provider = _mapping(providers[CODEX_MODEL_PROVIDER_ID])
    expected = {
        "name": CODEX_RUNTIME_PROVIDER_NAME,
        "base_url": f"http://127.0.0.1:{receipt.proxy_port}/v1",
        "wire_api": CODEX_RUNTIME_WIRE_API,
        "request_max_retries": 0,
        "stream_max_retries": 0,
        "stream_idle_timeout_ms": 300000,
        "supports_websockets": False,
    }
    if any(provider.get(key) != item for key, item in expected.items()):
        raise CodexRuntimeAdmissionError("Codex provider config differs from its receipt")
    auth = _mapping(provider.get("auth"))
    expected_auth = {
        "command": receipt.helper_path,
        "args": ["--cell-id", receipt.cell_id, "--socket", receipt.socket_name],
        "timeout_ms": 1000,
        "refresh_interval_ms": 30000,
        "cwd": f"{receipt.cell_root}/workspace",
    }
    if any(auth.get(key) != item for key, item in expected_auth.items()):
        raise CodexRuntimeAdmissionError("Codex provider auth differs from its receipt")


def _attest_policy_tables(config: dict[str, object], receipt: CodexRuntimeConfigReceipt) -> None:
    history = _mapping(config.get("history"))
    if history.get("persistence") != "none":
        raise CodexRuntimeAdmissionError("Codex history persistence is enabled")
    shell = _mapping(config.get("shell_environment_policy"))
    if shell.get("inherit") != "none" or shell.get("set") != {}:
        raise CodexRuntimeAdmissionError("Codex shell environment is not isolated")
    if config.get("project_doc_max_bytes") != 0:
        raise CodexRuntimeAdmissionError("Codex project instruction discovery is enabled")
    if config.get("project_doc_fallback_filenames") != []:
        raise CodexRuntimeAdmissionError("Codex project instruction fallback is enabled")
    if config.get("project_root_markers") != []:
        raise CodexRuntimeAdmissionError("Codex project root discovery is enabled")
    apps = _mapping(config.get("apps"))
    if set(apps) != {"_default"} or _mapping(apps["_default"]).get("enabled") is not False:
        raise CodexRuntimeAdmissionError("Codex app defaults are not disabled")
    if _mapping(config.get("plugins")):
        raise CodexRuntimeAdmissionError("Codex plugin config is not empty")
    mcp = _mapping(config.get("mcp_servers"))
    if receipt.mcp_server_url is None:
        if mcp:
            raise CodexRuntimeAdmissionError("Codex MCP config is not empty")
    elif mcp != {
        "boltrig": {
            "url": receipt.mcp_server_url,
            "bearer_token_env_var": receipt.mcp_bearer_env_var,
        }
    }:
        raise CodexRuntimeAdmissionError("Codex MCP config differs from its receipt")


def _attest_empty_apps(payload: dict[str, object]) -> None:
    if set(payload) - {"data", "nextCursor"} or _list(payload.get("data")):
        raise CodexRuntimeAdmissionError("Codex app inventory is not empty")
    if payload.get("nextCursor") is not None:
        raise CodexRuntimeAdmissionError("Codex app inventory is paginated")


def _attest_empty_plugins(payload: dict[str, object]) -> None:
    if set(payload) != {"featuredPluginIds", "marketplaceLoadErrors", "marketplaces"}:
        raise CodexRuntimeAdmissionError("Codex plugin inventory is not exact")
    if any(_list(payload[key]) for key in payload):
        raise CodexRuntimeAdmissionError("Codex plugin inventory is not empty")


def _attest_empty_external_agents(payload: dict[str, object]) -> None:
    if set(payload) != {"items"} or _list(payload["items"]):
        raise CodexRuntimeAdmissionError("Codex external-agent inventory is not empty")


__all__ = ["BoundCodexSurfacePreflightProbe"]
