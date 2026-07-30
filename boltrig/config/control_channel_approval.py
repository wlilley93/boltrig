"""Exact, secret-free channel resource snapshots for approval binding."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from boltrig.identity.rbac import can_author
from boltrig.models import AdapterFailure


def channel_delivery_view(receipt: Any) -> dict[str, Any]:
    """Public metadata-only delivery receipt; payload/lease data never enters."""
    return {
        "id": receipt.id,
        "channel_id": receipt.channel_id,
        "status": receipt.status,
        "attempts": receipt.attempts,
        "safe_reason": receipt.safe_reason,
        "created_at": receipt.created_at.isoformat() if receipt.created_at else None,
        "updated_at": receipt.updated_at.isoformat() if receipt.updated_at else None,
        "next_attempt_at": (
            receipt.next_attempt_at.isoformat() if receipt.next_attempt_at else None
        ),
    }


def channel_configuration_revision(channel: Any) -> str:
    document = {
        "id": channel.id,
        "platform": channel.platform,
        "transport": channel.transport,
        "credential_ref": channel.credential_ref,
        "config": channel.config,
        "unpaired_behavior": channel.unpaired_behavior,
        "enabled": channel.enabled,
    }
    canonical = json.dumps(
        document, sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def require_channel_author(context: Any) -> None:
    role = str((context.extra or {}).get("principal_role") or "")
    if not can_author(role):
        raise PermissionError("authoring/admin not permitted for this role")


async def channel_delivery_retry_context(
    store: Any, params: dict[str, Any], context: Any
) -> dict[str, Any]:
    """Exact, non-sensitive message + channel snapshot bound to an approval."""
    try:
        require_channel_author(context)
    except PermissionError as exc:
        raise AdapterFailure(
            str(exc), status_code=403, reason="control_unauthorised"
        ) from exc
    tenant_id = context.tenant_id
    channel_id = str(params.get("channel_id") or "")
    message_id = str(params.get("message_id") or "")
    expected_updated_at = str(params.get("expected_updated_at") or "")
    channel = await store.get_channel(tenant_id, channel_id)
    if channel is None:
        raise AdapterFailure(
            "channel not found",
            status_code=404,
            reason="control_resource_not_found",
        )
    receipt = await store.get_channel_delivery_receipt(
        tenant_id, channel_id, message_id
    )
    if receipt is None:
        raise AdapterFailure(
            "channel delivery not found",
            status_code=404,
            reason="control_resource_not_found",
        )
    if receipt.status != "terminal_failed":
        raise AdapterFailure(
            "only a terminal failed delivery may be retried",
            status_code=409,
            reason="control_conflict",
        )
    if (
        not channel.enabled
        or channel.transport != "socket"
        or not channel.credential_ref
    ):
        raise AdapterFailure(
            "retry requires an enabled socket channel with configured credentials",
            status_code=409,
            reason="control_conflict",
        )
    observed_updated_at = receipt.updated_at.isoformat() if receipt.updated_at else ""
    if not expected_updated_at or expected_updated_at != observed_updated_at:
        raise AdapterFailure(
            "delivery snapshot is stale",
            status_code=409,
            reason="control_conflict",
        )
    return {
        "channel_id": channel_id,
        "channel_configuration_revision": channel_configuration_revision(channel),
        "delivery": {
            "id": receipt.id,
            "status": receipt.status,
            "attempts": receipt.attempts,
            "updated_at": observed_updated_at,
        },
    }


async def channel_mutation_context(
    store: Any,
    verb: str,
    params: dict[str, Any],
    context: Any,
) -> dict[str, Any] | None:
    """Bind channel approvals to the exact mutable resource snapshot."""
    if verb == "control.channel.delivery.retry":
        return await channel_delivery_retry_context(store, params, context)
    require_channel_author(context)
    if verb == "control.channel.connect":
        return None
    channel_id = str(params.get("channel_id") or "")
    channel = await store.get_channel(context.tenant_id, channel_id)
    if channel is None:
        raise AdapterFailure(
            "channel not found",
            status_code=404,
            reason="control_resource_not_found",
        )
    resource: dict[str, Any] = {
        "channel": {
            "id": channel.id,
            "revision": channel_configuration_revision(channel),
        }
    }
    if verb != "control.channel.unbind":
        return resource
    binding_id = str(params.get("binding_id") or "")
    binding = next(
        (
            row
            for row in await store.list_channel_bindings(
                context.tenant_id, channel_id
            )
            if row.id == binding_id
        ),
        None,
    )
    if binding is None:
        raise AdapterFailure(
            "channel binding not found",
            status_code=404,
            reason="control_resource_not_found",
        )
    return {
        **resource,
        "binding": {
            "id": binding.id,
            "external_user_id": binding.external_user_id,
            "subject": binding.subject,
            "role": binding.role,
        },
    }
