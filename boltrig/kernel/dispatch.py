"""The dispatch chokepoint (P2, US-KER-01, K-1).

Every external action funnels through ``Dispatcher.invoke``. The order is fixed
and audited at the end regardless of outcome:

    resolve verb + binding   (BindingNotFound, fail-closed)
    validate params          (SchemaValidationError, SEC-21)
    grant check              (GrantMissing, SEC-07)
    idempotency replay       (SEC-15)
    consequence/HITL gate    (PendingHuman, SEC-14 - cannot be bypassed)
    rate limit               (RateLimited, FR-KER-05 - runs AHEAD of the gate on
                              the leg that spends an approval, so a throttle trip
                              never burns a human authorisation)
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
from .approval_posture import posture_requires_approval
from .schema_diagnosis import (
    MAX_SCHEMA_ERRORS,
    MAX_SCHEMA_PATH_DEPTH,
    MAX_SCHEMA_PATH_SEGMENT,
    SCHEMA_KEYWORDS,
    caller_hints,
    schema_digest,
)
from .credentials import CredentialResolver
from .grants import GrantChecker
from .approval_gate import enforce_approval
from .held_call import record_held_call
from .hitl import HITLManager, hitl_scope_fields
from .idempotency import (
    IdempotencyCoordinator,
    IdempotencyReplay,
    IdempotencyRun,
)
from .questions import QUESTIONS_VERB
from .run_event_projection import (
    _event_safe,
    _summarise_output,
    _summarise_params,
)
from .ratelimit import RateLimiter

AdapterProvider = Callable[[str, str], Awaitable[Adapter | None]]
AgentInvoker = Callable[[str, dict[str, Any], InvocationContext, str], Awaitable[Result]]


def _validate(schema: dict[str, Any], instance: dict[str, Any]) -> list[dict[str, Any]]:
    """Validate, and return findings whose provenance is WHOLLY THE SCHEMA AND NAME-ONLY.

    Two fields, and the choice of exactly these two is the holding of the schema-validation
    ledger order. See kernel/schema_diagnosis.py for the rule and for why the near misses
    were refused:

      * ``schema_path`` is ``absolute_schema_path``: a path through the SCHEMA, made of
        schema keywords and property NAMES. It carries no instance value and no schema value.
      * ``keyword`` is ``validator``, checked against the allowlist.

    Refused, and both look safe: ``json_path`` / ``absolute_path`` are derived from the
    INSTANCE (under ``additionalProperties`` an instance key IS a path segment, so a secret
    used as a key lands in the path verbatim), and ``validator_value`` is schema-derived and
    still a VALUE (for ``const`` it is the literal expected). ``message`` embeds the instance
    directly and was never a candidate.
    """
    if not schema:
        return []
    validator = Draft202012Validator(schema)
    findings: list[dict[str, Any]] = []
    for e in validator.iter_errors(instance):
        if len(findings) >= MAX_SCHEMA_ERRORS:
            break
        path = [
            str(seg)[:MAX_SCHEMA_PATH_SEGMENT]
            for seg in list(e.absolute_schema_path)[:MAX_SCHEMA_PATH_DEPTH]
        ]
        findings.append({
            "schema_path": path,
            "keyword": e.validator if e.validator in SCHEMA_KEYWORDS else "unknown",
        })
    return findings


def _schema_detail(e: BoltrigError) -> dict[str, Any]:
    """The extra audit fields a schema failure contributes, and {} for every other error.

    A function rather than a branch at the call site, so the failure taxonomy can grow another
    detail-bearing member without the chokepoint's one error handler growing with it.
    """
    return e.audit_detail() if isinstance(e, SchemaValidationError) else {}


def _reject_if_invalid(
    kind: str, verb: str, schema: dict[str, Any] | None, instance: Any
) -> None:
    """Validate and raise, with the schema digest attached. ONE seam for input and output.

    Two call sites that each built their own error were how the output twin came to be
    forgotten in the first place: the filing that produced the schema-validation ledger order
    described the input path only, and an order fixing just that would have left the half
    whose instance is the adapter's response.
    """
    errors = _validate(schema or {}, instance)
    if errors:
        raise SchemaValidationError(
            f"invalid {kind} for '{verb}'", errors,
            schema_digest=schema_digest(schema),
            # Derived in schema_diagnosis, NOT here: this module is on the audit
            # path and is under a module-wide ban on instance-derived reads, so
            # the caller's hint is built where it cannot contaminate a row.
            hints=caller_hints(schema or {}, errors),
        )


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

    async def _emit_pause(
        self, context: Any, hitl_request_id: str, verb: str, call_id: str
    ) -> None:
        """Publish a HITL pause to this run AND to the run that delegated to it.

        A pause has to reach the person who asked for the thing being paused. A chat
        turn never calls a verb itself: it spawns a worker whose cell reaches back
        through the MCP face, so the dispatch runs under the CHILD run id while the
        chat client follows the ROOT stream. Publishing only to ``context.run_id``
        put the pause on a stream nobody follows - the turn simply ended and the user
        was told, in prose, that something was "pending human approval", with nothing
        to approve. Mirrors how a delegation's subagent/subagent_end frames are
        published to the parent relay.
        """
        event = await self._hitl.pending_event(context, hitl_request_id, verb, call_id)
        self._emit_run_and_parent(context, event)

    async def _hold_pause(
        self,
        context: InvocationContext,
        exc: PendingHuman,
        noun: str,
        verb: str,
        params: dict[str, Any],
        call_id: str,
    ) -> None:
        """Announce the pause AND make it durable (decision 0018, Order 2).

        The announcement alone was the whole of it, and that is how a human could
        approve a write that then never happened: the approval was recorded and
        nothing anywhere held the CALL, so nothing could replay it. The record
        written here - a ``held:`` checkpoint on the root run plus the sealed
        canonical call - is what the answer bridge replays under the SAME run
        identity, which is what makes the approval fingerprint match and the
        ANSWERED -> CONSUMED CAS the only thing that decides exactly-once.

        Unlike the event emit above, a failure here is NOT swallowed: the relay is
        observability, this is the record the approved write is replayed from.

        Only an APPROVAL is held. The other pause raised here is the ask-user
        QUESTION, which has no held WRITE to replay - re-invoking it would simply
        ask again - and sealing its params would put a plain question's inputs
        under a secret kind for no one to redeem (SEC-181).
        """
        await self._emit_pause(context, exc.hitl_request_id, verb, call_id)
        request = await self._hitl.get(context.tenant_id, exc.hitl_request_id)
        if request is None or request.type != HITLType.APPROVAL:
            return
        await record_held_call(
            self._store, context,
            noun=noun, verb=verb, params=params,
            request_id=exc.hitl_request_id, call_id=call_id,
        )

    def _emit_run_and_parent(self, context: Any, event: dict[str, Any]) -> None:
        """Publish to THIS run and to the run that delegated to it.

        A chat turn never calls a verb itself: it spawns a worker whose cell reaches
        back through the MCP face, so dispatch runs under the CHILD run id while the
        chat client follows the ROOT stream. ``_emit_pause`` already fanned out for
        this reason; ``tool_call``/``tool_result`` did not, so on a live tenant the
        browser rendered a correct tool-backed answer showing NO tool call and NO
        context while audit_log held the call.
        """
        self._emit(context.tenant_id, context.run_id, event)
        parent = getattr(context, "parent_run_id", None)
        if parent and parent != context.run_id:
            self._emit(context.tenant_id, parent, event)

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
        # SEC-181 secure input: the QUESTION is marked secure with its bounded
        # purpose label so the answer route seals the answer as a run/purpose-
        # scoped credential reference (the value never enters the run) and
        # consumers can render a secure-input affordance. The prompt/choices
        # themselves stay ordinary text.
        secure = params.get("secure") is True
        purpose = str(params.get("purpose") or "") if secure else ""
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
            secure=secure, secure_purpose=purpose or None,
            **hitl_scope_fields(context),
        )
        event: dict[str, Any] = {
            "type": "question", "run_id": context.run_id,
            "question_id": req.id, "prompt": prompt, "choices": choices,
        }
        if secure:
            # SEC-181 marker (present only when secure, so the event shape is
            # unchanged otherwise); the purpose label is a bounded non-secret.
            event["secure"] = True
            event["purpose"] = purpose
        self._emit(context.tenant_id, context.run_id, event)
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
        self._emit_run_and_parent(context, {"type": "tool_call", "verb": verb, "noun": noun,
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
            # Announce the pause, and RECORD it so the approved call can be replayed.
            await self._hold_pause(context, e, noun, verb, params, call_id)
            raise
        except DegradedMode:
            status = "degraded"
            raise
        except BoltrigError as e:
            status = e.reason
            detail = {"message": str(e), **_schema_detail(e)}
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
                self._emit_run_and_parent(context, {
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
            detail.setdefault("params", _summarise_params(params))   # D1, schema-ledger order
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
        _reject_if_invalid("params", verb, verb_def.input_schema, params)

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

        gated = verb in self._blocking_verbs or await posture_requires_approval(
            self._store, verb, verb_def, binding, context
        )
        # 6. rate limit (FR-KER-05). The gate SPENDS the approval it is handed
        # (atomic ANSWERED -> CONSUMED, single-use) and nothing can hand it back,
        # so on the leg that carries one the throttle must decide FIRST: a
        # RateLimited raised after the consume burns a human authorisation for a
        # call the adapter provably never saw, and the retry that retry_after
        # invites is then met with "its invocation already ran".
        #
        # The name is CARRIES, not spends. A stale, unanswered or bogus approval_id
        # takes this branch too, and enforce_approval then re-pends it - so such a
        # call now costs a rate token while only pending for a human. That is the
        # accepted trade, stated rather than glossed: an approval id is single-use
        # and unrecoverable, a rate token refills within the minute, and nothing
        # can tell the two apart until the gate has already spent one.
        #
        # This does NOT make the whole pre-execution path approval-safe, and the
        # invariant is worded to match: _idempotency.start (IdempotencyConflict), a
        # missing adapter (DegradedMode) and run-scoped credential resolution
        # (CredentialResolution) all still raise after the consume. Only the
        # rate-limit gate moves.
        carries_approval = gated and approval_id is not None
        try:
            if carries_approval:
                await self._rate.enforce(tenant, verb, binding.rate_limit)
            if gated:
                context = await enforce_approval(
                    self._hitl, self._adapter_provider, binding,
                    noun, verb, params, context, approval_id, store=self._store,
                )
            if not carries_approval:
                await self._rate.enforce(tenant, verb, binding.rate_limit)
        except Exception:
            await self._idempotency.release(run)
            raise

        await self._idempotency.start(run)

        # The author-tier count before the call, for the 1<->2 crossing row
        # (D3). See _announce_author_crossing for why it is measured here.
        authors_before = (
            await self._active_author_count(tenant) if verb.startswith("control.") else None
        )

        # Everything from here to ``complete`` runs with the key IN_PROGRESS: any
        # raise (the pausing ask-user verb, a definitive adapter failure, an
        # invalid output) must release the claim like the gate above, never park
        # it until lease expiry.
        try:
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
            # The OUTPUT twin, through the SAME seam. The case file did not mention output
            # validation and it is the worse half: the instance here is the adapter's
            # RESPONSE, which is where credentials live.
            _reject_if_invalid("output", verb, verb_def.output_schema, output)
        except Exception:
            await self._idempotency.release(run)
            raise

        # 9. complete atomically; secret-shaped output becomes uncacheable.
        await self._idempotency.complete(run, output)
        if authors_before is not None:
            await self._announce_author_crossing(verb, noun, context, authors_before)
        return output

    async def _active_author_count(self, tenant_id: str) -> int:
        """Active users whose role is author-tier - the number the exemption reads."""
        from boltrig.identity.rbac import AUTHOR_ROLES

        users = await self._store.list_users(tenant_id)
        return sum(
            1
            for u in users
            if getattr(u, "status", None) == "active"
            and getattr(u, "role", None) in AUTHOR_ROLES
        )

    async def _announce_author_crossing(
        self, verb: str, noun: str, context: InvocationContext, before: int
    ) -> None:
        """Announce a crossing of the 1<->2 author boundary
        ([2026] VJS-CC-BOLTRIG-OPERATOR-SEAT-001, D3).

        At exactly one active author-tier user the sole-author bootstrap
        exemption is live and self-approval is lawful; at two it is not. So that
        count is not a detail of the user record, it is the tenant's approval
        REGIME - and on Classical Visas it changed without a word: the
        `control.user.update` promoting the client to `admin` was itself the
        last act self-approved under the exemption, and destroyed the exemption
        on its way through. The operator discovered the regime had changed only
        by hitting the deadlock it created, and applied to open the host
        boundary to escape it.

        Measured at the dispatch chokepoint, which both agent and route calls
        pass, and measured by COUNTING rather than by knowing which verbs touch
        users: a list of user-mutating verbs has to be maintained, and the
        crossing that matters is the one made by the verb nobody thought of,
        including verbs not yet written. D2 forbids the downward crossing via a
        control verb; this records whichever ones still occur.

        Written ONLY on an actual crossing. A row per control verb would bury
        the few that matter under hundreds that do not, and a reader who has to
        filter is a reader who stops looking. Silent on 2->3 and on any change
        that leaves the count where it was.
        """
        after = await self._active_author_count(context.tenant_id)
        if before == after or min(before, after) > 1:
            return
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
                verb="control.author_tier.crossing",
                status="ok",
                on_behalf_of=context.on_behalf_of,
                detail={
                    "verb": verb,
                    "active_authors_before": before,
                    "active_authors_after": after,
                    # At one, self-approval is lawful; at two it is not. Spelled
                    # out so the row does not require the reader to know that.
                    "sole_author_exemption_after": after == 1,
                },
            )
        )

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
        # Permission-parity passthrough: when the chat turn sealed a per-run bearer
        # for THIS adapter (keyed by run id + target_ref), it overrides the static
        # service credential for this call so the downstream service enforces the
        # CALLER's grants (min(agent,user)-clamped), not the adapter's own token.
        # Adapter-scoped and run-scoped by construction; absent => static fallback
        # (dev / non-passthrough tenants are unchanged). Kernel-only: the bearer is
        # minted straight into the credential arg, never into params/events/audit.
        override = await self._creds.resolve_run_scoped_credential(
            context.tenant_id, context.run_id, binding.target_ref, context.on_behalf_of
        )
        if override is not None:
            credential = override
        # SEC-181: at this same resolve-credential stage, a param carrying a
        # run-scoped credential REFERENCE (a secure ask_user answer) is resolved
        # to its material INSIDE the kernel - the adapter receives the material
        # on a resolved copy; the params the agent authored, the events and the
        # audit only ever held the reference. Scoped: another run's or purpose's
        # reference fails closed (CredentialResolution).
        resolved_params = await self._creds.resolve_run_scoped_params(
            context.tenant_id, params, run_id=context.run_id, owner=context.on_behalf_of
        )
        result: Result = await adapter.execute(verb_def.id, resolved_params, credential, context)
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
