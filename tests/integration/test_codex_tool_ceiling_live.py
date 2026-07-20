"""Live re-proof of the tool ceiling on the pinned binary ([2026] VJS-CC-VJS 4 F5).

The court required an end-to-end observation on the PINNED artifact showing the
bound holding on the real wire, re-run as a gate, and re-run whenever
``CODEX_CLI_SHA256`` changes. A unit test of ``enforce_tool_ceiling`` alone was
expressly held insufficient, and rightly: the defect this guards against was a
mismatch between what the kernel asserted and what the runtime actually sent, and
only the real runtime can produce the real request.

So this drives a REAL Codex 0.144.3 App Server through the REAL provider and proxy
and captures BOTH sides of the ceiling:

- the body as it ARRIVES, which must carry Codex's built-in tools, because a run
  where Codex happened to offer nothing would prove nothing at all; and
- the body as it LEAVES, which must carry no tools key.

A mock upstream is NOT enough and was tried first: Codex probes the gateway before
the model call, and a mock that answers implausibly makes it abandon the turn
before any tool set is ever composed. The test would then pass vacuously by
observing nothing. So this drives the real gateway.

Opt-in, like the other pinned-binary tests: set BOLTRIG_CODEX_01443_SMOKE_BINARY
to the absolute path of the pinned binary, plus BOLTRIG_MODEL_GATEWAY_URL. It
never searches PATH.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

import httpx
import pytest

from boltrig.fleet.application.model_proxy_grants import PhaseScopedModelProxyGrantBroker
from boltrig.fleet.domain.execution import (
    OrganisationUserRef,
    PhaseAssignmentRef,
    PhaseRef,
)
from boltrig.fleet.infrastructure import codex_model_proxy_server as proxy_module
from boltrig.fleet.infrastructure.codex_cell_boundary import (
    DEFAULT_SHARED_HELPER_PATH,
    CodexCellBoundaryError,
    assert_cell_isolation_boundary,
)
from boltrig.fleet.infrastructure.codex_cell_provisioning import (
    ProvisioningCodexPhaseAdmissionSource,
)
from boltrig.fleet.infrastructure.codex_cell_supervisor import CodexCellSupervisor
from boltrig.fleet.infrastructure.codex_cell_policy import CODEX_CLI_SHA256
from boltrig.fleet.infrastructure.codex_runtime_preflight import (
    QuarantinedCodexPreflightProbe,
)
from boltrig.fleet.infrastructure.codex_trusted_proxy_provider import (
    TrustedProxyCodexPhaseCellProvider,
)
from boltrig.fleet.infrastructure.memory_model_proxy_grants import (
    MemoryModelProxyGrantStore,
)
from boltrig.fleet.infrastructure.model_proxy_peer_attestation import (
    LinuxModelProxyPeerAttestor,
)
from boltrig.fleet.infrastructure.model_proxy_peer_registry import (
    ModelProxyProcessRegistry,
)

_BINARY_ENV = "BOLTRIG_CODEX_01443_SMOKE_BINARY"

# Codex 0.144.3's built-in tools. If Codex stops offering these the ceiling is not
# doing anything and this test must fail rather than pass vacuously.
_BUILT_IN_TOOLS = ("exec_command", "update_plan", "view_image")


def _first_tool_bearing(bodies: list[bytes]) -> int | None:
    """Index of the first captured body that declares a tool set, if any."""

    for position, body in enumerate(bodies):
        if not body:
            continue
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict) and payload.get("tools"):
            return position
    return None


def _assignment() -> PhaseAssignmentRef:
    return PhaseAssignmentRef(
        PhaseRef(
            root_run_id="run-f5",
            phase_id="phase-f5",
            principal=OrganisationUserRef("org-f5", "user-f5"),
            workspace_id="ws-f5",
        ),
        "assignment-f5",
    )


def _deployed_boundary_is_present() -> bool:
    """True only where the REAL shared helper is installed, as in the image.

    A stand-in helper cannot satisfy this test: the helper has to actually deliver
    the bearer over the ingress socket, or Codex never makes a model call and the
    test would pass vacuously by observing nothing. So the gate arms only where the
    deployed layout exists, and skips loudly rather than pretending elsewhere.
    """

    try:
        assert_cell_isolation_boundary(
            stack_root=Path("/var/lib/boltrig/codex-cells"), require_ptrace_scope=False
        )
    except CodexCellBoundaryError:
        return False
    return True


@pytest.mark.skipif(
    sys.platform != "linux"
    or not os.environ.get(_BINARY_ENV)
    or not os.environ.get("BOLTRIG_MODEL_GATEWAY_URL")
    or not _deployed_boundary_is_present(),
    reason=(
        f"requires Linux, an absolute {_BINARY_ENV} pin path, a reachable "
        f"BOLTRIG_MODEL_GATEWAY_URL, and the deployed shared auth helper at "
        f"{DEFAULT_SHARED_HELPER_PATH}"
    ),
)
async def test_the_pinned_binary_offers_built_in_tools_and_none_reach_upstream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both sides of the ceiling, on the real pinned artifact."""

    binary = Path(os.environ[_BINARY_ENV])
    # Re-runs meaningfully when the pin moves: a new binary may offer a new tool.
    assert (
        hashlib.sha256(binary.read_bytes()).hexdigest() == CODEX_CLI_SHA256
    ), "the smoke binary is not the pinned Codex 0.144.3 artifact"

    arriving: list[bytes] = []
    leaving: list[bytes] = []
    real_enforce = proxy_module.enforce_tool_ceiling

    def recording_enforce(body: bytes, allowed: frozenset[str]) -> bytes:
        arriving.append(body)
        result = real_enforce(body, allowed)
        leaving.append(result)
        return result

    monkeypatch.setattr(proxy_module, "enforce_tool_ceiling", recording_enforce)

    stack = Path(tempfile.mkdtemp(prefix="f5-"))
    store = MemoryModelProxyGrantStore()
    registry = ModelProxyProcessRegistry()
    attestor = LinuxModelProxyPeerAttestor(registry)
    env: dict[str, Any] = dict(os.environ)
    env["BOLTRIG_DEV_AUTH"] = "1"
    env["BOLTRIG_CODEX_TRUSTED"] = "1"

    async with httpx.AsyncClient(timeout=120.0) as client:
        provider = TrustedProxyCodexPhaseCellProvider(
            source=ProvisioningCodexPhaseAdmissionSource(
                stack_root=stack, model_id="glm-4.6"
            ),
            supervisor=CodexCellSupervisor(binary=binary, auth=None),
            probe=QuarantinedCodexPreflightProbe(),
            broker=PhaseScopedModelProxyGrantBroker(store),
            grant_store=store,
            registry=registry,
            attestor=attestor,
            stack_root=stack,
            upstream_base_url=os.environ["BOLTRIG_MODEL_GATEWAY_URL"],
            upstream_key=os.environ.get("BOLTRIG_MODEL_GATEWAY_KEY", ""),
            http_client=client,
            env=env,
        )
        leased = await provider.acquire(_assignment())
        try:
            started = await leased.cell.client.thread_start(
                cwd=leased.admission.layout.workspace.as_posix(),
                model=leased.admission.compilation.policy.model.model_id,
                sandbox="read-only",
                approval_policy="never",
                developer_instructions=leased.admission.developer_instructions,
            )
            await leased.cell.client.turn_start(
                started.thread_id, prompt="say hi", client_user_message_id="f5-1"
            )
            for _ in range(80):
                note = await leased.cell.client.next_notification(timeout=5.0)
                if note.method.endswith("turn/completed") or note.method.endswith(
                    "turn/failed"
                ):
                    break
        except Exception:  # noqa: BLE001 - a failed turn is acceptable, see above
            pass
        finally:
            await leased.cell.aclose()
            await attestor.aclose()

    assert arriving, "the pinned binary made no model call, so nothing was proved"
    # Not every captured request is the model call (a GET carries no body), so
    # select the first one that actually declares a tool set.
    index = _first_tool_bearing(arriving)
    assert index is not None, "no captured request declared a tool set"
    offered = json.loads(arriving[index].decode("utf-8"))
    offered_names = {
        str(tool.get("name") or tool.get("type"))
        for tool in (offered.get("tools") or [])
        if isinstance(tool, dict)
    }
    # Guards against a vacuous pass: the ceiling only means something if the real
    # runtime genuinely offered tools on this exact artifact.
    assert set(_BUILT_IN_TOOLS) <= offered_names, offered_names

    sent = json.loads(leaving[index].decode("utf-8"))
    assert "tools" not in sent
    assert "tool_choice" not in sent
    assert b"exec_command" not in leaving[index]
