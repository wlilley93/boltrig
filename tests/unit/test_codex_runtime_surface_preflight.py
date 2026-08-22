from __future__ import annotations

import asyncio
import tomllib
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from boltrig.fleet.domain import NativeSubagentLimits
from boltrig.fleet.domain.skill_attestation import (
    SkillAttestationPlan,
    SkillDiscoveryReport,
    attest_skill_discovery,
)
from boltrig.fleet.infrastructure import codex_protocol as wire
from boltrig.fleet.infrastructure.codex_app_server import CodexAppServerClient
from boltrig.fleet.infrastructure.codex_runtime_admission import (
    CodexRuntimeAdmissionError,
    QuarantinedCodexPreflightReceipt,
)
from boltrig.fleet.infrastructure.codex_runtime_config import CodexReasoningEffort
from boltrig.fleet.infrastructure.codex_runtime_surface_preflight import (
    APP_PAGE_LIMIT,
    BoundCodexSurfacePreflightProbe,
)
from boltrig.fleet.infrastructure.codex_trusted_proxy_support import (
    model_policy_digest,
    render_trusted_config,
)

from .codex_app_server_fakes import FakeLineTransport, initialize, sent
from .codex_runtime_fakes import digest

WORKSPACE = "/srv/boltrig/cells/cell-1/workspace"


class _BaseProbe:
    def __init__(self, plan: SkillAttestationPlan) -> None:
        self._receipt = QuarantinedCodexPreflightReceipt(
            attest_skill_discovery(plan, SkillDiscoveryReport(WORKSPACE, ()))
        )

    async def probe(
        self, _client: CodexAppServerClient, _plan: SkillAttestationPlan
    ) -> QuarantinedCodexPreflightReceipt:
        return self._receipt


@pytest.fixture
async def surface_client() -> AsyncIterator[tuple[CodexAppServerClient, FakeLineTransport]]:
    transport = FakeLineTransport()
    client = CodexAppServerClient(transport, request_timeout=1.0)
    await initialize(client, transport)
    yield client, transport
    await client.aclose()


def _composed(tmp_path: Path):
    cell_root = tmp_path / "cell-1"
    codex_home = cell_root / "codex-home"
    return render_trusted_config(
        cell_id="cell-1",
        cell_root=cell_root,
        codex_home=codex_home,
        helper_path=Path("/opt/boltrig/bin/model-auth"),
        helper_sha256=digest("helper"),
        socket_name="@boltrig-mp-0123456789abcdef0123456789abcdef",
        model_id="openai/gpt-5.4",
        policy_digest=model_policy_digest("openai/gpt-5.4", CodexReasoningEffort.HIGH),
        reasoning_effort=CodexReasoningEffort.HIGH,
        proxy_port=43190,
        native_subagents=NativeSubagentLimits(),
    )


def _effective_config(composed) -> dict[str, object]:
    config = tomllib.loads(composed.config_toml)
    config["plugins"] = {}
    config["model_providers"]["boltrig_model_proxy"]["auth"]["cwd"] = (  # type: ignore[index]
        f"{composed.receipt.cell_root}/workspace"
    )
    return {
        "config": config,
        "layers": [
            {
                "name": {
                    "type": "user",
                    "file": f"{composed.receipt.codex_home}/config.toml",
                    "profile": None,
                },
                "version": composed.receipt.config_digest,
                "config": config,
            }
        ],
        "origins": {},
    }


async def _respond(
    transport: FakeLineTransport,
    method: str,
    params: dict[str, object],
    result: dict[str, object],
) -> None:
    request = await sent(transport)
    assert isinstance(request, wire.RequestMessage)
    assert request.method == method
    assert request.params.to_mapping() == params
    await transport.receive({"id": request.request_id, "result": result})


async def _drive(
    transport: FakeLineTransport,
    config: dict[str, object],
) -> None:
    responses = [
        (
            "config/read",
            {"cwd": WORKSPACE, "includeLayers": True},
            config,
        ),
        (
            "app/list",
            {
                "cursor": None,
                "forceRefetch": True,
                "limit": APP_PAGE_LIMIT,
                "threadId": None,
            },
            {"data": [], "nextCursor": None},
        ),
        (
            "plugin/list",
            {"cwds": [WORKSPACE], "marketplaceKinds": ["local"]},
            {
                "featuredPluginIds": [],
                "marketplaceLoadErrors": [],
                "marketplaces": [],
            },
        ),
        (
            "externalAgentConfig/detect",
            {"cwds": [WORKSPACE], "includeHome": True},
            {"items": []},
        ),
    ]
    for method, params, result in responses:
        await _respond(transport, method, params, result)


@pytest.mark.invariant("SEC-159")
async def test_surface_preflight_binds_exact_empty_surfaces_and_tool_ceiling(
    surface_client: tuple[CodexAppServerClient, FakeLineTransport], tmp_path: Path
) -> None:
    client, transport = surface_client
    plan = SkillAttestationPlan(WORKSPACE, (), generation=3)
    composed = _composed(tmp_path)
    probe = BoundCodexSurfacePreflightProbe(
        _BaseProbe(plan), composed.receipt, ("device.file.list",)
    )
    task = asyncio.create_task(probe.probe(client, plan))
    await _drive(transport, _effective_config(composed))

    receipt = await task

    assert receipt.production_complete is False
    assert receipt.production_blockers
    assert receipt.surface_evidence is not None
    assert receipt.surface_evidence.composed_config_digest == composed.receipt.config_digest
    assert receipt.surface_evidence.observed_app_count == 0
    assert receipt.surface_evidence.observed_plugin_count == 0
    assert receipt.surface_evidence.observed_external_agent_count == 0


@pytest.mark.invariant("SEC-159")
async def test_surface_preflight_rejects_config_drift_before_listing_other_surfaces(
    surface_client: tuple[CodexAppServerClient, FakeLineTransport], tmp_path: Path
) -> None:
    client, transport = surface_client
    plan = SkillAttestationPlan(WORKSPACE, (), generation=3)
    composed = _composed(tmp_path)
    payload = _effective_config(composed)
    payload["config"]["sandbox_mode"] = "danger-full-access"  # type: ignore[index]
    probe = BoundCodexSurfacePreflightProbe(_BaseProbe(plan), composed.receipt, ())
    task = asyncio.create_task(probe.probe(client, plan))
    await _respond(
        transport,
        "config/read",
        {"cwd": WORKSPACE, "includeLayers": True},
        payload,
    )

    with pytest.raises(CodexRuntimeAdmissionError, match="surface preflight"):
        await task
    assert transport.sent.empty()


@pytest.mark.invariant("SEC-159")
@pytest.mark.parametrize("surface", ["apps", "plugins", "external_agents"])
async def test_surface_preflight_rejects_every_nonempty_dynamic_inventory(
    surface_client: tuple[CodexAppServerClient, FakeLineTransport],
    tmp_path: Path,
    surface: str,
) -> None:
    client, transport = surface_client
    plan = SkillAttestationPlan(WORKSPACE, (), generation=3)
    composed = _composed(tmp_path)
    task = asyncio.create_task(
        BoundCodexSurfacePreflightProbe(_BaseProbe(plan), composed.receipt, ()).probe(
            client, plan
        )
    )
    await _respond(
        transport,
        "config/read",
        {"cwd": WORKSPACE, "includeLayers": True},
        _effective_config(composed),
    )
    app_payload = {"data": [], "nextCursor": None}
    if surface == "apps":
        app_payload["data"] = [{"id": "unreviewed"}]
    await _respond(
        transport,
        "app/list",
        {
            "cursor": None,
            "forceRefetch": True,
            "limit": APP_PAGE_LIMIT,
            "threadId": None,
        },
        app_payload,
    )
    if surface != "apps":
        plugin_payload = {
            "featuredPluginIds": [],
            "marketplaceLoadErrors": [],
            "marketplaces": [],
        }
        if surface == "plugins":
            plugin_payload["marketplaces"] = [{"name": "unreviewed"}]
        await _respond(
            transport,
            "plugin/list",
            {"cwds": [WORKSPACE], "marketplaceKinds": ["local"]},
            plugin_payload,
        )
    if surface == "external_agents":
        await _respond(
            transport,
            "externalAgentConfig/detect",
            {"cwds": [WORKSPACE], "includeHome": True},
            {"items": [{"name": "unreviewed"}]},
        )

    with pytest.raises(CodexRuntimeAdmissionError, match="surface preflight"):
        await task


def _composed_with_mcp(tmp_path: Path):
    cell_root = tmp_path / "cell-mcp"
    codex_home = cell_root / "codex-home"
    return render_trusted_config(
        cell_id="cell-mcp",
        cell_root=cell_root,
        codex_home=codex_home,
        helper_path=Path("/opt/boltrig/bin/model-auth"),
        helper_sha256=digest("helper"),
        socket_name="@boltrig-mp-0123456789abcdef0123456789abcdef",
        model_id="openai/gpt-5.4",
        policy_digest=model_policy_digest("openai/gpt-5.4", CodexReasoningEffort.HIGH),
        reasoning_effort=CodexReasoningEffort.HIGH,
        proxy_port=43190,
        native_subagents=NativeSubagentLimits(),
        mcp_server_url="http://kernel:8000/v1/mcp",
        mcp_bearer_env_var="BOLTRIG_CODEX_MCP_RUN_TOKEN",
    )


def _normalize_mcp_like_the_binary(payload: dict[str, object]) -> None:
    """Apply codex-cli 0.144.3's effective-view normalization to the fixture.

    The binary reports the written two-key server entry with three defaults
    folded in. The fixture used to replay the WRITTEN shape, which is a config
    the real binary never reports - so the mcp branch of the attestation was
    green while being impossible to satisfy live (found on the first real
    kernel-tools admission, 2026-08-20).
    """

    config = payload["config"]
    for entry in config["mcp_servers"].values():  # type: ignore[union-attr,index]
        entry.setdefault("enabled", True)
        entry.setdefault("environment_id", "local")
        entry.setdefault("tool_timeout_sec", None)


@pytest.mark.invariant("SEC-159")
async def test_surface_preflight_accepts_the_binary_normalized_mcp_entry(
    surface_client: tuple[CodexAppServerClient, FakeLineTransport], tmp_path: Path
) -> None:
    client, transport = surface_client
    plan = SkillAttestationPlan(WORKSPACE, (), generation=3)
    composed = _composed_with_mcp(tmp_path)
    payload = _effective_config(composed)
    _normalize_mcp_like_the_binary(payload)
    probe = BoundCodexSurfacePreflightProbe(
        _BaseProbe(plan), composed.receipt, ("device_file_list",)
    )
    task = asyncio.create_task(probe.probe(client, plan))
    await _drive(transport, payload)

    receipt = await task

    assert receipt.production_complete is False


@pytest.mark.invariant("SEC-159")
async def test_surface_preflight_refuses_an_mcp_entry_with_a_drifted_default(
    surface_client: tuple[CodexAppServerClient, FakeLineTransport], tmp_path: Path
) -> None:
    # The defaults are pinned by VALUE: a binary that flips one (or adds a
    # fourth key) must refuse again, or the tolerance becomes a blind spot.
    client, transport = surface_client
    plan = SkillAttestationPlan(WORKSPACE, (), generation=3)
    composed = _composed_with_mcp(tmp_path)
    payload = _effective_config(composed)
    _normalize_mcp_like_the_binary(payload)
    payload["config"]["mcp_servers"]["boltrig"]["enabled"] = False  # type: ignore[index]
    probe = BoundCodexSurfacePreflightProbe(
        _BaseProbe(plan), composed.receipt, ("device_file_list",)
    )
    task = asyncio.create_task(probe.probe(client, plan))
    await _respond(
        transport,
        "config/read",
        {"cwd": WORKSPACE, "includeLayers": True},
        payload,
    )

    with pytest.raises(CodexRuntimeAdmissionError, match="surface preflight"):
        await task
    assert transport.sent.empty()
