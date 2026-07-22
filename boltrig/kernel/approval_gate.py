"""Exact-request approval gate shared by the dispatch chokepoint."""

from __future__ import annotations

import inspect
import json
from collections.abc import Awaitable, Callable
from dataclasses import replace
from typing import Any

from boltrig.adapters.base import Adapter
from boltrig.models import (
    BoltrigError,
    HITLType,
    InvocationContext,
    PendingHuman,
    TargetType,
    VerbBinding,
)

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
        "inputs": _approval_display_value(canonical_approval_value(params)),
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


async def enforce_approval(
    hitl: HITLManager,
    provider: AdapterProvider,
    binding: VerbBinding,
    noun: str,
    verb: str,
    params: dict[str, Any],
    context: InvocationContext,
    approval_id: str | None,
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
        request = await hitl.create(
            tenant_id=context.tenant_id,
            run_id=context.run_id or "",
            type=HITLType.APPROVAL,
            question=f"Approve {verb}?",
            context=display_context,
            options=["approve", "reject"],
            verb=verb,
            requested_by=context.actor,
            request_fingerprint=fingerprint,
            **hitl_scope_fields(context),
        )
        raise PendingHuman(request.id)
    return replace(
        context,
        extra={
            **dict(context.extra),
            "approved_by": approved_by,
            "approval_request_fingerprint": fingerprint,
            "approval_resource_context": resource,
        },
    )
