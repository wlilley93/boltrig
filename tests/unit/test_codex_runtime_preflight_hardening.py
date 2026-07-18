from __future__ import annotations

import asyncio
import math
import threading
from collections.abc import AsyncIterator, Mapping, Sequence

import pytest

from boltrig.fleet.domain.skill_attestation import (
    SkillAttestation,
    SkillAttestationPlan,
)
from boltrig.fleet.infrastructure import codex_protocol as wire
from boltrig.fleet.infrastructure import codex_runtime_preflight as preflight_module
from boltrig.fleet.infrastructure.codex_app_server import CodexAppServerClient
from boltrig.fleet.infrastructure.codex_runtime_admission import (
    CodexRuntimeAdmissionError,
)
from boltrig.fleet.infrastructure.codex_runtime_preflight import (
    MAX_PREFLIGHT_TOTAL_TIMEOUT_SECONDS,
    MCP_STATUS_PAGE_LIMIT,
    QuarantinedCodexPreflightProbe,
)
from boltrig.fleet.infrastructure.skill_discovery import attest_skills_list

from .codex_app_server_fakes import (
    ClientFactory,
    FakeLineTransport,
    initialize,
    sent,
)

WORKSPACE = "/srv/boltrig/cells/cell-1/workspace"
_SKILLS_PARAMS: dict[str, object] = {
    "cwds": [WORKSPACE],
    "forceReload": True,
}
_MCP_PARAMS: dict[str, object] = {
    "detail": "toolsAndAuthOnly",
    "limit": MCP_STATUS_PAGE_LIMIT,
}
_HOOKS_PARAMS: dict[str, object] = {"cwds": [WORKSPACE]}

Response = tuple[str, dict[str, object], dict[str, object]]


@pytest.fixture
async def hardening_client_factory() -> AsyncIterator[ClientFactory]:
    clients: list[CodexAppServerClient] = []

    def make(**_kwargs: object) -> tuple[CodexAppServerClient, FakeLineTransport]:
        transport = FakeLineTransport()
        client = CodexAppServerClient(transport, request_timeout=0.2)
        clients.append(client)
        return client, transport

    yield make
    await asyncio.gather(*(client.aclose() for client in clients), return_exceptions=True)


def _plan() -> SkillAttestationPlan:
    return SkillAttestationPlan(WORKSPACE, (), generation=3)


def _skills_payload(
    *,
    root_extra: Mapping[str, object] | None = None,
    entry_extra: Mapping[str, object] | None = None,
    skill_extra: Mapping[str, object] | None = None,
) -> dict[str, object]:
    skill: dict[str, object] = {
        "description": "disabled system skill",
        "enabled": False,
        "name": "skill-creator",
        "path": "/opt/codex/system/skill-creator/SKILL.md",
        "scope": "system",
    }
    if skill_extra is not None:
        skill.update(skill_extra)
    entry: dict[str, object] = {
        "cwd": WORKSPACE,
        "errors": [],
        "skills": [skill],
    }
    if entry_extra is not None:
        entry.update(entry_extra)
    root: dict[str, object] = {"data": [entry]}
    if root_extra is not None:
        root.update(root_extra)
    return root


def _empty_mcp_payload() -> dict[str, object]:
    return {"data": [], "nextCursor": None}


def _hooks_payload(
    *,
    root_extra: Mapping[str, object] | None = None,
    entry_extra: Mapping[str, object] | None = None,
) -> dict[str, object]:
    entry: dict[str, object] = {
        "cwd": WORKSPACE,
        "errors": [],
        "hooks": [],
        "warnings": [],
    }
    if entry_extra is not None:
        entry.update(entry_extra)
    root: dict[str, object] = {"data": [entry]}
    if root_extra is not None:
        root.update(root_extra)
    return root


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


async def _assert_rejected(
    client_factory: ClientFactory,
    responses: Sequence[Response],
) -> None:
    client, transport = client_factory()
    await initialize(client, transport)
    task = asyncio.create_task(QuarantinedCodexPreflightProbe().probe(client, _plan()))
    for method, params, result in responses:
        await _respond(transport, method, params, result)

    with pytest.raises(CodexRuntimeAdmissionError) as caught:
        await task

    assert str(caught.value) == "Codex quarantined preflight failed"
    assert transport.sent.empty()


@pytest.mark.parametrize(
    "payload",
    [
        _skills_payload(
            root_extra={"effectiveConfig": {"approvalPolicy": "full-auto"}}
        ),
        _skills_payload(entry_extra={"mcpServers": [{"name": "SECRET"}]}),
        _skills_payload(skill_extra={"allowedTools": ["shell.exec"]}),
    ],
    ids=["root", "workspace-entry", "skill-item"],
)
async def test_skills_reject_unexpected_security_relevant_fields_at_every_level(
    hardening_client_factory: ClientFactory,
    payload: dict[str, object],
) -> None:
    await _assert_rejected(
        hardening_client_factory,
        [("skills/list", _SKILLS_PARAMS, payload)],
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("dependencies", {"mcpServers": ["SECRET"]}),
        ("interface", {"allowedTools": ["shell.exec"]}),
    ],
)
async def test_skills_reject_enabled_skill_with_dependencies_or_interface(
    hardening_client_factory: ClientFactory,
    field: str,
    value: object,
) -> None:
    # The quarantine breach is an ACTIVE skill carrying dependencies (e.g. an MCP
    # server) or an interface, so the offending skill must be enabled.
    await _assert_rejected(
        hardening_client_factory,
        [
            (
                "skills/list",
                _SKILLS_PARAMS,
                _skills_payload(skill_extra={"enabled": True, field: value}),
            )
        ],
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("dependencies", {"tools": [{"type": "mcp", "value": "openaiDeveloperDocs"}]}),
        ("interface", {"displayName": "Image Gen", "brandColor": None}),
    ],
)
def test_disabled_skill_may_carry_dependencies_and_interface(
    field: str, value: object
) -> None:
    # Real Codex 0.144.3 ships its system skills disabled but with display
    # interface metadata (and some with declared dependencies). A disabled skill is
    # inert, so the shape validation must accept it; only an enabled one is a breach.
    disabled = _skills_payload(skill_extra={"enabled": False, field: value})
    preflight_module._validate_skills_shape(disabled)  # does not raise

    enabled = _skills_payload(skill_extra={"enabled": True, field: value})
    with pytest.raises(CodexRuntimeAdmissionError):
        preflight_module._validate_skills_shape(enabled)


async def test_mcp_rejects_unexpected_security_relevant_root_field(
    hardening_client_factory: ClientFactory,
) -> None:
    await _assert_rejected(
        hardening_client_factory,
        [
            ("skills/list", _SKILLS_PARAMS, _skills_payload()),
            (
                "mcpServerStatus/list",
                _MCP_PARAMS,
                {
                    "data": [],
                    "nextCursor": None,
                    "effectiveServers": [{"name": "SECRET"}],
                },
            ),
        ],
    )


@pytest.mark.parametrize(
    "payload",
    [
        _hooks_payload(root_extra={"effectiveHooks": ["SECRET"]}),
        _hooks_payload(entry_extra={"inheritedHooks": ["SECRET"]}),
    ],
    ids=["root", "workspace-entry"],
)
async def test_hooks_reject_unexpected_security_relevant_fields_at_every_level(
    hardening_client_factory: ClientFactory,
    payload: dict[str, object],
) -> None:
    await _assert_rejected(
        hardening_client_factory,
        [
            ("skills/list", _SKILLS_PARAMS, _skills_payload()),
            ("mcpServerStatus/list", _MCP_PARAMS, _empty_mcp_payload()),
            ("hooks/list", _HOOKS_PARAMS, payload),
        ],
    )


@pytest.mark.parametrize("value", [None, "10", True, False], ids=repr)
def test_preflight_timeout_rejects_non_numeric_exact_types(value: object) -> None:
    with pytest.raises(TypeError, match="finite positive number"):
        QuarantinedCodexPreflightProbe(
            total_timeout_seconds=value,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    "value",
    [
        0.0,
        -1.0,
        MAX_PREFLIGHT_TOTAL_TIMEOUT_SECONDS + 0.001,
        math.inf,
        -math.inf,
        math.nan,
    ],
    ids=["zero", "negative", "above-maximum", "infinity", "negative-infinity", "nan"],
)
def test_preflight_timeout_rejects_values_outside_bounded_range(value: float) -> None:
    with pytest.raises(ValueError, match="outside its bounded range"):
        QuarantinedCodexPreflightProbe(total_timeout_seconds=value)


@pytest.mark.parametrize(
    "value",
    [0.001, MAX_PREFLIGHT_TOTAL_TIMEOUT_SECONDS],
    ids=["positive-lower-edge", "maximum"],
)
def test_preflight_timeout_accepts_bounded_edge_values(value: float) -> None:
    QuarantinedCodexPreflightProbe(total_timeout_seconds=value)


async def test_total_timeout_is_sanitized_and_stops_the_probe(
    hardening_client_factory: ClientFactory,
) -> None:
    client, transport = hardening_client_factory()
    await initialize(client, transport)
    probe = QuarantinedCodexPreflightProbe(total_timeout_seconds=0.05)
    task = asyncio.create_task(probe.probe(client, _plan()))
    request = await sent(transport)
    assert isinstance(request, wire.RequestMessage)
    assert request.method == "skills/list"

    with pytest.raises(CodexRuntimeAdmissionError) as caught:
        await task

    assert str(caught.value) == "Codex quarantined preflight failed"
    assert "timeout" not in str(caught.value).lower()
    assert transport.sent.empty()


async def test_skill_attestation_runs_off_the_event_loop_thread(
    hardening_client_factory: ClientFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event_loop_thread = threading.get_ident()
    attestation_threads: list[int] = []
    real_attest = attest_skills_list

    def recording_attest(
        payload: Mapping[str, object],
        plan: SkillAttestationPlan,
    ) -> SkillAttestation:
        attestation_threads.append(threading.get_ident())
        return real_attest(payload, plan)

    monkeypatch.setattr(preflight_module, "attest_skills_list", recording_attest)
    client, transport = hardening_client_factory()
    await initialize(client, transport)
    task = asyncio.create_task(QuarantinedCodexPreflightProbe().probe(client, _plan()))
    await _respond(transport, "skills/list", _SKILLS_PARAMS, _skills_payload())
    await _respond(
        transport,
        "mcpServerStatus/list",
        _MCP_PARAMS,
        _empty_mcp_payload(),
    )
    await _respond(transport, "hooks/list", _HOOKS_PARAMS, _hooks_payload())

    receipt = await task

    assert receipt.skill_attestation.selected_names == ()
    assert len(attestation_threads) == 1
    assert attestation_threads[0] != event_loop_thread
