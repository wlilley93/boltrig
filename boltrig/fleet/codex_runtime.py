"""Runtime-protocol adapter over a supervised read-only Codex phase.

This is the seam that makes Codex selectable by the spawner. The live selection
path speaks the one-shot ``Runtime`` protocol (runtime.py: ``run(prompt, ctx, *,
tools) -> AgentResult``), while Codex implements the disjoint ``AgentRuntime``
bounded-phase lifecycle (``start_thread -> start_turn -> events -> close_thread``,
plus a ``read_turn_output`` content read-back, since ``events()`` is a
content-free lifecycle ledger). ``CodexRuntime`` bridges the two: it mints a
read-only phase assignment from the invocation context, runs exactly one turn,
reads the turn's assistant text back, and returns a uniform ``AgentResult``.

Offline/degrade-safe (P9): a missing run scope, any runtime error, or empty
output yields a clearly-marked degraded ``AgentResult`` (never an exception into
the caller), exactly like every other runtime. Read-only by construction: the
thread spec pins ``PhaseMode.READ_ONLY`` / ``SandboxPolicy.READ_ONLY`` (the write
phase is the separate, court-gated PR8 and is not reachable from here).
"""

from __future__ import annotations

import contextlib
import logging
import uuid
from collections.abc import AsyncIterator, Mapping
from typing import TYPE_CHECKING, Any, Protocol

from pathlib import Path

if TYPE_CHECKING:  # avoid importing runtime.py at module load (it imports us lazily)
    from boltrig.fleet.runtime import Runtime

from boltrig.fleet.domain import (
    PhaseAssignmentRef,
    RuntimeEvent,
    RuntimeThreadRef,
    RuntimeTurnRef,
)
from boltrig.fleet.infrastructure.codex_kernel_tool_scope import CodexKernelToolScope
from boltrig.fleet.infrastructure.codex_assignment_model_binding import (
    CodexAssignmentModelBinding,
    CodexAssignmentModelBindingRegistry,
)
from boltrig.fleet.infrastructure.codex_kernel_tools_phase import (
    admissible_kernel_tool_names,
    kernel_tools_thread_spec,
)
from boltrig.fleet.infrastructure.codex_read_only_phase import read_only_thread_spec
from boltrig.fleet.ports.runtime import RuntimeThreadSpec, RuntimeTurnSpec
from boltrig.models import InvocationContext

from .codex_kernel_tool_wiring import (
    DEFAULT_KERNEL_TOOLS_TOKEN_TTL_SECONDS,
    CodexKernelToolWiring,
)
from .codex_runtime_support import (
    drain_until_complete,
    empty_output_reason,
    mint_assignment,
)
from .result import AgentResult

logger = logging.getLogger(__name__)

# Retained private compatibility name for focused token-accounting tests and
# downstream diagnostics; the runtime itself calls the extracted helper directly.
_drain_until_complete = drain_until_complete


class CodexPhaseLifecycle(Protocol):
    """The subset of the Codex ``AgentRuntime`` the adapter drives, plus the
    content read-back it needs to build an ``AgentResult`` (``CodexAgentRuntime``
    satisfies this; tests inject a fake)."""

    async def start_thread(self, spec: RuntimeThreadSpec) -> RuntimeThreadRef: ...

    async def start_turn(self, spec: RuntimeTurnSpec) -> RuntimeTurnRef: ...

    def events(self, thread: RuntimeThreadRef) -> AsyncIterator[RuntimeEvent]: ...

    async def read_turn_output(self, thread: RuntimeThreadRef) -> str: ...

    async def close_thread(self, thread: RuntimeThreadRef) -> None: ...


class CodexRuntime:
    """One read-only Codex phase per ``run``, mapped to a uniform ``AgentResult``."""

    runtime = "codex"

    def __init__(
        self,
        lifecycle: CodexPhaseLifecycle,
        *,
        stack_root: Path,
        cost_tier: str = "standard",
        kernel_tools: CodexKernelToolWiring | None = None,
        model_id: str | None = None,
        model_endpoint_id: str | None = None,
        gateway_virtual_key: str | None = None,
        model_bindings: CodexAssignmentModelBindingRegistry | None = None,
    ) -> None:
        if kernel_tools is not None and type(kernel_tools) is not CodexKernelToolWiring:
            raise TypeError("kernel_tools must be an exact CodexKernelToolWiring")
        if (
            model_bindings is not None
            and type(model_bindings) is not CodexAssignmentModelBindingRegistry
        ):
            raise TypeError("model_bindings must be an exact CodexAssignmentModelBindingRegistry")
        if (model_bindings is None) != (model_id is None):
            raise ValueError("model id and binding registry must be configured together")
        self._lifecycle = lifecycle
        self._stack_root = stack_root
        self.cost_tier = cost_tier
        self._kernel_tools = kernel_tools
        self._model_id = model_id
        self._model_endpoint_id = model_endpoint_id
        self._gateway_virtual_key = gateway_virtual_key
        self._model_bindings = model_bindings

    async def run(
        self, prompt: str, context: InvocationContext, *, tools: list[str]
    ) -> AgentResult:
        run_id = context.run_id
        workspace_id = context.workspace_id
        if not run_id or not workspace_id:
            # A Codex phase is scoped to a run + workspace; without them there is
            # nothing to provision. Degrade rather than fabricate a scope.
            return AgentResult.degrade(
                runtime=self.runtime, reason="no_read_only_phase_scope", prompt=prompt
            )
        assignment = mint_assignment(context, run_id, workspace_id)
        binding_registered = False
        if self._model_bindings is not None:
            try:
                assert self._model_id is not None
                self._model_bindings.register(
                    CodexAssignmentModelBinding(
                        assignment=assignment,
                        tenant_id=context.tenant_id,
                        model_id=self._model_id,
                        endpoint_id=self._model_endpoint_id,
                        gateway_virtual_key=self._gateway_virtual_key,
                    )
                )
                binding_registered = True
            except Exception as error:
                logger.exception("codex model binding failed for run %s", context.run_id)
                return AgentResult.degrade(
                    runtime=self.runtime,
                    reason=f"codex_model_binding_failed:{type(error).__name__}",
                    prompt=prompt,
                )
        try:
            if self._kernel_tools is not None:
                return await self._run_kernel_tools(prompt, context, assignment)
            return await self._run_phase(
                prompt, read_only_thread_spec(assignment, self._stack_root)
            )
        finally:
            if binding_registered:
                assert self._model_bindings is not None
                self._model_bindings.discard(assignment)

    async def _run_kernel_tools(
        self, prompt: str, context: InvocationContext, assignment: PhaseAssignmentRef
    ) -> AgentResult:
        """The tool-enabled lane: the cell's only tools are the kernel's MCP face.

        Mints a run-scoped kernel MCP token scoped to EXACTLY this run's grants
        (the pi idiom), compiles the run's effective tool set as Codex wire
        names, and registers both for the provider to consume at provisioning.
        The token is revoked and the scope discarded in ``finally``, whether the
        phase ran, failed, or never started.
        """

        wiring = self._kernel_tools
        assert wiring is not None
        token: str | None = None
        try:
            verb_ids = await wiring.compile_tool_ceiling(context.tenant_id, context.grants)
            tools = admissible_kernel_tool_names(verb_ids, run_id=context.run_id)
            if tools is None:
                # Voice without hands, never silence: the helper already said why.
                return await self._run_phase(
                    prompt, read_only_thread_spec(assignment, self._stack_root)
                )
            token = wiring.issue_token(
                context.tenant_id,
                context.grants,
                run_id=context.run_id,
                actor=context.actor,
                actor_tier=context.actor_tier,
                skills=context.skills_loaded,
                workspace_id=context.workspace_id,
                on_behalf_of=context.on_behalf_of,
                # So a verb this cell dispatches can publish its HITL pause to the
                # parent (chat) stream, not only to this child run's - see the
                # PendingHuman branch in kernel/dispatch.py.
                parent_run_id=context.parent_run_id,
                extra=dict(context.extra),
                ttl_seconds=wiring.ttl_seconds,
            )
            wiring.registry.register(
                CodexKernelToolScope(
                    assignment_id=assignment.assignment_id,
                    mcp_url=wiring.mcp_url,
                    tools=tools,
                    token=token,
                )
            )
            return await self._run_phase(
                prompt, kernel_tools_thread_spec(assignment, self._stack_root)
            )
        except Exception as error:
            # Same contract as the read-only lane: degrade, never raise into the
            # caller, and carry only a cause tag - never token material.
            logger.exception("codex kernel-tools turn failed for run %s", context.run_id)
            return AgentResult.degrade(
                runtime=self.runtime,
                reason=f"codex_turn_failed:{type(error).__name__}",
                prompt=prompt,
            )
        finally:
            wiring.registry.discard(assignment.assignment_id)
            if token is not None:
                with contextlib.suppress(Exception):
                    wiring.revoke_token(token)

    async def _run_phase(self, prompt: str, spec: RuntimeThreadSpec) -> AgentResult:
        text = ""
        # Held outside the try so a degrade can still report what the turn consumed
        # before it failed: the provider was paid whether or not we got a usable
        # answer out of it.
        tokens_used = 0
        usage_seen: list[int] = []
        # The last reported input/output SPLIT, caller-owned for the same reason as
        # `usage_seen`: a raise discards the drain's locals. Kept because the two
        # legs are priced at different rates - billing an input-heavy turn as if it
        # were all output costs the tenant more than twice what it should.
        usage_legs: dict[str, int] = {}
        # Runtime ERROR events, caller-owned for the same reason as the two above.
        runtime_errors: list[Mapping[str, object]] = []
        thread: RuntimeThreadRef | None = None
        try:
            thread = await self._lifecycle.start_thread(spec)
            await self._lifecycle.start_turn(
                RuntimeTurnSpec(thread=thread, prompt=prompt, client_message_id=uuid.uuid4().hex)
            )
            tokens_used = await drain_until_complete(
                self._lifecycle.events(thread), usage_seen, usage_legs, runtime_errors
            )
            text = await self._lifecycle.read_turn_output(thread)
        except Exception as error:
            # A degrade must never swallow the cause: a silent codex_turn_failed is
            # unactionable in ops. Log the full traceback and carry a short cause
            # tag in the reason so the failure is visible on the wire and in logs.
            logger.exception(
                "codex read-only turn failed for run %s", spec.assignment.phase.root_run_id
            )
            cause = type(error).__name__
            return AgentResult.degrade(
                runtime=self.runtime,
                reason=f"codex_turn_failed:{cause}",
                prompt=prompt,
                # Whatever the turn had already consumed before it died. The
                # provider was paid for it either way.
                tokens_used=usage_seen[-1] if usage_seen else 0,
                input_tokens=usage_legs.get("input_tokens", 0),
                output_tokens=usage_legs.get("output_tokens", 0),
            )
        finally:
            if thread is not None:
                with contextlib.suppress(Exception):
                    await self._lifecycle.close_thread(thread)
        if not text:
            # The model ran and consumed tokens, it just produced nothing usable.
            # Reporting 0 here (as this did) made a paid-for turn record as free and
            # handed the tenant a full budget refund for spend that really happened.
            return AgentResult.degrade(
                runtime=self.runtime,
                reason=empty_output_reason(runtime_errors, spec.assignment.phase.root_run_id),
                prompt=prompt,
                tokens_used=tokens_used,
                input_tokens=usage_legs.get("input_tokens", 0),
                output_tokens=usage_legs.get("output_tokens", 0),
            )
        # Report what the turn consumed so the fleet can price it, INCLUDING the
        # input/output split, because those legs carry different rates. `cost_micros`
        # is left to the accountant, which applies the tenant's own per-model/tier
        # rate (`price_micros`); the runtime's job is to report usage honestly, not
        # to price it.
        return AgentResult.succeeded(
            output={"runtime": "codex_app_server", "text": text},
            summary=text[:256],
            tokens_used=tokens_used,
            input_tokens=usage_legs.get("input_tokens", 0),
            output_tokens=usage_legs.get("output_tokens", 0),
        )


def build_trusted_codex_runtime(codex_config: dict[str, Any] | None, cost_tier: str) -> "Runtime":
    """Construct the trusted read-only Codex runtime, or a typed unavailable one.

    The provider + stack_root are pre-built at the composition root and carried in
    ``codex_config``. Re-assert the dev/prod wall HERE ([2026] VJS-CC-VJS 2, D1) so
    the runtime is structurally unreachable under any production signal, then run
    under the existing ``allow_test_only_runtime`` gate with ``production_ready``
    left False (D4). Anything short of trusted+wired is an unavailable lane and
    degrades to ``UnavailableRuntime`` - degrade-marked, never a script echo
    presented upstream as a real Codex answer (US-FLT-07, decision 0012).

    The kernel-tools lane (``kernel_tools`` marker set by the resolver for a
    ``runtime: codex`` capability with ``supported_skills: '*'``) additionally
    requires the run-scoped-token + tool-ceiling seams; a capability that asks
    for tool use without the full wiring is an unavailable lane, never a silent
    downgrade to read-only reasoning (US-FLT-07).
    """
    from .runtime import UnavailableRuntime

    cfg = dict(codex_config or {})
    provider = cfg.get("provider")
    stack_root = cfg.get("stack_root")
    model_id = cfg.get("model_id")
    if not (
        cfg.get("trusted")
        and provider is not None
        and stack_root is not None
        and isinstance(model_id, str)
        and model_id
    ):
        return UnavailableRuntime(requested="codex", cost_tier=cost_tier or "cheap")
    from boltrig.fleet.codex_trusted_wall import require_codex_trusted_posture
    from boltrig.fleet.infrastructure.codex_agent_runtime import CodexAgentRuntime
    from boltrig.fleet.infrastructure.codex_trusted_proxy_provider import (
        TrustedProxyCodexPhaseCellProvider,
    )

    require_codex_trusted_posture()
    if type(provider) is not TrustedProxyCodexPhaseCellProvider:
        return UnavailableRuntime(requested="codex", cost_tier=cost_tier or "cheap")
    kernel_tools: CodexKernelToolWiring | None = None
    if cfg.get("kernel_tools"):
        try:
            kernel_tools = CodexKernelToolWiring(
                issue_token=cfg.get("issue_token"),
                revoke_token=cfg.get("revoke_token"),
                compile_tool_ceiling=cfg.get("compile_tool_ceiling"),
                mcp_url=cfg.get("mcp_url"),
                registry=provider.kernel_tool_scopes,
                ttl_seconds=int(
                    cfg.get("mcp_token_ttl_seconds") or DEFAULT_KERNEL_TOOLS_TOKEN_TTL_SECONDS
                ),
            )
        except (TypeError, ValueError):
            return UnavailableRuntime(requested="codex", cost_tier=cost_tier or "cheap")
    return CodexRuntime(
        CodexAgentRuntime(provider, allow_test_only_runtime=True),
        stack_root=stack_root,
        cost_tier=cost_tier or "standard",
        kernel_tools=kernel_tools,
        model_id=model_id,
        model_endpoint_id=cfg.get("model_endpoint_id"),
        gateway_virtual_key=cfg.get("gateway_virtual_key"),
        model_bindings=provider.model_bindings,
    )


__all__ = [
    "CodexKernelToolWiring",
    "CodexPhaseLifecycle",
    "CodexRuntime",
    "DEFAULT_KERNEL_TOOLS_TOKEN_TTL_SECONDS",
    "build_trusted_codex_runtime",
]
