"""The dispatch chokepoint (P2, US-KER-01, K-1).

Every external action funnels through ``Dispatcher.invoke``. The order is fixed
and audited at the end regardless of outcome:

    resolve verb + binding   (BindingNotFound, fail-closed)
    validate params          (SchemaValidationError, SEC-21)
    grant check              (GrantMissing, SEC-07)
    idempotency replay       (SEC-15)
    consequence/HITL gate    (PendingHuman, SEC-14 - cannot be bypassed)
    rate limit               (RateLimited, FR-KER-05)
    resolve credential       (inside kernel only, SEC-05)
    execute adapter | agent  (degrade on UNAVAILABLE, P9)
    validate output          (SchemaValidationError)
    audit (always)           (SEC-16)
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from jsonschema import Draft202012Validator

from boltrig.adapters.base import Adapter, ErrorClass, Result
from boltrig.models import (
    ActionType,
    AuditEvent,
    BindingNotFound,
    Consequence,
    DegradedMode,
    GrantMissing,
    HITLType,
    InvocationContext,
    BoltrigError,
    PendingHuman,
    RateLimited,
    SchemaValidationError,
    SecurityEventType,
    TargetType,
    Verb,
    VerbBinding,
    utcnow,
)
from boltrig.store import Store

from .audit import AuditWriter
from .adapter_errors import adapter_failure
from .cost import CostAccountant
from .credentials import CredentialResolver
from .grants import GrantChecker
from .approval_gate import enforce_approval
from .hitl import HITLManager, hitl_scope_fields
from .idempotency import (
    IdempotencyCoordinator,
    IdempotencyReplay,
    IdempotencyRun,
    sensitive_key,
)
from .questions import QUESTIONS_VERB
from .ratelimit import RateLimiter

AdapterProvider = Callable[[str, str], Awaitable[Adapter | None]]
AgentInvoker = Callable[[str, dict[str, Any], InvocationContext, str], Awaitable[Result]]


def _validate(schema: dict[str, Any], instance: dict[str, Any]) -> list[str]:
    if not schema:
        return []
    validator = Draft202012Validator(schema)
    return [e.message for e in validator.iter_errors(instance)]


def _summarise_params(params: Any) -> dict[str, Any]:
    """A bounded, VALUE-FREE description of a verb's params for the chat stream
    (K-20 bounded observability): the sorted top-level KEY NAMES and their count,
    never the values (which can carry secrets or untrusted content). Mirrors the
    keys-only rule the audit rows follow."""
    if isinstance(params, dict):
        return {"keys": sorted(str(k) for k in params), "count": len(params)}
    return {"keys": [], "count": 0}


def _summarise_output(output: Any) -> dict[str, Any]:
    """A bounded, VALUE-FREE description of a verb's output (K-20): the output's
    top-level key names only, never the values."""
    if isinstance(output, dict):
        return {"keys": sorted(str(k) for k in output)}
    return {"keys": []}


def _event_safe(value: Any) -> Any:
    """Redact secret-shaped values before the internal run-event relay.

    The caller still receives the real adapter result. Durable/run-canvas event
    records do not need bearer material and must never become a second secret
    store (notably for one-time invitation tokens).
    """
    if isinstance(value, dict):
        safe: dict[str, Any] = {}
        for key, item in value.items():
            safe[str(key)] = "[redacted]" if sensitive_key(key) else _event_safe(item)
        return safe
    if isinstance(value, list):
        return [_event_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_event_safe(item) for item in value]
    return value


# Param keys that plausibly name the acted-on object's id (best-effort, D1). Only
# a short scalar is taken - never free text, never a secret-bearing value.
_RESOURCE_ID_KEYS = ("id", "resource_id", "target_id", "object_id", "item_id", "key")
_RESOURCE_ID_MAXLEN = 128


def _resource_ref(noun: str, params: Any) -> tuple[str | None, str | None]:
    """Best-effort (resource, resource_id) for the enriched audit row (D1). The
    resource is the noun (the object TYPE); the id is a short scalar id-like param
    when present, else None. Bounded + keys-only: an over-long or non-scalar value
    is dropped rather than folded into the row."""
    resource = noun or None
    if not isinstance(params, dict):
        return (resource, None)
    for key in _RESOURCE_ID_KEYS:
        val = params.get(key)
        if isinstance(val, (str, int)) and not isinstance(val, bool):
            sval = str(val)
            if 0 < len(sval) <= _RESOURCE_ID_MAXLEN:
                return (resource, sval)
    return (resource, None)


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
        security: Any | None = None,
    ) -> None:
        self._store = store
        self._idempotency = IdempotencyCoordinator(store)
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
        # Optional SecurityEvent stream ([2026] VJS-COUNTY 9, D3). A denied grant or
        # a throttle trip at THIS chokepoint is a security signal; recording it is
        # fail-safe (like the event relay) and never changes the dispatch outcome.
        self._security = security

    async def _record_security(
        self, event_type: SecurityEventType, reason: str, noun: str, verb: str,
        params: dict[str, Any], context: InvocationContext,
    ) -> None:
        """Record a security signal on the distinct stream (D3), at the same field
        depth as the audit row. Fail-safe: no writer wired, or a write error, must
        never break the dispatch path (the security event is observability)."""
        if self._security is None:
            return
        resource, resource_id = _resource_ref(noun, params)
        await self._security.record(
            context.tenant_id, event_type, reason,
            actor=context.actor, actor_tier=context.actor_tier,
            workspace_id=context.workspace_id,
            ip_address=context.ip_address, user_agent=context.user_agent,
            resource=resource, resource_id=resource_id,
            on_behalf_of=context.on_behalf_of,
            detail={"verb": verb},
        )

    def _emit(self, tenant_id: str, run_id: str | None, event: dict[str, Any]) -> None:
        """Publish a run event, fail-safe. Only when a relay is wired and the call
        belongs to a run; a publish error is swallowed so observability can never
        break the chokepoint."""
        if self._events is None or not run_id:
            return
        try:
            self._events.publish(tenant_id, run_id, event)
        except Exception:  # observability must never break dispatch (P9)
            pass

    async def _ask_user(self, params: dict[str, Any], context: InvocationContext) -> None:
        """Create a QUESTION HITL, emit a ``question`` run event, and pause the run
        (US-CHAT-12). Built entirely on the existing HITL machinery: the request is
        a ``HITLType.QUESTION`` bound to the run/work item, so the ordinary answer
        route + resume wiring carry it forward. Always raises PendingHuman.

        The ``prompt``/``choices`` are agent-authored model output (the question it
        is asking), so they may surface on the stream; the user's ANSWER is what is
        untrusted, and that enters the run via ``wrap_untrusted`` at the answer route.
        """
        prompt = str(params.get("prompt") or "")
        raw_choices = params.get("choices") or []
        choices = (
            [str(c) for c in raw_choices] if isinstance(raw_choices, list) else []
        )
        req = await self._hitl.create(
            tenant_id=context.tenant_id,
            run_id=context.run_id or "",
            type=HITLType.QUESTION,
            question=prompt,
            context=f"{context.actor} asks the user a question",
            options=choices,
            # a chat turn's work item id IS its run id, so binding the request to it
            # lets the ordinary resume wiring requeue the paused run on an answer.
            work_item_id=context.run_id, requested_by=context.actor,
            **hitl_scope_fields(context),
        )
        self._emit(context.tenant_id, context.run_id, {
            "type": "question", "run_id": context.run_id,
            "question_id": req.id, "prompt": prompt, "choices": choices,
        })
        raise PendingHuman(req.id)

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
        # _invoke_inner records the resolved adapter ref here so the audit row
        # attributes which adapter serviced the call (it was always None before).
        meta: dict[str, Any] = {}
        output: dict[str, Any] | None = None
        # A per-call id correlates the tool_call with its paired tool_result on the
        # stream so a client can pair a callout with its outcome (US-CHAT-10).
        call_id = uuid.uuid4().hex
        # Live run event: the agent is calling a tool. Keyed by the run so the chat
        # / run-canvas subscribed to it sees the call as it happens (Round Ten). The
        # redacted input rides for the run canvas + durable record (FR-EVT-01); the
        # chat stream forwards only the bounded ``tool``/``call_id``/``args_summary``
        # keys (K-20), never the raw input (see fleet/chat._project_chat_event).
        self._emit(context.tenant_id, context.run_id, {"type": "tool_call", "verb": verb, "noun": noun,
                                    "input": _event_safe(params), "run_id": context.run_id,
                                    "tool": verb, "call_id": call_id,
                                    "args_summary": _summarise_params(params)})
        try:
            output = await self._invoke_inner(
                noun, verb, params, context, idempotency_key, approval_id, meta
            )
            return output
        except PendingHuman as e:
            status = "pending_human"
            detail = {"hitl_request_id": e.hitl_request_id}
            # the call paused for a human - surface it on the run stream so the
            # inline approval card appears where the agent is working.
            self._emit(context.tenant_id, context.run_id, {"type": "hitl", "verb": verb,
                                        "call_id": call_id,
                                        "hitl_request_id": e.hitl_request_id})
            raise
        except DegradedMode:
            status = "degraded"
            raise
        except BoltrigError as e:
            status = e.reason
            detail = {"message": str(e)}
            # D3: a denied grant or a throttle trip at the chokepoint is a security
            # signal on the distinct stream, recorded at the SAME field-depth as the
            # audit row (actor / workspace / ip / ua). Fail-safe: never breaks the
            # call (the raise below is what governs the outcome).
            if isinstance(e, GrantMissing):
                await self._record_security(
                    SecurityEventType.PERMISSION_DENIED, "grant_missing",
                    noun, verb, params, context,
                )
            elif isinstance(e, RateLimited):
                await self._record_security(
                    SecurityEventType.RATE_LIMIT_TRIP, "rate_limited",
                    noun, verb, params, context,
                )
            raise
        except Exception as e:  # adapter/agent crash -> audited error, not a leak
            status = "error"
            detail = {"message": type(e).__name__}
            raise
        finally:
            # Paired result event (success -> redacted output; failure -> status
            # only). pending_human already emitted its own event above. The safe
            # output rides for the run canvas + the durable record (FR-EVT-01); the
            # chat stream forwards only the bounded ``call_id``/``status``/
            # ``result_summary`` keys (K-20), never the raw output.
            if status != "pending_human":
                self._emit(context.tenant_id, context.run_id, {
                    "type": "tool_result", "verb": verb, "status": status,
                    "output": _event_safe(output) if status == "ok" else None,
                    "run_id": context.run_id, "call_id": call_id,
                    "result_summary": (
                        _summarise_output(output) if status == "ok"
                        else {"status": status}
                    ),
                })
            latency_ms = int((time.monotonic() - started) * 1000)
            target_adapter = meta.get("target_adapter")
            resource, resource_id = _resource_ref(noun, params)
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
                    # Opbox-depth enrichment (D1). ip/ua ride on the context from the
                    # door (None off the HTTP path); workspace_id from the active
                    # workspace; resource/resource_id name the acted-on object.
                    ip_address=context.ip_address,
                    user_agent=context.user_agent,
                    resource=resource,
                    resource_id=resource_id,
                    workspace_id=context.workspace_id,
                )
            )

    async def _invoke_inner(
        self,
        noun: str,
        verb: str,
        params: dict[str, Any],
        context: InvocationContext,
        idempotency_key: str | None,
        approval_id: str | None,
        meta: dict[str, Any],
    ) -> dict[str, Any]:
        tenant = context.tenant_id

        # 1. resolve verb + binding (tenant-scoped; fail-closed)
        verb_def = await self._store.get_verb(tenant, verb)
        if verb_def is None:
            raise BindingNotFound(f"unknown verb '{verb}'")
        binding = await self._store.get_binding(tenant, verb)
        if binding is None:
            raise BindingNotFound(f"verb '{verb}' has no binding")
        # record which adapter/agent services this call so the audit can attribute it.
        meta["target_adapter"] = binding.target_ref

        # 2. validate params (SEC-21)
        errors = _validate(verb_def.input_schema, params)
        if errors:
            raise SchemaValidationError(f"invalid params for '{verb}'", errors)

        # 3. grant check (SEC-07)
        perms = await self._store.get_tenant_permissions(tenant)
        self._grants.check(context, verb, perms)

        # 4. atomically bind/claim the key after authorization. Completed results
        # replay before execution-side approval/rate-limit gates (SEC-15).
        idempotency = await self._idempotency.claim(
            idempotency_key, noun, verb, params, context, verb_def.idempotency_mode
        )
        if isinstance(idempotency, IdempotencyReplay):
            return idempotency.result
        run = idempotency if isinstance(idempotency, IdempotencyRun) else None

        # 5. consequence / HITL gate (SEC-14) - cannot be bypassed by an agent
        gated = verb_def.consequence == Consequence.HIGH or verb in self._blocking_verbs
        try:
            if gated:
                context = await enforce_approval(
                    self._hitl, self._adapter_provider, binding,
                    noun, verb, params, context, approval_id,
                )
            await self._rate.enforce(tenant, verb, binding.rate_limit)
        except Exception:
            await self._idempotency.release(run)
            raise

        await self._idempotency.start(run)

        # 6b. Governed built-in: the "ask the user a question" verb (US-CHAT-12).
        # It reached here only after passing schema validation + the grant check +
        # the HITL gate above, so it is fully governed like any verb. Its effect is
        # to PAUSE: it creates a QUESTION HITL, emits a ``question`` run event and
        # raises PendingHuman - it never touches an adapter/agent. Handled in-kernel
        # so it rides the ONE chokepoint and the EXISTING HITL machinery.
        if verb == QUESTIONS_VERB:
            await self._ask_user(params, context)

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

        # 9. complete atomically; secret-shaped output becomes uncacheable.
        await self._idempotency.complete(run, output)
        return output

    async def _execute_adapter(
        self,
        verb_def: Verb,
        binding: VerbBinding,
        params: dict[str, Any],
        context: InvocationContext,
    ) -> dict[str, Any]:
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
        raise adapter_failure(err)

    async def _execute_agent(
        self,
        verb_def: Verb,
        binding: VerbBinding,
        params: dict[str, Any],
        context: InvocationContext,
    ) -> dict[str, Any]:
        if self._agent_invoker is None:
            return self._degrade_or_fail(verb_def, reason="agent_runtime_absent")
        result = await self._agent_invoker(verb_def.id, params, context, binding.target_ref)
        if result.ok:
            return result.output
        return self._degrade_or_fail(verb_def, reason="agent_failed")

    def _degrade_or_fail(self, verb_def: Verb, reason: str) -> dict[str, Any]:
        """Produce a degraded result if the verb defines one, else fail (P9)."""
        dm = verb_def.degraded_mode
        if not dm:
            raise BoltrigError(f"verb '{verb_def.id}' unavailable ({reason})")
        output = dict(dm.get("output", {}))
        output["_degraded"] = {"reason": reason, "strategy": dm.get("strategy", "deferred")}
        raise DegradedMode(output=output, deferred=True)
