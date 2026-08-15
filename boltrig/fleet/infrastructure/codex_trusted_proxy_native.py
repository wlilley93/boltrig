"""Native-collaboration projection for trusted Codex model proxies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import httpx

from boltrig.fleet.domain import NativeSubagentLimits

from .codex_model_proxy_server import BearerDigestLookup, PerCellModelProxyServer
from .codex_native_collaboration_wire import (
    NativeCollaborationWireGate as NativeCollaborationWireGate,
)
from .codex_runtime_admission import CodexPhaseAdmission
from .codex_runtime_config import CodexReasoningEffort
from .codex_trusted_proxy_support import (
    GenerationHolder,
    tracking_bearer_verifier,
)


@dataclass(frozen=True)
class CodexProxyAdmission:
    """Exact model-proxy ceiling derived from one admitted policy."""

    allowed_tools: frozenset[str]
    model_id: str
    reasoning_effort: str
    native_subagents: NativeSubagentLimits
    native_collaboration: NativeCollaborationWireGate | None


class TrustedProxyBackend(Protocol):
    _grant_store: BearerDigestLookup
    _upstream_base_url: str
    _upstream_key: str
    _client: httpx.AsyncClient
    _reasoning_effort: CodexReasoningEffort


def codex_proxy_admission(admission: CodexPhaseAdmission) -> CodexProxyAdmission:
    policy = admission.compilation.policy
    model_id = policy.model.model_id
    effort = policy.model.reasoning_effort.value
    ceiling = frozenset(admission.kernel_tools) | frozenset(policy.enabled_tools)
    gate = (
        None
        if policy.native_subagents.max_total == 0
        else NativeCollaborationWireGate(
            max_total=policy.native_subagents.max_total,
            allowed_model=model_id,
            allowed_reasoning_effort=effort,
        )
    )
    return CodexProxyAdmission(
        ceiling, model_id, effort, policy.native_subagents, gate
    )


async def start_codex_model_proxy(
    backend: TrustedProxyBackend,
    holder: GenerationHolder,
    allowed_tools: frozenset[str],
    allowed_model: str,
    allowed_reasoning_effort: str | None,
    *,
    gateway_virtual_key: str | None = None,
    native_collaboration: NativeCollaborationWireGate | None = None,
) -> PerCellModelProxyServer:
    effort = (
        backend._reasoning_effort.value
        if allowed_reasoning_effort is None
        else allowed_reasoning_effort
    )
    proxy = PerCellModelProxyServer(
        verify_bearer=tracking_bearer_verifier(backend._grant_store, holder),
        upstream_base_url=backend._upstream_base_url,
        upstream_key=backend._upstream_key,
        upstream_virtual_key=gateway_virtual_key,
        client=backend._client,
        allowed_model=allowed_model,
        allowed_reasoning_effort=effort,
        allowed_tools=allowed_tools,
        native_collaboration=native_collaboration,
    )
    await proxy.start()
    return proxy
