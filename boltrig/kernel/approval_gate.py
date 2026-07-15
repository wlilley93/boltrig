"""Exact-request approval gate shared by the dispatch chokepoint."""

from __future__ import annotations

import inspect
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

AdapterProvider = Callable[[str, str], Awaitable[Adapter | None]]


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
            question=f"Approve {verb} ?",
            context=f"{context.actor} requests {verb}",
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
