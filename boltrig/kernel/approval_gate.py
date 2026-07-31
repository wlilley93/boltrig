"""Exact-request approval gate shared by the dispatch chokepoint."""

from __future__ import annotations

import inspect
import json
from collections.abc import Awaitable, Callable
from dataclasses import replace
from typing import Any

from boltrig.adapters.base import Adapter
from boltrig.models import (
    ApprovalNotHoldable,
    BoltrigError,
    HITLStateConflict,
    HITLStatus,
    HITLType,
    InvocationContext,
    PendingHuman,
    TargetType,
    VerbBinding,
)

from .held_call import name_redeemer
from .approval_digest import approval_action_digest
from .hitl import (
    HITLManager,
    approval_request_fingerprint,
    canonical_approval_value,
    hitl_scope_fields,
)
from .idempotency import secret_shaped, sensitive_key

AdapterProvider = Callable[[str, str], Awaitable[Adapter | None]]


def _approval_display_value(value: Any) -> Any:
    """Return approval context that is faithful but never a secret store."""
    if isinstance(value, dict):
        return {
            str(key): (
                "[redacted]"
                if sensitive_key(key)
                else _approval_display_value(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_approval_display_value(item) for item in value]
    return "[redacted]" if secret_shaped(value) else value


def _approval_display_inputs(verb: str, params: dict[str, Any]) -> Any:
    canonical = canonical_approval_value(params)
    if verb != "control.mcp_server.update":
        return _approval_display_value(canonical)
    # The exact raw parameters remain in the approval fingerprint and action
    # digest, but endpoint paths and credential references are not approver
    # display material. The resource context carries the safe requested view.
    return {
        "server_id": str(params.get("server_id") or ""),
        "configuration": "[redacted; see requested_config]",
    }


def _approval_display_context(
    *, verb: str, params: dict[str, Any], context: InvocationContext,
    resource_context: Any,
) -> str:
    """Serialise the exact governed action for the authorised approver."""
    payload = {
        "version": 1,
        "requested_by": context.actor,
        "requested_on_behalf_of": context.on_behalf_of,
        "verb": verb,
        "inputs": _approval_display_inputs(verb, params),
    }
    if resource_context is not None:
        payload["resource_context"] = _approval_display_value(resource_context)
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


# A reserved key an adapter's ``approval_context`` may set to state, in one
# sentence, something the approver MUST be told before they approve - not merely
# something the card may render. The gate lifts it into the request QUESTION,
# which is the field ``HITLManager._notify_request`` sends to every eligible
# approver, so a disclosure set here reaches the request row, the notification and
# the card rather than only the card.
#
# It exists for [2026] VJS-CC-BOLTRIG-DEV-EGRESS-LOOPBACK-001 C3: where a posture
# makes an approval mean something other than what the approver is being asked to
# approve, the narrowing must be disclosed AT THE POINT OF APPROVAL, in the
# approval itself. The key stays in the resource context as well as the question,
# so it is part of the approval FINGERPRINT: an approval given on one description
# cannot be redeemed for an action described differently.
APPROVAL_NOTICE_KEY = "approval_notice"


def _approval_question(verb: str, resource_context: Any) -> str:
    notice = (
        str(resource_context.get(APPROVAL_NOTICE_KEY) or "").strip()
        if isinstance(resource_context, dict)
        else ""
    )
    return f"Approve {verb}? {notice}".rstrip() if notice else f"Approve {verb}?"


async def _resource_context(
    provider: AdapterProvider,
    binding: VerbBinding,
    verb: str,
    params: dict[str, Any],
    context: InvocationContext,
) -> Any:
    if binding.target_type != TargetType.ADAPTER:
        return None
    adapter = await provider(context.tenant_id, binding.target_ref)
    hook = getattr(adapter, "approval_context", None) if adapter else None
    if hook is None:
        return None
    value = hook(verb, params, context)
    return await value if inspect.isawaitable(value) else value


async def _require_redeemer(store: Any, verb: str, context: InvocationContext) -> None:
    """Refuse to MINT an approval no lane could ever redeem (decision 0018, Order 5).

    The ground truth this exists for: a human approved ``opbox.add_comment`` inside
    a chat turn at 11:41:52, the request sat ANSWERED forever, and the comment was
    never posted - the instrument was minted on a lane with no claimant. The gate
    that mints must be able to NAME the redeemer from the record
    (``held_call.name_redeemer``), so the unclaimable state is structurally
    impossible rather than fixed once. Nothing is created on refusal: no request
    row, no seal, no checkpoint.
    """
    if await name_redeemer(store, context) is None:
        raise ApprovalNotHoldable(
            f"'{verb}' is high-consequence and this run cannot hold an approval: "
            "nothing here could redeem it, so none was created",
            verb,
        )


async def enforce_approval(
    hitl: HITLManager,
    provider: AdapterProvider,
    binding: VerbBinding,
    noun: str,
    verb: str,
    params: dict[str, Any],
    context: InvocationContext,
    approval_id: str | None,
    *,
    store: Any = None,
) -> InvocationContext:
    """Return an approval-stamped context or raise a newly bound pause."""
    try:
        resource = canonical_approval_value(
            await _resource_context(provider, binding, verb, params, context)
        )
        fingerprint = approval_request_fingerprint(
            noun=noun,
            verb=verb,
            params=params,
            context=context,
            resource_context=resource,
        )
        display_context = _approval_display_context(
            verb=verb,
            params=params,
            context=context,
            resource_context=resource,
        )
    except (TypeError, ValueError) as exc:
        raise BoltrigError("approval context is not canonical JSON") from exc
    approved_by = (
        await hitl.consume_approved_by(
            context.tenant_id, approval_id, verb, fingerprint
        )
        if approval_id
        else None
    )
    if not approved_by:
        if approval_id is not None:
            spent = await hitl.get(context.tenant_id, approval_id)
            if spent is not None and spent.status == HITLStatus.CONSUMED:
                # A spent approval must never silently re-pend; this invocation
                # already ran, so the caller must inspect its resource state.
                raise HITLStateConflict(
                    f"approval '{approval_id}' was already consumed; "
                    "its invocation already ran"
                )
        await _require_redeemer(store, verb, context)
        request = await hitl.create(
            tenant_id=context.tenant_id,
            run_id=context.run_id or "",
            type=HITLType.APPROVAL,
            question=_approval_question(verb, resource),
            context=display_context,
            options=["approve", "reject"],
            verb=verb,
            requested_by=context.actor,
            request_fingerprint=fingerprint,
            action_digest=approval_action_digest(noun=noun, verb=verb, params=params),
            # Gate-created approvals inherit the configured timeout (SEC-14).
            timeout_seconds=hitl.approval_timeout_seconds,
            **hitl_scope_fields(context),
        )
        raise PendingHuman(request.id)
    return replace(
        context,
        extra={
            **dict(context.extra),
            "approved_by": approved_by,
            # Trusted evidence stamped only after the exact consume CAS succeeds.
            "approval_request_id": approval_id,
            "approval_request_fingerprint": fingerprint,
            "approval_resource_context": resource,
        },
    )
