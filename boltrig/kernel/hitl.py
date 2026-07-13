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
        self, store: Store, resume_notifier: Callable[..., Any] | None = None
    ) -> None:
        self._store = store
        self._resume_notifier = resume_notifier

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
    ) -> HITLRequest:
        if type == HITLType.APPROVAL and not (
            verb and requested_by and request_fingerprint
        ):
            raise ValueError("approval requests must be action- and requester-bound")
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
            timeout_at=(
                utcnow() + timedelta(seconds=timeout_seconds) if timeout_seconds else None
            ),
        )
        await self._store.create_hitl_request(req)
        return req

    async def get(self, tenant_id: str, req_id: str) -> HITLRequest | None:
        return await self._store.get_hitl_request(tenant_id, req_id)

    async def list_pending(self, tenant_id: str) -> list[HITLRequest]:
        return await self._store.list_pending_hitl(tenant_id)

    async def answer(
        self, tenant_id: str, request_id: str, decision: str, respondent: str, notes: str = ""
    ) -> HITLResponse:
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
        durable resume itself is exactly-once via ``consume_if_approved``, so a
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
        does NOT consume). The dispatch gate uses ``consume_if_approved`` instead so
        an approval is single-use and verb-bound (SEC-14)."""
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
