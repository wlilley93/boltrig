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
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from pathlib import Path

if TYPE_CHECKING:  # avoid importing runtime.py at module load (it imports us lazily)
    from boltrig.fleet.runtime import Runtime

from boltrig.fleet.domain import (
    PhaseAssignmentRef,
    PhaseRef,
    RuntimeEvent,
    RuntimeEventKind,
    RuntimeThreadRef,
    RuntimeTurnRef,
)
from boltrig.fleet.infrastructure.codex_kernel_tool_scope import (
    CodexKernelToolScope,
    CodexKernelToolScopeRegistry,
)
from boltrig.fleet.infrastructure.codex_kernel_tools_phase import (
    codex_mcp_tool_name,
    kernel_tools_thread_spec,
    validated_kernel_tool_names,
)
from boltrig.fleet.infrastructure.codex_read_only_phase import read_only_thread_spec
from boltrig.fleet.infrastructure.codex_runtime_config_policy import (
    CodexRuntimeConfigError,
    validate_mcp_server_url,
)
from boltrig.fleet.ports.runtime import RuntimeThreadSpec, RuntimeTurnSpec
from boltrig.models import GrantSet, InvocationContext
from boltrig.models.execution_scope import OrganisationUserRef

from .result import AgentResult

logger = logging.getLogger(__name__)

DEFAULT_KERNEL_TOOLS_TOKEN_TTL_SECONDS = 3600

# issue_token(tenant_id, grants, *, run_id, actor, skills, ...) -> token (the
# same McpFace.issue_run_token seam pi/opencode/rivet mint from, SEC-23).
TokenIssuer = Callable[..., str]
# compile_tool_ceiling(tenant_id, grants) -> the run's effective verb ids
# (tenant ceiling ∩ run grants - exactly the kernel MCP tools/list derivation,
# FR-MCP-02). Injected at the composition seam; the runtime holds no store.
ToolCeilingCompiler = Callable[[str, GrantSet], Awaitable[tuple[str, ...]]]


@dataclass(frozen=True, repr=False, slots=True)
class CodexKernelToolWiring:
    """The kernel-tools lane's injected seams; carries NO secret material."""

    issue_token: TokenIssuer
    revoke_token: Callable[[str], None]
    compile_tool_ceiling: ToolCeilingCompiler
    mcp_url: str
    registry: CodexKernelToolScopeRegistry
    ttl_seconds: int = DEFAULT_KERNEL_TOOLS_TOKEN_TTL_SECONDS

    def __post_init__(self) -> None:
        if not callable(self.issue_token) or not callable(self.revoke_token):
            raise TypeError("kernel tool wiring token callables are required")
        if not callable(self.compile_tool_ceiling):
            raise TypeError("kernel tool wiring requires a tool ceiling compiler")
        try:
            validate_mcp_server_url(self.mcp_url)
        except CodexRuntimeConfigError as error:
            raise ValueError(str(error)) from None
        if type(self.registry) is not CodexKernelToolScopeRegistry:
            raise TypeError("registry must be an exact CodexKernelToolScopeRegistry")
        if type(self.ttl_seconds) is not int or not 1 <= self.ttl_seconds <= 3600:
            raise ValueError("kernel tool token TTL must be between 1 and 3600 seconds")

    def __repr__(self) -> str:
        return "CodexKernelToolWiring(redacted=True)"


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
    ) -> None:
        if kernel_tools is not None and type(kernel_tools) is not CodexKernelToolWiring:
            raise TypeError("kernel_tools must be an exact CodexKernelToolWiring")
        self._lifecycle = lifecycle
        self._stack_root = stack_root
        self.cost_tier = cost_tier
        self._kernel_tools = kernel_tools

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
        assignment = _mint_assignment(context, run_id, workspace_id)
        if self._kernel_tools is not None:
            return await self._run_kernel_tools(prompt, context, assignment)
        return await self._run_phase(
            prompt, read_only_thread_spec(assignment, self._stack_root)
        )

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
            tools = validated_kernel_tool_names(
                tuple({codex_mcp_tool_name(verb_id) for verb_id in verb_ids})
            )
            if not tools:
                # A tool-enabled capability whose run holds NO effective verbs
                # (e.g. a chat turn whose role loads no skills) has no MCP face
                # to offer. Run the plain read-only phase - exactly what the
                # legacy lanes did with empty grants - rather than provisioning
                # a cell whose config advertises a server its admission does
                # not declare. Observable, never silent.
                logger.warning(
                    "codex kernel-tools run %s has no effective tools; "
                    "falling back to the read-only phase",
                    context.run_id,
                )
                return await self._run_phase(
                    prompt, read_only_thread_spec(assignment, self._stack_root)
                )
            token = wiring.issue_token(
                context.tenant_id,
                context.grants,
                run_id=context.run_id,
                actor=context.actor,
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
            logger.exception(
                "codex kernel-tools turn failed for run %s", context.run_id
            )
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
        thread: RuntimeThreadRef | None = None
        try:
            thread = await self._lifecycle.start_thread(spec)
            await self._lifecycle.start_turn(
                RuntimeTurnSpec(
                    thread=thread, prompt=prompt, client_message_id=uuid.uuid4().hex
                )
            )
            tokens_used = await _drain_until_complete(
                self._lifecycle.events(thread), usage_seen, usage_legs
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
                reason="codex_empty_output",
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


def build_trusted_codex_runtime(
    codex_config: dict[str, Any] | None, cost_tier: str
) -> "Runtime":
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
    if not (cfg.get("trusted") and provider is not None and stack_root is not None):
        return UnavailableRuntime(requested="codex", cost_tier=cost_tier or "cheap")
    from boltrig.fleet.codex_trusted_wall import require_codex_trusted_posture
    from boltrig.fleet.infrastructure.codex_agent_runtime import CodexAgentRuntime
    from boltrig.fleet.infrastructure.codex_trusted_proxy_provider import (
        TrustedProxyCodexPhaseCellProvider,
    )

    require_codex_trusted_posture()
    kernel_tools: CodexKernelToolWiring | None = None
    if cfg.get("kernel_tools"):
        if type(provider) is not TrustedProxyCodexPhaseCellProvider:
            return UnavailableRuntime(requested="codex", cost_tier=cost_tier or "cheap")
        try:
            kernel_tools = CodexKernelToolWiring(
                issue_token=cfg.get("issue_token"),
                revoke_token=cfg.get("revoke_token"),
                compile_tool_ceiling=cfg.get("compile_tool_ceiling"),
                mcp_url=cfg.get("mcp_url"),
                registry=provider.kernel_tool_scopes,
                ttl_seconds=int(cfg.get("mcp_token_ttl_seconds") or DEFAULT_KERNEL_TOOLS_TOKEN_TTL_SECONDS),
            )
        except (TypeError, ValueError):
            return UnavailableRuntime(requested="codex", cost_tier=cost_tier or "cheap")
    return CodexRuntime(
        CodexAgentRuntime(provider, allow_test_only_runtime=True),
        stack_root=stack_root,
        cost_tier=cost_tier or "standard",
        kernel_tools=kernel_tools,
    )


async def _drain_until_complete(
    events: AsyncIterator[RuntimeEvent],
    seen: list[int] | None = None,
    legs: dict[str, int] | None = None,
) -> int:
    """Consume the lifecycle stream until the turn completes (the completion
    signal, not the content source), returning the tokens the turn reported.

    Usage arrives on its own notification, mid-turn and possibly more than once, so
    the LAST report before completion wins (Codex's `total` is cumulative for the
    thread). Zero when the runtime reported nothing - which is the honest answer,
    and is what the fleet used to bill unconditionally for every Codex turn because
    the usage notification was being discarded upstream.

    ``seen`` is the caller's sink for usage observed SO FAR. A terminal stream
    raises and the caller degrades, and a raise discards this function's locals -
    so without the sink a turn that consumed real tokens and then died reported
    zero, and the tenant was refunded for spend the provider had already taken.

    ``legs`` is the same idea for that report's input/output SPLIT, which rides on
    the same frame as the total. It is carried because the two legs are priced at
    different rates (boltrig/kernel/cost.py): billing an input-heavy turn at the
    output rate over-bills it substantially. Both sinks are written from the SAME
    accepted report, so they can never disagree about which frame won.
    """
    tokens = 0
    async for event in events:
        if event.kind is RuntimeEventKind.TOKEN_USAGE:
            payload = event.payload.to_mapping()
            reported = payload.get("total_tokens")
            if type(reported) is int and reported > 0:
                tokens = reported
                if seen is not None:
                    seen.append(reported)
                if legs is not None:
                    legs["input_tokens"] = _reported_leg(payload.get("input_tokens"))
                    legs["output_tokens"] = _reported_leg(payload.get("output_tokens"))
        elif event.kind is RuntimeEventKind.TURN_COMPLETED:
            return tokens
    return tokens


def _reported_leg(value: object) -> int:
    """One usage leg as a non-negative int, or 0 when absent/malformed.

    0 is the honest answer for a leg the runtime did not report, and 0/0 is priced
    at a single rate on the TOTAL - so a partial report degrades to the previous
    behaviour rather than billing the turn as free.
    """
    return value if type(value) is int and value > 0 else 0


def _mint_assignment(
    context: InvocationContext, run_id: str, workspace_id: str
) -> PhaseAssignmentRef:
    """Mint the read-only phase assignment for this chat turn from the context.

    The read-only reasoning phase is identity-bound to the run, not gated by the
    write-phase assignment admission; a deterministic per-run phase/assignment id
    keeps a re-run mapping onto the same phase.
    """
    principal = OrganisationUserRef(
        tenant_id=context.tenant_id,
        user_id=context.on_behalf_of or context.actor or "agent",
    )
    phase = PhaseRef(
        root_run_id=run_id,
        phase_id=f"{run_id}-codex",
        principal=principal,
        workspace_id=workspace_id,
    )
    return PhaseAssignmentRef(phase=phase, assignment_id=f"{run_id}-codex-assignment")


__all__ = [
    "CodexKernelToolWiring",
    "CodexPhaseLifecycle",
    "CodexRuntime",
    "DEFAULT_KERNEL_TOOLS_TOKEN_TTL_SECONDS",
    "build_trusted_codex_runtime",
]
