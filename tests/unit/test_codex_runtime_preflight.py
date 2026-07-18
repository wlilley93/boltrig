from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from jsonschema import Draft7Validator

from boltrig.fleet.domain.skill_attestation import (
    ExpectedSkill,
    SkillAttestationPlan,
    SkillScope,
)
from boltrig.fleet.infrastructure import codex_protocol as wire
from boltrig.fleet.infrastructure.codex_app_server import CodexAppServerClient
from boltrig.fleet.infrastructure.codex_runtime_admission import (
    CodexRuntimeAdmissionError,
    QuarantinedCodexPreflightReceipt,
)
from boltrig.fleet.infrastructure.codex_runtime_preflight import (
    MCP_STATUS_PAGE_LIMIT,
    QuarantinedCodexPreflightProbe,
)

from .codex_app_server_fakes import (
    ClientFactory,
    FakeLineTransport,
    initialize,
    sent,
)
from .codex_runtime_fakes import digest

WORKSPACE = "/srv/boltrig/cells/cell-1/workspace"
SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "schemas/codex/0.144.3/codex_app_server_protocol.v2.schemas.json"
)


@pytest.fixture
async def runtime_client_factory() -> AsyncIterator[ClientFactory]:
    clients: list[CodexAppServerClient] = []

    def make(**_kwargs: object) -> tuple[CodexAppServerClient, FakeLineTransport]:
        transport = FakeLineTransport()
        client = CodexAppServerClient(transport, request_timeout=0.2)
        clients.append(client)
        return client, transport

    yield make
    await asyncio.gather(*(client.aclose() for client in clients), return_exceptions=True)


def _plan(*skills: ExpectedSkill) -> SkillAttestationPlan:
    return SkillAttestationPlan(WORKSPACE, skills, generation=3)


def _skills(*items: dict[str, object]) -> dict[str, object]:
    return {"data": [{"cwd": WORKSPACE, "errors": [], "skills": list(items)}]}


async def _respond(
    transport: FakeLineTransport,
    method: str,
    expected_params: dict[str, object],
    result: dict[str, object],
) -> None:
    request = await sent(transport)
    assert isinstance(request, wire.RequestMessage)
    assert request.method == method
    assert request.params.to_mapping() == expected_params
    await transport.receive({"id": request.request_id, "result": result})


async def _run_success(
    client_factory: ClientFactory,
) -> tuple[QuarantinedCodexPreflightReceipt, list[tuple[str, dict[str, object]]]]:
    client, transport = client_factory()
    await initialize(client, transport)
    task = asyncio.create_task(QuarantinedCodexPreflightProbe().probe(client, _plan()))
    calls: list[tuple[str, dict[str, object]]] = []
    responses: list[tuple[str, dict[str, object], dict[str, object]]] = [
        (
            "skills/list",
            {"cwds": [WORKSPACE], "forceReload": True},
            _skills(
                {
                    "description": "system skill",
                    "enabled": False,
                    "name": "skill-creator",
                    "path": "/opt/codex/system/skill-creator/SKILL.md",
                    "scope": "system",
                }
            ),
        ),
        (
            "mcpServerStatus/list",
            {"detail": "toolsAndAuthOnly", "limit": MCP_STATUS_PAGE_LIMIT},
            {"data": [], "nextCursor": None},
        ),
        (
            "hooks/list",
            {"cwds": [WORKSPACE]},
            {
                "data": [
                    {
                        "cwd": WORKSPACE,
                        "errors": [],
                        "hooks": [],
                        "warnings": [],
                    }
                ]
            },
        ),
    ]
    for method, params, result in responses:
        calls.append((method, params))
        await _respond(transport, method, params, result)
    return await task, calls


async def test_preflight_force_reloads_skills_then_proves_empty_mcp_and_hooks(
    runtime_client_factory: ClientFactory,
) -> None:
    receipt, calls = await _run_success(runtime_client_factory)

    assert receipt.observed_mcp_server_count == receipt.observed_hook_count == 0
    assert receipt.production_complete is False
    assert receipt.skill_attestation.selected_names == ()
    assert [method for method, _params in calls] == [
        "skills/list",
        "mcpServerStatus/list",
        "hooks/list",
    ]


def test_preflight_request_and_response_shapes_match_checked_01443_schema() -> None:
    bundle = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    definitions = bundle["definitions"]
    fixtures = [
        (
            "SkillsListParams",
            {"cwds": [WORKSPACE], "forceReload": True},
        ),
        ("SkillsListResponse", _skills()),
        (
            "ListMcpServerStatusParams",
            {"detail": "toolsAndAuthOnly", "limit": MCP_STATUS_PAGE_LIMIT},
        ),
        ("ListMcpServerStatusResponse", {"data": [], "nextCursor": None}),
        ("HooksListParams", {"cwds": [WORKSPACE]}),
        (
            "HooksListResponse",
            {
                "data": [
                    {
                        "cwd": WORKSPACE,
                        "errors": [],
                        "hooks": [],
                        "warnings": [],
                    }
                ]
            },
        ),
    ]
    for definition_name, fixture in fixtures:
        schema = {**definitions[definition_name], "definitions": definitions}
        Draft7Validator(schema).validate(fixture)


@pytest.mark.parametrize("variant", ["unselected", "missing"])
async def test_preflight_rejects_unselected_or_missing_enabled_skill(
    runtime_client_factory: ClientFactory,
    variant: str,
) -> None:
    client, transport = runtime_client_factory()
    await initialize(client, transport)
    selected = ExpectedSkill(
        "legal-review",
        "/srv/boltrig/cells/cell-1/codex-home/skills/legal-review/SKILL.md",
        SkillScope.USER,
        digest("directory"),
        digest("manifest"),
    )
    plan = _plan(selected) if variant == "missing" else _plan()
    task = asyncio.create_task(QuarantinedCodexPreflightProbe().probe(client, plan))
    payload = _skills()
    if variant == "unselected":
        payload = _skills(
            {
                "description": "unselected system skill",
                "enabled": True,
                "name": "skill-creator",
                "path": "/opt/codex/system/skill-creator/SKILL.md",
                "scope": "system",
            }
        )
    await _respond(
        transport,
        "skills/list",
        {"cwds": [WORKSPACE], "forceReload": True},
        payload,
    )

    with pytest.raises(CodexRuntimeAdmissionError, match="quarantined preflight"):
        await task


async def test_preflight_sanitizes_list_error_and_stops_before_other_calls(
    runtime_client_factory: ClientFactory,
) -> None:
    client, transport = runtime_client_factory()
    await initialize(client, transport)
    task = asyncio.create_task(QuarantinedCodexPreflightProbe().probe(client, _plan()))
    request = await sent(transport)
    assert isinstance(request, wire.RequestMessage) and request.method == "skills/list"
    await transport.receive(
        {"id": request.request_id, "error": {"code": -32001, "message": "SECRET"}}
    )

    with pytest.raises(CodexRuntimeAdmissionError) as caught:
        await task

    assert "SECRET" not in str(caught.value)
    assert transport.sent.empty()


async def test_cancelling_skills_list_propagates_without_starting_other_calls(
    runtime_client_factory: ClientFactory,
) -> None:
    client, transport = runtime_client_factory()
    await initialize(client, transport)
    task = asyncio.create_task(QuarantinedCodexPreflightProbe().probe(client, _plan()))
    request = await sent(transport)
    assert isinstance(request, wire.RequestMessage) and request.method == "skills/list"

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert transport.sent.empty()


@pytest.mark.parametrize(
    "mcp_payload",
    [
        {"data": [{"name": "hidden"}], "nextCursor": None},
        {"data": [], "nextCursor": "more-hidden-inventory"},
    ],
)
async def test_preflight_rejects_nonempty_or_paginated_mcp_inventory(
    runtime_client_factory: ClientFactory,
    mcp_payload: dict[str, object],
) -> None:
    client, transport = runtime_client_factory()
    await initialize(client, transport)
    task = asyncio.create_task(QuarantinedCodexPreflightProbe().probe(client, _plan()))
    await _respond(
        transport,
        "skills/list",
        {"cwds": [WORKSPACE], "forceReload": True},
        _skills(),
    )
    await _respond(
        transport,
        "mcpServerStatus/list",
        {"detail": "toolsAndAuthOnly", "limit": MCP_STATUS_PAGE_LIMIT},
        mcp_payload,
    )

    with pytest.raises(CodexRuntimeAdmissionError):
        await task


async def test_preflight_rejects_any_hook_or_hook_discovery_diagnostic(
    runtime_client_factory: ClientFactory,
) -> None:
    client, transport = runtime_client_factory()
    await initialize(client, transport)
    task = asyncio.create_task(QuarantinedCodexPreflightProbe().probe(client, _plan()))
    await _respond(
        transport,
        "skills/list",
        {"cwds": [WORKSPACE], "forceReload": True},
        _skills(),
    )
    await _respond(
        transport,
        "mcpServerStatus/list",
        {"detail": "toolsAndAuthOnly", "limit": MCP_STATUS_PAGE_LIMIT},
        {"data": [], "nextCursor": None},
    )
    await _respond(
        transport,
        "hooks/list",
        {"cwds": [WORKSPACE]},
        {
            "data": [
                {
                    "cwd": WORKSPACE,
                    "errors": [{"message": "SECRET"}],
                    "hooks": [],
                    "warnings": [],
                }
            ]
        },
    )

    with pytest.raises(CodexRuntimeAdmissionError) as caught:
        await task
    assert "SECRET" not in str(caught.value)


async def test_preflight_rejects_invalidation_queued_before_thread_start(
    runtime_client_factory: ClientFactory,
) -> None:
    client, transport = runtime_client_factory()
    await initialize(client, transport)
    task = asyncio.create_task(QuarantinedCodexPreflightProbe().probe(client, _plan()))
    await _respond(
        transport,
        "skills/list",
        {"cwds": [WORKSPACE], "forceReload": True},
        _skills(),
    )
    await _respond(
        transport,
        "mcpServerStatus/list",
        {"detail": "toolsAndAuthOnly", "limit": MCP_STATUS_PAGE_LIMIT},
        {"data": [], "nextCursor": None},
    )
    request = await sent(transport)
    assert isinstance(request, wire.RequestMessage) and request.method == "hooks/list"
    await transport.receive({"method": "skills/changed", "params": {}})
    await transport.receive(
        {
            "id": request.request_id,
            "result": {
                "data": [
                    {
                        "cwd": WORKSPACE,
                        "errors": [],
                        "hooks": [],
                        "warnings": [],
                    }
                ]
            },
        }
    )

    with pytest.raises(CodexRuntimeAdmissionError, match="quarantined preflight"):
        await task


async def _drive_with_pre_hook_notification(
    runtime_client_factory: ClientFactory, notification: dict[str, object]
) -> "asyncio.Task[QuarantinedCodexPreflightReceipt]":
    client, transport = runtime_client_factory()
    await initialize(client, transport)
    task = asyncio.create_task(QuarantinedCodexPreflightProbe().probe(client, _plan()))
    await _respond(
        transport, "skills/list", {"cwds": [WORKSPACE], "forceReload": True}, _skills()
    )
    await _respond(
        transport,
        "mcpServerStatus/list",
        {"detail": "toolsAndAuthOnly", "limit": MCP_STATUS_PAGE_LIMIT},
        {"data": [], "nextCursor": None},
    )
    request = await sent(transport)
    assert isinstance(request, wire.RequestMessage) and request.method == "hooks/list"
    await transport.receive(notification)
    await transport.receive(
        {
            "id": request.request_id,
            "result": {
                "data": [{"cwd": WORKSPACE, "errors": [], "hooks": [], "warnings": []}]
            },
        }
    )
    return task


async def test_preflight_drains_a_disabled_remote_control_notification(
    runtime_client_factory: ClientFactory,
) -> None:
    # Real Codex 0.144.3 emits remoteControl/status/changed at startup; when it
    # reports remote control DISABLED (plus benign install/server identity) the
    # attestation drains it and succeeds - it has verified remote control is off.
    task = await _drive_with_pre_hook_notification(
        runtime_client_factory,
        {
            "method": "remoteControl/status/changed",
            "params": {
                "environmentId": None,
                "installationId": "4f71b517-653a-48f9-87a5-9acc8e0ef27a",
                "serverName": "beelink",
                "status": "disabled",
            },
        },
    )
    receipt = await task
    assert receipt.production_complete is False


@pytest.mark.parametrize(
    "params",
    [
        {"status": "enabled"},
        {"installationId": "x", "serverName": "b", "status": "active"},
        {"status": "disabled", "unexpected": "field"},
    ],
    ids=["enabled", "active", "unexpected-key"],
)
async def test_preflight_rejects_active_or_malformed_remote_control(
    runtime_client_factory: ClientFactory, params: dict[str, object]
) -> None:
    # Benign only when remote control is DISABLED with known fields; an enabled/
    # active status or an unexpected field is a security-relevant state change.
    task = await _drive_with_pre_hook_notification(
        runtime_client_factory,
        {"method": "remoteControl/status/changed", "params": params},
    )
    with pytest.raises(CodexRuntimeAdmissionError, match="quarantined preflight"):
        await task


async def test_preflight_rejects_a_non_remote_control_notification(
    runtime_client_factory: ClientFactory,
) -> None:
    task = await _drive_with_pre_hook_notification(
        runtime_client_factory,
        {"method": "skills/changed", "params": {}},
    )
    with pytest.raises(CodexRuntimeAdmissionError, match="quarantined preflight"):
        await task
