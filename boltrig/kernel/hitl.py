"""Human-in-the-loop management (Epic K).

Creates and resolves approval / clarification / escalation requests. The kernel
gate (in ``dispatch``) creates an approval before a high-consequence verb runs
and refuses to proceed until it is answered with an approving decision
(SEC-14). The web Approvals panel is the canonical record (US-HIL-05); chat
adapters mirror it. Durable resume of paused runs is provided by Hatchet in the
fleet workers; this manager owns the request/response records and the gate, and
``answer`` fires an injected resume notifier (Beat 5, NFR-REL-03) so the fleet
can resume the paused run - the kernel never imports the fleet (P1).
"""

from __future__ import annotations

import hashlib
import hmac
import inspect
import json
import math
import unicodedata
import uuid
from datetime import timedelta
from typing import Any, Callable

from boltrig.models import (
    HITLStateConflict,
    HITLRequest,
    HITLResponse,
    HITLStatus,
    HITLType,
    Urgency,
    utcnow,
)
from boltrig.store import Store

# Decisions that count as approval for a gated verb.
_APPROVING = {"approve", "approved", "yes", "ok", "allow"}


def hitl_department_scope(context: Any) -> list[str] | None:
    """Extract the authenticated department scope carried by a principal context."""
    scope = context.extra.get("principal_scope")
    if not isinstance(scope, dict) or scope.get("all"):
        return None
    raw = scope.get("departments", [])
    if not isinstance(raw, (list, tuple, set)):
        return []
    return sorted({str(value) for value in raw if str(value)})


def hitl_scope_fields(context: Any) -> dict[str, Any]:
    """Return the authenticated visibility fields for a new HITL request."""
    return {
        "requested_on_behalf_of": context.on_behalf_of,
        "workspace_id": context.workspace_id,
        "department_scope": hitl_department_scope(context),
    }


def request_timed_out(req: HITLRequest) -> bool:
    """True when a still-PENDING request's timeout_at has passed (SEC-14).

    Only a pending request can expire; an answered one is already decided (the
    gate's ``consume_approved_by`` applies the timeout to the stale approval
    itself)."""
    return (
        req.status == HITLStatus.PENDING
        and req.timeout_at is not None
        and req.timeout_at <= utcnow()
    )


def _normalise_json(value: Any) -> Any:
    """Return a deterministic JSON value for approval request binding.

    HTTP params and adapter approval contexts are required to be JSON-like. NFC
    string normalisation prevents visually identical Unicode from producing
    different bindings; normalised-key collisions and non-finite numbers fail
    closed instead of being silently reinterpreted.
    """
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite number in approval context")
        return value
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, (list, tuple)):
        return [_normalise_json(item) for item in value]
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for raw_key, item in value.items():
            if not isinstance(raw_key, str):
                raise ValueError("non-string key in approval context")
            key = unicodedata.normalize("NFC", raw_key)
            if key in out:
                raise ValueError("normalised key collision in approval context")
            out[key] = _normalise_json(item)
        return out
    raise ValueError("non-JSON value in approval context")


def canonical_approval_value(value: Any) -> Any:
    """Return a detached canonical copy suitable for an adapter re-check."""
    return _normalise_json(value)


def approval_request_fingerprint(
    *, noun: str, verb: str, params: dict[str, Any], context: Any,
    resource_context: Any = None,
) -> str:
    """Bind one approval to one canonical action and authenticated initiator.

    The digest deliberately excludes transport provenance (IP/User-Agent), which
    may legitimately change while an approval is pending. It includes every
    authority-bearing identity field, grant/scope state, run/workspace and the
    optional adapter-provided snapshot of mutable resource state.
    """
    payload = {
        "version": 1,
        "tenant_id": context.tenant_id,
        "noun": noun,
        "verb": verb,
        "params": params,
        "initiator": {
            "actor": context.actor,
            "actor_tier": context.actor_tier,
            "on_behalf_of": context.on_behalf_of,
            "workspace_id": context.workspace_id,
            "run_id": context.run_id,
            "role": context.extra.get("principal_role"),
            "scope": context.extra.get("principal_scope"),
            "grants": {
                "allow": sorted(context.grants.allow),
                "deny": sorted(context.grants.deny),
            },
            "skills_loaded": sorted(context.skills_loaded),
        },
        "resource_context": resource_context,
    }
    canonical = json.dumps(
        _normalise_json(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


class HITLManager:
    def __init__(
        self,
        store: Store,
        resume_notifier: Callable[..., Any] | None = None,
        *,
        approval_timeout_seconds: int | None = None,
        development_posture: Any = None,
    ) -> None:
        self._store = store
        self._resume_notifier = resume_notifier
        # Manifest values threaded in at the composition root: the timeout the approval
        # gate stamps on each request, and the posture (dev_posture.py) eligibility reads.
        self.approval_timeout_seconds = approval_timeout_seconds
        self.development_posture = development_posture

    def set_resume_notifier(self, notifier: Callable[..., Any] | None) -> None:
        """Attach the answer -> resume bridge (NFR-REL-03): a callable (sync or
        async) fired with the answered :class:`HITLRequest`. Injected so the
        kernel never imports the fleet (P1); fired fail-safe (P9)."""
        self._resume_notifier = notifier

    async def create(
        self,
        tenant_id: str,
        run_id: str,
        type: HITLType,
        question: str,
        context: str = "",
        urgency: Urgency = Urgency.BLOCKING,
        options: list[str] | None = None,
        assignee: str | None = None,
        timeout_seconds: int | None = None,
        work_item_id: str | None = None,
        verb: str | None = None,
        requested_by: str | None = None,
        requested_on_behalf_of: str | None = None,
        request_fingerprint: str | None = None,
        workspace_id: str | None = None,
        department_scope: list[str] | None = None,
        secure: bool = False,
        secure_purpose: str | None = None,
    ) -> HITLRequest:
        if type == HITLType.APPROVAL and not (
            verb and requested_by and request_fingerprint
        ):
            raise ValueError("approval requests must be action- and requester-bound")
        # SEC-181: a secure QUESTION must carry its bounded purpose label (the
        # answer route seals the answer under it); a purpose without the secure
        # flag is meaningless and dropped rather than half-recorded.
        if secure and not secure_purpose:
            raise ValueError("a secure question requires a purpose label")
        req = HITLRequest(
            id=uuid.uuid4().hex,
            tenant_id=tenant_id,
            run_id=run_id,
            type=type,
            urgency=urgency,
            context=context,
            question=question,
            options=options or [],
            assignee=assignee,
            work_item_id=work_item_id,
            verb=verb,
            requested_by=requested_by,
            requested_on_behalf_of=requested_on_behalf_of,
            request_fingerprint=request_fingerprint,
            workspace_id=workspace_id,
            department_scope=(
                None
                if department_scope is None
                else sorted({str(value) for value in department_scope if str(value)})
            ),
            timeout_at=(
                utcnow() + timedelta(seconds=timeout_seconds) if timeout_seconds else None
            ),
            secure=bool(secure),
            secure_purpose=secure_purpose if secure else None,
        )
        await self._store.create_hitl_request(req)
        await self._notify_request(req)
        return req

    async def _notify_request(self, req: HITLRequest) -> None:
        """Best-effort channel notice to the humans who must act (SEC-179):
        enqueue to the subject's bound surface per their notification_prefs -
        and, for an APPROVAL, to every eligible approver
        (``enqueue_approval_fanout``: notice follows eligibility,
        [2026] VJS-CC-BOLTRIG-HITL-NOTIFICATION-ROUTING-001). Fail-safe (P9),
        mirroring _fire_resume: the recorded request is the truth; a notifier
        or eligibility fault never voids it - the subject notice stands even
        when the fan-out below faults."""
        subject = req.assignee or req.requested_on_behalf_of or req.requested_by
        event = "approval" if req.type == HITLType.APPROVAL else "escalation"
        try:
            from boltrig.kernel.channel_notify import (
                enqueue_approval_fanout,
                enqueue_user_notification,
            )

            if subject:
                await enqueue_user_notification(
                    self._store, req.tenant_id, subject, event, req.question
                )
            if req.type == HITLType.APPROVAL:
                await enqueue_approval_fanout(
                    self._store, req, exclude=subject, posture=self.development_posture)
        except Exception:  # noqa: BLE001 - delivery is a side channel
            pass

    async def get(self, tenant_id: str, req_id: str) -> HITLRequest | None:
        return await self._store.get_hitl_request(tenant_id, req_id)

    async def pending_event(
        self, context: Any, request_id: str, verb: str, call_id: str
    ) -> dict[str, Any]:
        """Project one bounded run-stream event from a canonical HITL request."""
        request = await self.get(context.tenant_id, request_id)
        event = {
            "type": "hitl",
            "verb": verb,
            "call_id": call_id,
            "hitl_request_id": request_id,
            "kind": request.type.value if request else "approval",
            "question": request.question if request else f"Approve {verb}?",
            "options": list(request.options) if request else ["approve", "reject"],
            "requested_by": request.requested_by if request else context.actor,
        }
        if request and request.secure:
            # SEC-181 marker (present only when secure, so the pause event's
            # shape is unchanged for every existing consumer): a secure-input
            # affordance may be rendered.
            event["secure"] = True
        return event

    async def list_pending(self, tenant_id: str) -> list[HITLRequest]:
        return await self._store.list_pending_hitl(tenant_id)

    async def answer(
        self, tenant_id: str, request_id: str, decision: str, respondent: str, notes: str = ""
    ) -> HITLResponse:
        req = await self._store.get_hitl_request(tenant_id, request_id)
        if req is not None and request_timed_out(req):
            # Lazy timeout enforcement (SEC-14): a request past its timeout_at is
            # expired on the spot and refuses the answer with a typed 409 - the
            # human's decision arrives too late to authorise anything.
            await self._store.expire_hitl(tenant_id, request_id)
            raise HITLStateConflict(
                f"HITL request '{request_id}' has timed out and cannot be answered"
            )
        resp = HITLResponse(
            id=uuid.uuid4().hex,
            request_id=request_id,
            tenant_id=tenant_id,
            decision=decision,
            respondent=respondent,
            responded_at=utcnow(),
            notes=notes,
        )
        answered = await self._store.answer_hitl(resp)
        if answered is None:
            raise HITLStateConflict(
                f"HITL request '{request_id}' is not pending and cannot be answered"
            )
        await self._fire_resume(tenant_id, request_id)
        return resp

    async def _fire_resume(self, tenant_id: str, request_id: str) -> None:
        """Fire the resume notifier with the answered request, fail-safe (P9):
        the recorded answer is the truth; a notifier fault never voids it. The
        durable resume itself is exactly-once via ``consume_approved_by``, so a
        duplicate or lost notification is safe (NFR-REL-03)."""
        if self._resume_notifier is None:
            return
        try:
            req = await self._store.get_hitl_request(tenant_id, request_id)
            if req is None:
                return
            out = self._resume_notifier(req)
            if inspect.isawaitable(out):
                await out
        except Exception:
            pass

    async def is_approved(self, tenant_id: str, request_id: str) -> bool:
        """True iff the request was answered with an approving decision (read-only;
        does NOT consume). The dispatch gate uses ``consume_approved_by``
        instead (via ``approval_gate.enforce_approval``) so an approval is
        single-use and verb-bound (SEC-14)."""
        req = await self._store.get_hitl_request(tenant_id, request_id)
        if req is None or req.status != HITLStatus.ANSWERED:
            return False
        resp = await self._store.get_hitl_response(tenant_id, request_id)
        return bool(resp and resp.decision.strip().lower() in _APPROVING)

    async def consume_approved_by(
        self, tenant_id: str, request_id: str, verb: str, request_fingerprint: str
    ) -> str | None:
        """Consume a valid approval and return its authenticated respondent.

        The respondent is part of the authorization evidence. Returning it only
        after the atomic ANSWERED -> CONSUMED transition lets downstream review
        gates attribute activation to the human who actually approved it instead
        of trusting a caller-supplied reviewer string.
        """
        req = await self._store.get_hitl_request(tenant_id, request_id)
        if req is None or req.status != HITLStatus.ANSWERED:
            return None
        if req.timeout_at is not None and req.timeout_at <= utcnow():
            # A stale approval can never execute (SEC-14): the human approved in
            # time, but the gated verb did not run before the request's deadline,
            # so the authorisation is void and the gate must re-pend.
            return None
        if (
            req.type != HITLType.APPROVAL
            or req.verb != verb
            or not req.request_fingerprint
            or not request_fingerprint
            or not hmac.compare_digest(req.request_fingerprint, request_fingerprint)
        ):
            return None
        resp = await self._store.get_hitl_response(tenant_id, request_id)
        if not (resp and resp.decision.strip().lower() in _APPROVING):
            return None
        consumed = await self._store.consume_hitl(tenant_id, request_id)
        return resp.respondent if consumed else None

    async def consume_if_approved(
        self, tenant_id: str, request_id: str, verb: str, request_fingerprint: str
    ) -> bool:
        """The gate's authorisation check (SEC-14). Returns True only if the request
        is a genuine, verb-bound APPROVAL that was answered with an approving
        decision and is not already spent - and atomically marks it CONSUMED so the
        same approval cannot authorise a second execution (single-use, anti-replay).

        H1 hardening: require ``type == APPROVAL`` and fail closed on a null verb.
        Escalation / clarification requests (which the fleet raises with
        ``verb=None`` and a non-human answer path) can no longer be laundered into
        authorisation by replaying their id as ``approval_id`` on a gated verb. A
        verb mismatch fails closed, so an approval for one verb never authorises
        another. dispatch always raises the gate's APPROVAL WITH a verb, so this is
        safe for every legitimate flow."""
        return (
            await self.consume_approved_by(
                tenant_id, request_id, verb, request_fingerprint
            )
            is not None
        )
