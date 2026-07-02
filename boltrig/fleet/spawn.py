"""Spawn logic behind ``POST /v1/spawn`` (US-FLT-03/04, FR-EXE-03, FR-COST-02, S7.5).

A spawn turns a task plus a set of skills into one running ephemeral agent:

    load skills (+ ``extends`` inheritance)      -> merged prompt / grants / reqs
    validate the spawn context against the reqs  -> ContextRequirementsUnmet (400)
    pick the cheapest capable runtime            -> by supported_skills + cost tier
    enforce recursion depth                      -> DepthExceeded (429)
    reserve budget BEFORE running                -> BudgetExceeded (429 / partial)
    audit the spawn (AGENT_SPAWN)                -> kernel.audit.write
    run the selected runtime                     -> AgentResult

The spawner owns policy *composition* only; the kernel still owns the dispatch
chokepoint for any verb the child invokes (P2). Everything here is offline-safe:
with no SDK / keys, runtimes degrade rather than crash (P9).
"""

from __future__ import annotations

import json
import os
import uuid
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from jsonschema import Draft202012Validator

from boltrig.adapters.base import AdapterError, ErrorClass, Result
from boltrig.models import (
    ActionType,
    AgentCapability,
    AuditEvent,
    BudgetExceeded,
    ContextRequirementsUnmet,
    DepthExceeded,
    GrantSet,
    InvocationContext,
    BoltrigError,
    Skill,
    utcnow,
)

from boltrig.kernel.cost import price_micros

from .model_gateway import ModelGateway, apply_gateway, gateway_config
from .model_router import select_model_endpoint
from .result import AgentResult
from .runtime import build_runtime

if TYPE_CHECKING:  # type-only: keeps fleet import independent of fastapi/kernel
    from boltrig.kernel import Kernel
    from boltrig.kernel.app import Principal, SpawnBody
    from boltrig.kernel.dispatch import AgentInvoker
    from boltrig.models import ModelEndpoint


# --- local error types (created here, not in the frozen models layer) ---------
class SkillNotFound(BoltrigError):
    """A referenced skill (or an ``extends`` parent) does not exist (fail-closed)."""

    status_code = 404
    reason = "skill_not_found"


class NoCapableRuntime(BoltrigError):
    """No agent capability supports all of the requested skills (US-FLT-04)."""

    status_code = 404
    reason = "no_capable_runtime"


# --- cost-tier ordering (cheapest first) --------------------------------------
_COST_ORDER: dict[str, int] = {"cheap": 0, "standard": 1, "expensive": 2}


# --- skill pattern matching (terminal "/*" wildcard + bare "*") ---------------
def _pattern_covers(pattern: str, skill_id: str) -> bool:
    """Whether a ``supported_skills`` pattern covers one skill id.

    Supports the bare ``"*"`` (everything) and terminal-wildcard patterns like
    ``"writing/*"`` (covers ``writing`` and ``writing/anything``) but not a
    bare prefix - mirrors the kernel grant rule (K-9) on the skill namespace.
    """
    if pattern == "*":
        return True
    if pattern == skill_id:
        return True
    if pattern.endswith("/*"):
        prefix = pattern[:-2]
        return skill_id == prefix or skill_id.startswith(prefix + "/")
    return False


def _supports(cap: AgentCapability, skills: list[str]) -> bool:
    """True iff the capability's patterns cover EVERY requested skill."""
    return all(
        any(_pattern_covers(p, s) for p in cap.supported_skills) for s in skills
    )


# --- merged skill view --------------------------------------------------------
class _MergedSkills:
    """The composed prompt / grants / context-requirements of a skill set."""

    def __init__(self) -> None:
        self.prompt_fragments: list[str] = []
        self.tool_grants: list[str] = []
        self.context_requirements: dict[str, Any] = {
            "type": "object",
            "properties": {},
            "required": [],
        }

    def add_grant(self, grant: str) -> None:
        if grant not in self.tool_grants:
            self.tool_grants.append(grant)

    def merge_requirements(self, schema: dict[str, Any]) -> None:
        """Shallow-merge a skill's JSON-Schema requirements: union properties and
        required keys. Conservative and deterministic (full schema algebra is
        out of scope; required-key coverage is what spawn validation needs)."""
        if not schema:
            return
        props = schema.get("properties")
        if isinstance(props, dict):
            self.context_requirements["properties"].update(props)
        required = schema.get("required")
        if isinstance(required, (list, tuple)):
            for key in required:
                if key not in self.context_requirements["required"]:
                    self.context_requirements["required"].append(key)


async def _resolve_skill_chain(
    store: Any, tenant_id: str, skill_id: str, merged: _MergedSkills, seen: set[str]
) -> None:
    """Load a skill and its ``extends`` ancestors, parent-first, into ``merged``.

    Parent fragments/grants/requirements are applied before the child so the
    child augments (never silently loses) the parent (skill inheritance, S6.2).
    """
    if skill_id in seen:  # defend against a cyclic ``extends`` chain
        return
    seen.add(skill_id)
    skill: Skill | None = await store.get_skill(tenant_id, skill_id)
    if skill is None:
        raise SkillNotFound(f"unknown skill '{skill_id}'")
    if skill.extends:  # parent first
        await _resolve_skill_chain(store, tenant_id, skill.extends, merged, seen)
    if skill.prompt_fragment:
        merged.prompt_fragments.append(skill.prompt_fragment)
    for grant in skill.tool_grants:
        merged.add_grant(grant)
    merged.merge_requirements(skill.context_requirements)


def _missing_requirements(
    schema: dict[str, Any], instance: dict[str, Any]
) -> tuple[list[str], list[str]]:
    """Validate ``instance`` against the merged schema via jsonschema.

    Returns ``(missing_required_keys, all_error_messages)``. Missing required
    keys are the headline of ``ContextRequirementsUnmet``; any other validation
    errors (e.g. type mismatch) are carried along in the message.
    """
    properties = schema.get("properties") or {}
    required = schema.get("required") or []
    # An empty merged schema (no properties and no required) imposes nothing.
    if not properties and not required:
        return [], []
    errors = [e.message for e in Draft202012Validator(schema).iter_errors(instance)]
    missing = [key for key in required if key not in instance]
    return missing, errors


def _estimate(task: str, prompt: str, skills: list[str], cost_tier: str) -> tuple[int, int]:
    """A deterministic pre-run (tokens, micros) estimate for budget reservation.

    Priced at the cost-tier default (no model yet at reservation time); the real
    per-model price and actual token count are applied post-run by the true-up
    (FR-COST-03), so a drift here is corrected, never carried."""
    chars = len(task) + len(prompt) + sum(len(s) for s in skills)
    tokens = max(16, chars // 4)
    micros = price_micros(tokens, cost_tier)
    return tokens, micros


class Spawner:
    """Composes and runs ephemeral agents on top of the kernel (S7.5)."""

    def __init__(self, kernel: Kernel, *, sensitive_endpoint_id: str | None = None) -> None:
        self._kernel = kernel
        # the tenant's local endpoint for sensitive data (manifest sensitive_endpoint)
        self._sensitive_endpoint_id = sensitive_endpoint_id
        # Pi sidecar wiring (manifest runtimes.pi maps to these env vars). Absent a
        # sidecar url, a pi capability resolves to a PiRuntime that degrades (P9).
        self._pi = {
            "sidecar_url": os.environ.get("BOLTRIG_PI_SIDECAR_URL") or None,
            "mcp_url": os.environ.get("BOLTRIG_PI_MCP_URL", "http://kernel:8000/v1/mcp"),
            "max_steps": int(os.environ.get("BOLTRIG_PI_MAX_STEPS", "12")),
        }
        # Conversation-scoped model-gateway binding (Round Six gap 3.2). Inert
        # unless BOLTRIG_MODEL_GATEWAY_URL is set; bindings live on this spawner
        # instance, which the chat path constructs once and reuses across turns.
        self._gateway = gateway_config()
        self._bindings = ModelGateway(ttl_seconds=int(self._gateway["ttl_seconds"]))

    async def spawn(
        self,
        tenant_id: str,
        task: str,
        skills: list[str],
        prefer: dict[str, Any],
        context: InvocationContext,
        *,
        partial_on_budget: bool = True,
        grant_ceiling: GrantSet | None = None,
    ) -> dict[str, Any]:
        """Spawn one ephemeral agent for ``task`` with ``skills`` (US-FLT-03/04).

        ``partial_on_budget`` keeps a deep tree alive: when ``True`` (the default
        for in-fleet spawns) a budget hard-stop returns a partial result instead
        of raising (FR-COST-02). The app-facing adapter sets it ``False`` so the
        HTTP caller gets a ``429 budget_exceeded`` (kernel error taxonomy).

        ``grant_ceiling`` caps the child's grants to those the initiator also
        holds - used by Skill Studio test-spawns, eval runs, and personal agents
        so a test/eval/personal turn can never call a verb the initiator lacks
        (no escalation, SEC-29/SEC-30).
        """
        kernel = self._kernel
        prefer = prefer or {}
        skills = list(skills or [])

        # 1. Load skills with ``extends`` inheritance and merge them.
        merged = _MergedSkills()
        for skill_id in skills:
            await _resolve_skill_chain(kernel.store, tenant_id, skill_id, merged, set())

        # 2. Validate the spawn context against the merged requirements. A key
        #    present but ``None`` reads as absent, so a required-but-unset field
        #    surfaces in ``missing`` by name rather than as a type error.
        instance = {k: v for k, v in context_payload(context).items() if v is not None}
        missing, errors = _missing_requirements(merged.context_requirements, instance)
        if missing or errors:
            detail = "; ".join(errors) if errors else "missing required context"
            raise ContextRequirementsUnmet(
                f"spawn context unmet: {detail}",
                missing=missing or errors,
            )

        # 3. Select the cheapest capable runtime (honouring prefer.cost_tier).
        capability = await self._select_capability(tenant_id, skills, prefer)

        # 4. Enforce recursion depth (FR-EXE-03).
        child_depth = context.depth + 1
        if child_depth > capability.max_depth:
            raise DepthExceeded(
                f"depth {child_depth} exceeds max_depth {capability.max_depth} "
                f"for capability '{capability.name}'"
            )

        # 5. Reserve budget BEFORE running (FR-COST-02).
        merged_prompt = "\n\n".join(merged.prompt_fragments)
        run_id = uuid.uuid4().hex
        tokens_est, micros_est = _estimate(
            task, merged_prompt, skills, capability.cost_tier
        )
        scope_ids = ["tenant"]
        department = prefer.get("department")
        if department:
            scope_ids.append(str(department))
        try:
            await kernel.cost.reserve(
                tenant_id, scope_ids=scope_ids, tokens=tokens_est, micros=micros_est
            )
        except BudgetExceeded:
            await self._audit_spawn(
                tenant_id, context, capability, skills, run_id,
                status="budget_exceeded", tokens=0, cost=0,
            )
            if not partial_on_budget:
                raise
            return {
                "run_id": run_id,
                "agent_type": capability.name,
                "status": "partial",
                "degraded": False,
                "reason": "budget_exceeded",
                "summary": "spawn skipped: budget hard-stop reached",
                "output": {},
                "tokens_used": 0,
                "cost_micros": 0,
                "new_work_items": [],
            }

        # 6. Build the child context (depth+1, skill grants, skills loaded). When a
        #    grant ceiling is given (test-spawn / eval / personal agent), the child
        #    gets only grants the initiator also holds - no escalation (SEC-29/30).
        child_grants = GrantSet.of(allow=list(merged.tool_grants))
        if grant_ceiling is not None:
            child_grants = child_grants.intersect(grant_ceiling)
        child_ctx = InvocationContext(
            tenant_id=tenant_id,
            run_id=run_id,
            parent_run_id=context.run_id,
            depth=child_depth,
            on_behalf_of=context.on_behalf_of,
            grants=child_grants,
            actor=capability.name,
            actor_tier="ephemeral",
            skills_loaded=tuple(skills),
            extra=dict(context.extra),  # propagate data_class etc to the child
        )

        # 7. Run the selected runtime (degrades, never crashes, offline). The
        #    data classification on the context gates sensitive->local routing.
        runtime = await self._runtime_for(tenant_id, capability, context)
        prompt = self._compose_prompt(merged_prompt, task)
        # Live run event (Round Ten): announce the sub-agent on the PARENT's run
        # stream so the chat / run-canvas shows the spawn as it happens. Fail-safe
        # observability side-channel - never affects the spawn (P9).
        if context.run_id:
            try:
                kernel.events.publish(context.run_id, {
                    "type": "subagent", "task": task,
                    "skills": list(skills), "child_run_id": run_id,
                    "capability": capability.name,
                })
            except Exception:
                pass
        result: AgentResult = await runtime.run(
            prompt, child_ctx, tools=list(merged.tool_grants)
        )

        # 7b. Cost true-up (FR-COST-03, audit M14). The reserve at step 5 debited an
        #     ESTIMATE. Now that the run reported real usage, reconcile every reserved
        #     scope by the signed delta (actual - estimate) so the ledger reflects
        #     real spend, not the guess. The actual cost is priced from the real
        #     per-model price table (FR-COST-04), falling back to the same tier rate
        #     the estimate used when no price is configured (so an unconfigured
        #     deployment simply corrects the token-count drift). A degraded /
        #     zero-usage run reports tokens_used == 0, so the actual is 0 and the
        #     delta fully refunds the reserved estimate.
        actual_tokens = int(result.tokens_used or 0)
        # Resolve the model name for pricing only when a price table is configured;
        # otherwise the tier fallback needs no model and we skip the extra read.
        priced_model: str | None = None
        if capability.model_endpoint and kernel.cost.has_prices:
            ep = await kernel.store.get_model_endpoint(
                tenant_id, capability.model_endpoint
            )
            priced_model = ep.model if ep is not None else None
        actual_micros = kernel.cost.price(
            actual_tokens, capability.cost_tier, model=priced_model
        )
        await kernel.cost.reconcile(
            tenant_id,
            scope_ids=scope_ids,
            delta_tokens=actual_tokens - tokens_est,
            delta_micros=actual_micros - micros_est,
        )

        # 8. Audit the spawn (AGENT_SPAWN) with real accounting. A degraded run
        #    audits as "degraded", never "ok" (US-FLT-07).
        if result.degraded:
            audit_status = "degraded"
        else:
            audit_status = "ok" if result.ok else "error"
        await self._audit_spawn(
            tenant_id, context, capability, skills, run_id,
            status=audit_status,
            tokens=result.tokens_used, cost=result.cost_micros,
        )

        return {
            "run_id": run_id,
            "agent_type": capability.name,
            "status": "ok" if result.ok else "error",
            "degraded": result.degraded,
            "summary": result.summary,
            "output": result.output,
            "tokens_used": result.tokens_used,
            "cost_micros": result.cost_micros,
            "new_work_items": list(result.new_work_items),
            # the child's effective grants after the ceiling intersection: a
            # test-spawn/eval/personal turn can never exceed the initiator (SEC-29).
            "effective_grants": list(child_grants.allow),
        }

    # --- internals ------------------------------------------------------------
    async def _select_capability(
        self, tenant_id: str, skills: list[str], prefer: dict[str, Any]
    ) -> AgentCapability:
        """Cheapest capable capability; honour ``prefer.cost_tier`` (US-FLT-04)."""
        caps = await self._kernel.store.list_capabilities(tenant_id)
        capable = [c for c in caps if _supports(c, skills)]
        if not capable:
            raise NoCapableRuntime(
                f"no capability supports skills {skills} for tenant '{tenant_id}'"
            )
        preferred_tier = prefer.get("cost_tier")
        if preferred_tier:
            tier_matches = [c for c in capable if c.cost_tier == preferred_tier]
            if tier_matches:  # fall back to overall-cheapest if the tier has none
                capable = tier_matches
        return min(
            capable, key=lambda c: (_COST_ORDER.get(c.cost_tier, 99), c.name)
        )

    async def _runtime_for(
        self, tenant_id: str, capability: AgentCapability, context: InvocationContext | None = None
    ):
        """Resolve the model endpoint (with the sensitive->local guard) and build
        the runtime. Sensitive-classified data (``context.extra['data_class'] ==
        'sensitive'``) may only resolve to a local endpoint, else the guard raises
        ``SensitiveDataMisrouted`` and audits it (SEC-12, US-PRIV-01)."""
        sensitive = bool(context is not None and context.extra.get("data_class") == "sensitive")
        endpoint = await select_model_endpoint(
            self._kernel.store,
            tenant_id,
            capability.model_endpoint,
            sensitive=sensitive,
            sensitive_endpoint_id=self._sensitive_endpoint_id,
            audit=self._kernel.audit,
            actor=capability.name,
        )

        # Route standard (non-sensitive) conversation traffic through the model
        # gateway, pinned to the conversation's bound model so its prompt cache
        # stays warm across turns (gap 3.2). Inert when no gateway is configured;
        # sensitive data is never re-routed (residency, SEC-47).
        conversation_id = context.extra.get("conversation_id") if context is not None else None
        endpoint = apply_gateway(
            endpoint,
            gateway_url=self._gateway["base_url"],
            binding=self._bindings,
            conversation_id=conversation_id,
            sensitive=sensitive,
        )

        def lookup(endpoint_id: str) -> ModelEndpoint | None:
            if endpoint is not None and endpoint.id == endpoint_id:
                return endpoint
            return None

        if capability.runtime == "pi":
            pi_config: dict[str, Any] = {
                "sidecar_url": self._pi["sidecar_url"],
                "mcp_url": self._pi["mcp_url"],
                "max_steps": self._pi["max_steps"],
                "issue_token": self._kernel.mcp.issue_run_token,
                "revoke_token": self._kernel.mcp.revoke,
            }
            if context is not None and context.run_id:
                run_id = context.run_id  # bind for the relay sink
                pi_config["event_sink"] = lambda ev: self._kernel.events.publish(run_id, ev)
            return build_runtime(capability, lookup, pi_config=pi_config)
        return build_runtime(capability, lookup)

    def _compose_prompt(self, merged_prompt: str, task: str) -> str:
        """Compose the skills' prompt fragments with the concrete task.

        M1 / SEC-72 boundary note: the only inputs here are ``merged_prompt`` (the
        skills' authored ``prompt_fragment`` bodies, which are trusted admin-curated
        content) and ``task``. The spawner composes no untrusted recall / tool
        context of its own - untrusted spans are enveloped at their source (the chat
        transcript via continuity, the inbound message via chat, tool results in the
        Pi sidecar). ``task`` therefore arrives already enveloped on the chat path,
        or is the initiating principal's own instruction on the direct-spawn path, so
        it is NOT re-wrapped here (a second wrap would defang the inner envelopes)."""
        if merged_prompt:
            return f"{merged_prompt}\n\nTask:\n{task}"
        return f"Task:\n{task}"

    async def _audit_spawn(
        self,
        tenant_id: str,
        parent: InvocationContext,
        capability: AgentCapability,
        skills: list[str],
        run_id: str,
        *,
        status: str,
        tokens: int,
        cost: int,
    ) -> None:
        """Write the AGENT_SPAWN audit row (SEC-16); actor is the chosen capability."""
        await self._kernel.audit.write(
            AuditEvent(
                tenant_id=tenant_id,
                ts=utcnow(),
                run_id=run_id,
                parent_run_id=parent.run_id,
                actor=capability.name,
                actor_tier="ephemeral",
                depth=parent.depth + 1,
                action_type=ActionType.AGENT_SPAWN,
                status=status,
                tokens_used=tokens or None,
                cost_micros=cost or None,
                on_behalf_of=parent.on_behalf_of,
                skills_loaded=list(skills),
                detail={"capability": capability.name, "runtime": capability.runtime},
            )
        )


def context_payload(context: InvocationContext) -> dict[str, Any]:
    """The data a skill's ``context_requirements`` schema validates against.

    The invocation context's own envelope fields (tenant, run, depth, grants)
    plus the delegated human are exposed by name so a skill can require, e.g.,
    ``on_behalf_of`` to be present before it runs.
    """
    return {
        # arbitrary skill-context (epic_id, team_context, ...) provided at spawn,
        # overlaid by the envelope fields which are authoritative (S7.5).
        **dict(context.extra),
        "tenant_id": context.tenant_id,
        "run_id": context.run_id,
        "parent_run_id": context.parent_run_id,
        "depth": context.depth,
        "on_behalf_of": context.on_behalf_of,
        "actor": context.actor,
        "actor_tier": context.actor_tier,
        "skills_loaded": list(context.skills_loaded),
    }


def build_spawner(kernel: Kernel) -> Spawner:
    """Construct the fleet ``Spawner`` for a kernel (app bootstrap seam)."""
    return Spawner(kernel)


def make_app_spawner(
    kernel: Kernel,
) -> Callable[[Principal, SpawnBody], Awaitable[dict[str, Any]]]:
    """Adapt ``Spawner.spawn`` to the ``POST /v1/spawn`` (Principal, SpawnBody) seam.

    Errors are *not* converted: ContextRequirementsUnmet (400),
    DepthExceeded / BudgetExceeded (429), SkillNotFound / NoCapableRuntime (404)
    propagate so ``create_app``'s BoltrigError handler maps them to status codes.
    Budget here propagates (``partial_on_budget=False``) so an HTTP caller gets a
    429 rather than a silent partial.
    """
    spawner = build_spawner(kernel)

    _envelope = {"run_id", "parent_run_id", "depth", "skills_loaded"}

    async def app_spawner(principal: Principal, body: SpawnBody) -> dict[str, Any]:
        # everything in body.context that is not an envelope field is skill-context
        extra = {k: v for k, v in body.context.items() if k not in _envelope}
        ctx = principal.context(
            run_id=body.context.get("run_id"),
            parent_run_id=body.context.get("parent_run_id"),
            depth=int(body.context.get("depth", 0)),
            skills=body.context.get("skills_loaded", ()),
            extra=extra,
        )
        return await spawner.spawn(
            tenant_id=principal.tenant_id,
            task=body.task,
            skills=body.skills,
            prefer=body.prefer,
            context=ctx,
            partial_on_budget=False,
        )

    return app_spawner


def make_agent_invoker(kernel: Kernel) -> AgentInvoker:
    """Build the reasoning-verb invoker the kernel attaches (US-KER-02).

    For an agent-BOUND verb the dispatcher calls this with
    ``(verb, params, context, agent_capability)``. We run an appropriate
    ephemeral and return an adapter ``Result`` whose output is the run's
    ``AgentResult.output``. ScriptRuntime is the offline-safe fallback, and any
    runtime failure degrades to it so a verb call never crashes the kernel (P9).
    """
    spawner = build_spawner(kernel)

    async def agent_invoker(
        verb: str,
        params: dict[str, Any],
        context: InvocationContext,
        agent_capability: str,
    ) -> Result:
        from .runtime import ScriptRuntime

        prompt = (
            f"Verb: {verb}\n"
            f"Params: {json.dumps(params, default=str, sort_keys=True)}"
        )
        caps = await kernel.store.list_capabilities(context.tenant_id)
        cap = next((c for c in caps if c.name == agent_capability), None)
        try:
            if cap is None:
                runtime = ScriptRuntime()
            else:
                runtime = await spawner._runtime_for(context.tenant_id, cap, context)
            result = await runtime.run(
                prompt, context, tools=list(context.grants.allow)
            )
        except Exception:  # any backend failure -> deterministic offline fallback
            result = await ScriptRuntime().run(
                prompt, context, tools=list(context.grants.allow)
            )
        if result.ok:
            output = dict(result.output)
            if result.degraded:  # the flag survives the adapter seam (US-FLT-07)
                output.setdefault("_degraded", {"reason": "degraded"})
            return Result.success(output)
        return Result.failure(
            AdapterError(ErrorClass.INTERNAL, result.summary or "agent run failed")
        )

    return agent_invoker
