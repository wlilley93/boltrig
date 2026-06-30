"""The dispatch chokepoint (P2, US-KER-01, K-1).

Every external action funnels through ``Dispatcher.invoke``. The order is fixed
and audited at the end regardless of outcome:

    resolve verb + binding   (BindingNotFound, fail-closed)
    validate params          (SchemaValidationError, SEC-21)
    grant check              (GrantMissing, SEC-07)
    consequence/HITL gate    (PendingHuman, SEC-14 - cannot be bypassed)
    rate limit               (RateLimited, FR-KER-05)
    idempotency replay       (NFR-REL-02)
    resolve credential       (inside kernel only, SEC-05)
    execute adapter | agent  (degrade on UNAVAILABLE, P9)
    validate output          (SchemaValidationError)
    audit (always)           (SEC-16)
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any

from jsonschema import Draft202012Validator

from nankle.adapters.base import Adapter, ErrorClass, Result
from nankle.models import (
    ActionType,
    AuditEvent,
    BindingNotFound,
    Consequence,
    DegradedMode,
    HITLType,
    InvocationContext,
    NankleError,
    PendingHuman,
    RateLimited,
    SchemaValidationError,
    TargetType,
    utcnow,
)
from nankle.store import Store

from .audit import AuditWriter
from .cost import CostAccountant
from .credentials import CredentialResolver
from .grants import GrantChecker
from .hitl import HITLManager
from .ratelimit import RateLimiter

AdapterProvider = Callable[[str, str], Awaitable[Adapter | None]]
AgentInvoker = Callable[[str, dict, InvocationContext, str], Awaitable[Result]]


def _validate(schema: dict, instance: dict) -> list[str]:
    if not schema:
        return []
    validator = Draft202012Validator(schema)
    return [e.message for e in validator.iter_errors(instance)]


class Dispatcher:
    def __init__(
        self,
        store: Store,
        *,
        grants: GrantChecker,
        rate_limiter: RateLimiter,
        credentials: CredentialResolver,
        audit: AuditWriter,
        hitl: HITLManager,
        cost: CostAccountant,
        adapter_provider: AdapterProvider,
        agent_invoker: AgentInvoker | None = None,
        blocking_verbs: set[str] | None = None,
        events: Any | None = None,
    ) -> None:
        self._store = store
        self._grants = grants
        self._rate = rate_limiter
        self._creds = credentials
        self._audit = audit
        self._hitl = hitl
        self._cost = cost
        self._adapter_provider = adapter_provider
        self._agent_invoker = agent_invoker
        self._blocking_verbs = blocking_verbs or set()
        # Optional run-event relay (Round Ten). Emitting run events is a pure
        # observability side-channel - like audit, it never affects the dispatch
        # decision and a relay failure never breaks a call (P9).
        self._events = events

    def _emit(self, run_id: str | None, event: dict[str, Any]) -> None:
        """Publish a run event, fail-safe. Only when a relay is wired and the call
        belongs to a run; a publish error is swallowed so observability can never
        break the chokepoint."""
        if self._events is None or not run_id:
            return
        try:
            self._events.publish(run_id, event)
        except Exception:  # observability must never break dispatch (P9)
            pass

    async def invoke(
        self,
        noun: str,
        verb: str,
        params: dict[str, Any],
        context: InvocationContext,
        *,
        idempotency_key: str | None = None,
        approval_id: str | None = None,
    ) -> dict[str, Any]:
        started = time.monotonic()
        status = "ok"
        target_adapter: str | None = None
        detail: dict[str, Any] = {}
        output: dict[str, Any] | None = None
        # Live run event: the agent is calling a tool. Keyed by the run so the chat
        # / run-canvas subscribed to it sees the call as it happens (Round Ten).
        self._emit(context.run_id, {"type": "tool_call", "verb": verb, "noun": noun,
                                    "input": params})
        try:
            output = await self._invoke_inner(
                noun, verb, params, context, idempotency_key, approval_id
            )
            return output
        except PendingHuman as e:
            status = "pending_human"
            detail = {"hitl_request_id": e.hitl_request_id}
            # the call paused for a human - surface it on the run stream so the
            # inline approval card appears where the agent is working.
            self._emit(context.run_id, {"type": "hitl", "verb": verb,
                                        "hitl_request_id": e.hitl_request_id})
            raise
        except DegradedMode:
            status = "degraded"
            raise
        except NankleError as e:
            status = e.reason
            detail = {"message": str(e)}
            raise
        except Exception as e:  # adapter/agent crash -> audited error, not a leak
            status = "error"
            detail = {"message": type(e).__name__}
            raise
        finally:
            # Paired result event (success -> output; failure -> status only, no
            # leak). pending_human already emitted its own event above.
            if status != "pending_human":
                self._emit(context.run_id, {"type": "tool_result", "verb": verb,
                                            "status": status,
                                            "output": output if status == "ok" else None})
            latency_ms = int((time.monotonic() - started) * 1000)
            await self._audit.write(
                AuditEvent(
                    tenant_id=context.tenant_id,
                    ts=utcnow(),
                    run_id=context.run_id,
                    parent_run_id=context.parent_run_id,
                    actor=context.actor,
                    actor_tier=context.actor_tier,
                    depth=context.depth,
                    action_type=ActionType.TOOL_CALL,
                    noun=noun,
                    verb=verb,
                    target_adapter=target_adapter,
                    on_behalf_of=context.on_behalf_of,
                    status=status,
                    latency_ms=latency_ms,
                    skills_loaded=list(context.skills_loaded),
                    detail=detail,
                )
            )

    async def _invoke_inner(self, noun, verb, params, context, idempotency_key, approval_id):
        tenant = context.tenant_id

        # 1. resolve verb + binding (tenant-scoped; fail-closed)
        verb_def = await self._store.get_verb(tenant, verb)
        if verb_def is None:
            raise BindingNotFound(f"unknown verb '{verb}'")
        binding = await self._store.get_binding(tenant, verb)
        if binding is None:
            raise BindingNotFound(f"verb '{verb}' has no binding")

        # 2. validate params (SEC-21)
        errors = _validate(verb_def.input_schema, params)
        if errors:
            raise SchemaValidationError(f"invalid params for '{verb}'", errors)

        # 3. grant check (SEC-07)
        perms = await self._store.get_tenant_permissions(tenant)
        self._grants.check(context, verb, perms)

        # 4. consequence / HITL gate (SEC-14) - cannot be bypassed by an agent
        gated = verb_def.consequence == Consequence.HIGH or verb in self._blocking_verbs
        if gated:
            approved = bool(
                approval_id and await self._hitl.is_approved(tenant, approval_id)
            )
            if not approved:
                req = await self._hitl.create(
                    tenant_id=tenant,
                    run_id=context.run_id or "",
                    type=HITLType.APPROVAL,
                    question=f"Approve {verb} ?",
                    context=f"{context.actor} requests {verb}",
                    options=["approve", "reject"],
                )
                raise PendingHuman(req.id)

        # 5. rate limit (FR-KER-05)
        await self._rate.enforce(tenant, verb, binding.rate_limit)

        # 6. idempotency replay (NFR-REL-02, SEC-15)
        if idempotency_key:
            prior = await self._store.idempotency_get(tenant, idempotency_key)
            if prior is not None:
                return prior

        # 7. execute
        if binding.target_type == TargetType.ADAPTER:
            output = await self._execute_adapter(verb_def, binding, params, context)
        elif binding.target_type == TargetType.AGENT:
            output = await self._execute_agent(verb_def, binding, params, context)
        else:  # fail-closed on an unknown target type
            raise BindingNotFound(f"unknown target_type '{binding.target_type}'")

        # 8. validate output
        out_errors = _validate(verb_def.output_schema, output)
        if out_errors:
            raise SchemaValidationError(f"invalid output for '{verb}'", out_errors)

        # 9. record idempotent result
        if idempotency_key:
            await self._store.idempotency_put(tenant, idempotency_key, output)
        return output

    async def _execute_adapter(self, verb_def, binding, params, context) -> dict:
        adapter = await self._adapter_provider(context.tenant_id, binding.target_ref)
        if adapter is None:
            return self._degrade_or_fail(verb_def, reason="adapter_not_loaded")
        credential = await self._creds.resolve_for_adapter(
            context.tenant_id, binding.target_ref
        )
        result: Result = await adapter.execute(verb_def.id, params, credential, context)
        if result.ok:
            return result.output
        err = result.error
        if err and err.error_class == ErrorClass.RATE_LIMITED:
            raise RateLimited(err.message, err.retry_after_seconds)
        if err and err.error_class == ErrorClass.UNAVAILABLE:
            return self._degrade_or_fail(verb_def, reason="backend_unavailable")
        raise NankleError(err.message if err else "adapter error")

    async def _execute_agent(self, verb_def, binding, params, context) -> dict:
        if self._agent_invoker is None:
            return self._degrade_or_fail(verb_def, reason="agent_runtime_absent")
        result = await self._agent_invoker(verb_def.id, params, context, binding.target_ref)
        if result.ok:
            return result.output
        return self._degrade_or_fail(verb_def, reason="agent_failed")

    def _degrade_or_fail(self, verb_def, reason: str) -> dict:
        """Produce a degraded result if the verb defines one, else fail (P9)."""
        dm = verb_def.degraded_mode
        if not dm:
            raise NankleError(f"verb '{verb_def.id}' unavailable ({reason})")
        output = dict(dm.get("output", {}))
        output["_degraded"] = {"reason": reason, "strategy": dm.get("strategy", "deferred")}
        raise DegradedMode(output=output, deferred=True)
