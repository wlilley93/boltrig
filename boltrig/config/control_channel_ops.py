"""Channel, evaluation, and personal-agent control-plane write helpers."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import replace
from datetime import timedelta
from typing import Any

from boltrig.identity.rbac import can_author
from boltrig.models import (
    Channel,
    ChannelBinding,
    ChannelPairing,
    EvalCase,
    utcnow,
)
from boltrig.models.channels import transport_for

_CHANNEL_TIERS = frozenset({"superadmin", "admin", "member"})
_CHANNEL_PLATFORMS = frozenset({"webhook", "msteams"})
_PAIR_TTL_MINUTES = 15
_PAIR_MAX_TTL_MINUTES = 60


def _require_author(context: Any) -> None:
    role = str((context.extra or {}).get("principal_role") or "")
    if not can_author(role):
        raise PermissionError("authoring/admin not permitted for this role")


async def _connect_channel(
    store: Any, tenant_id: str, params: dict[str, Any], context: Any
) -> dict:
    _require_author(context)
    platform = str(params.get("platform") or "").strip()
    name = str(params.get("name") or "").strip()
    if platform not in _CHANNEL_PLATFORMS or not name:
        raise ValueError("platform must be a webhook-class + name")
    channel_id = f"ch_{uuid.uuid4().hex[:16]}"
    secret = str(params.get("signing_secret") or "").strip()
    credential_ref = None
    if secret:
        credential_ref = f"cred_{uuid.uuid4().hex[:16]}"
        await store.set_credential_ref(tenant_id, credential_ref, {"secret": secret})
    channel = Channel(
        id=channel_id,
        tenant_id=tenant_id,
        platform=platform,
        name=name,
        transport=transport_for(platform),
        credential_ref=credential_ref,
        config=params.get("config") if isinstance(params.get("config"), dict) else {},
        enabled=bool(params.get("enabled", True)),
        unpaired_behavior=str(params.get("unpaired_behavior") or "reject"),
    )
    await store.upsert_channel(channel)
    return {
        "channel": channel_id,
        "transport": channel.transport,
        "inbound_url": f"/v1/channels/{channel_id}/inbound",
    }


async def _configure_channel(
    store: Any, tenant_id: str, params: dict[str, Any], context: Any
) -> dict:
    _require_author(context)
    channel = await store.get_channel(tenant_id, params["channel_id"])
    if channel is None:
        raise LookupError("channel not found")
    channel = replace(channel)
    if "name" in params:
        channel.name = str(params["name"])
    if isinstance(params.get("config"), dict):
        channel.config = params["config"]
    if "unpaired_behavior" in params:
        channel.unpaired_behavior = str(params["unpaired_behavior"])
    if "enabled" in params:
        channel.enabled = bool(params["enabled"])
    await store.upsert_channel(channel)
    return {"channel": channel.id}


async def _disconnect_channel(
    store: Any, tenant_id: str, params: dict[str, Any], context: Any
) -> dict:
    _require_author(context)
    channel_id = str(params["channel_id"])
    if await store.get_channel(tenant_id, channel_id) is None:
        raise LookupError("channel not found")
    await store.delete_channel(tenant_id, channel_id)
    return {"channel": channel_id}


def _pairing_code() -> str:
    return secrets.token_urlsafe(6)[:8].upper()


async def _pair_channel(store: Any, tenant_id: str, params: dict[str, Any], context: Any) -> dict:
    _require_author(context)
    channel_id = str(params["channel_id"])
    if await store.get_channel(tenant_id, channel_id) is None:
        raise LookupError("channel not found")
    external_user_id = str(params.get("external_user_id") or "").strip()
    subject = str(params.get("subject") or "").strip()
    role = str(params.get("role") or "member").strip()
    if not external_user_id or not subject or role not in _CHANNEL_TIERS:
        raise ValueError("external_user_id + subject + valid role required")
    ttl = max(
        1,
        min(int(params.get("ttl_minutes") or _PAIR_TTL_MINUTES), _PAIR_MAX_TTL_MINUTES),
    )
    code = _pairing_code()
    now = utcnow()
    pairing = ChannelPairing(
        id=f"cp_{uuid.uuid4().hex[:16]}",
        tenant_id=tenant_id,
        channel_id=channel_id,
        code_hash=hashlib.sha256(code.encode("utf-8")).hexdigest(),
        external_user_id=external_user_id,
        subject=subject,
        role=role,
        status="pending",
        attempts=0,
        expires_at=now + timedelta(minutes=ttl),
        created_at=now,
    )
    await store.create_channel_pairing(pairing)
    return {"pairing_id": pairing.id, "code": code}


async def _bind_channel(store: Any, tenant_id: str, params: dict[str, Any], context: Any) -> dict:
    _require_author(context)
    channel_id = str(params["channel_id"])
    channel = await store.get_channel(tenant_id, channel_id)
    if channel is None:
        raise LookupError("channel not found")
    external_user_id = str(params.get("external_user_id") or "").strip()
    subject = str(params.get("subject") or "").strip()
    role = str(params.get("role") or "member").strip()
    if not external_user_id or not subject or role not in _CHANNEL_TIERS:
        raise ValueError("external_user_id + subject + valid role required")
    binding = ChannelBinding(
        id=f"cb_{uuid.uuid4().hex[:12]}",
        tenant_id=tenant_id,
        channel_id=channel_id,
        platform=channel.platform,
        external_user_id=external_user_id,
        subject=subject,
        role=role,
    )
    await store.upsert_channel_binding(binding)
    return {"binding": binding.id}


async def _unbind_channel(store: Any, tenant_id: str, params: dict[str, Any], context: Any) -> dict:
    _require_author(context)
    channel_id = str(params["channel_id"])
    binding_id = str(params["binding_id"])
    rows = await store.list_channel_bindings(tenant_id, channel_id)
    if not any(row.id == binding_id for row in rows):
        raise LookupError("binding not found")
    await store.delete_channel_binding(tenant_id, binding_id)
    return {"channel": channel_id, "binding": binding_id}


async def _upsert_eval_case(
    store: Any, tenant_id: str, params: dict[str, Any], context: Any
) -> dict:
    _require_author(context)
    case = EvalCase(
        id=params.get("id") or uuid.uuid4().hex,
        tenant_id=tenant_id,
        target_kind=params["target_kind"],
        target_ref=params["target_ref"],
        input=params.get("input", {}),
        assertions=params.get("assertions", {}),
        labels=params.get("labels", []),
    )
    await store.upsert_eval_case(case)
    return {"id": case.id, "target": case.target_ref}


async def execute_channel_compat(
    store: Any, verb: str, params: dict[str, Any], context: Any
) -> dict[str, Any] | None:
    handlers = {
        "control.channel.connect": _connect_channel,
        "control.channel.configure": _configure_channel,
        "control.channel.disconnect": _disconnect_channel,
        "control.channel.pair": _pair_channel,
        "control.channel.bind": _bind_channel,
        "control.channel.unbind": _unbind_channel,
        "control.eval_case.upsert": _upsert_eval_case,
    }
    handler = handlers.get(verb)
    if handler is None:
        return None
    return await handler(store, context.tenant_id, params, context)
