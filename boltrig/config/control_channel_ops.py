"""Channel, evaluation, and personal-agent control-plane write helpers."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any

from boltrig.models import (
    Channel,
    ChannelBinding,
    ChannelPairing,
    utcnow,
)
from boltrig.models.channel_providers import (
    CHANNEL_PLATFORMS,
    credential_presence,
    credential_reference_bundle,
    normalise_channel_config,
    provider_for,
    transport_for,
)
from boltrig.identity.rbac import departments_for
from .control_channel_approval import (
    channel_delivery_retry_context as channel_delivery_retry_context,
    channel_delivery_view as channel_delivery_view,
    channel_mutation_context as channel_mutation_context,
    require_channel_author,
)
from .channel_addressing import validate_channel_policy_config
from .control_eval_case_ops import (
    archive_eval_case,
    restore_eval_case,
    upsert_eval_case,
)

_CHANNEL_TIERS = frozenset({"superadmin", "admin", "member"})
_CHANNEL_PLATFORMS = frozenset(CHANNEL_PLATFORMS)
_PAIR_TTL_MINUTES = 15
_PAIR_MAX_TTL_MINUTES = 60


def _require_author(context: Any) -> None:
    require_channel_author(context)


def _addressing_departments(context: Any) -> list[str] | None:
    extra = context.extra or {}
    return departments_for(
        str(extra.get("principal_role") or ""),
        extra.get("principal_scope"),
    )


async def _create_channel_credential(
    store: Any,
    tenant_id: str,
    platform: str,
    params: dict[str, Any],
) -> str | None:
    secret = str(params.get("signing_secret") or "").strip()
    secret_ref = str(params.get("signing_secret_ref") or "").strip()
    supplied_refs = dict(params.get("credential_refs") or {})
    if secret_ref:
        supplied_refs["signing"] = secret_ref
    if supplied_refs:
        bundle = credential_reference_bundle(platform, supplied_refs)
        missing = [
            key
            for key, configured in credential_presence(platform, bundle).items()
            if not configured
        ]
        if missing:
            raise ValueError(
                f"{platform} requires credential references: {', '.join(missing)}"
            )
        credential_ref = f"cred_{uuid.uuid4().hex[:16]}"
        if (
            provider_for(platform).transport == "webhook"
            and set(supplied_refs) == {"signing"}
        ):
            await store.set_credential_ref(
                tenant_id,
                credential_ref,
                {
                    "store": "env",
                    "ref": supplied_refs["signing"],
                    "kind": "webhook_signing",
                },
            )
        else:
            await store.set_credential_ref(tenant_id, credential_ref, bundle)
        return credential_ref
    if secret:
        if provider_for(platform).transport == "socket":
            raise ValueError(
                "socket channels accept secret-store references only; plaintext is refused"
            )
        credential_ref = f"cred_{uuid.uuid4().hex[:16]}"
        await store.set_credential_ref(tenant_id, credential_ref, {"secret": secret})
        return credential_ref
    if provider_for(platform).transport == "socket":
        raise ValueError(
            f"{platform} requires credential_refs; gateway secrets are never accepted inline"
        )
    return None


async def _connect_channel(
    store: Any, tenant_id: str, params: dict[str, Any], context: Any
) -> dict:
    _require_author(context)
    from .control_approval import require_unchanged_approval_context

    await require_unchanged_approval_context(
        store, None, "control.channel.connect", params, context
    )
    platform = str(params.get("platform") or "").strip()
    name = str(params.get("name") or "").strip()
    if platform not in _CHANNEL_PLATFORMS or not name:
        raise ValueError("a supported channel platform + name is required")
    channel_id = f"ch_{uuid.uuid4().hex[:16]}"
    credential_ref = await _create_channel_credential(
        store, tenant_id, platform, params
    )
    provider_config = params.get("provider_config")
    policy_config = params.get("config")
    config = normalise_channel_config(
        platform,
        policy_config if isinstance(policy_config, dict) else {},
        provider_config if isinstance(provider_config, dict) else {},
    )
    await validate_channel_policy_config(
        store,
        tenant_id,
        getattr(context, "workspace_id", None),
        config,
        allowed_departments=_addressing_departments(context),
    )
    channel = Channel(
        id=channel_id,
        tenant_id=tenant_id,
        platform=platform,
        name=name,
        transport=transport_for(platform),
        credential_ref=credential_ref,
        config=config,
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
    from .control_approval import require_unchanged_approval_context

    await require_unchanged_approval_context(
        store, None, "control.channel.configure", params, context
    )
    channel = await store.get_channel(tenant_id, params["channel_id"])
    if channel is None:
        raise LookupError("channel not found")
    channel = replace(channel)
    retired_credential_ref = None
    if "name" in params:
        channel.name = str(params["name"])
    provider_config = params.get("provider_config")
    if isinstance(params.get("config"), dict) or isinstance(provider_config, dict):
        existing_provider = dict((channel.config or {}).get("provider") or {})
        next_policy = (
            dict(params["config"])
            if isinstance(params.get("config"), dict)
            else {
                key: value for key, value in (channel.config or {}).items()
                if key != "provider"
            }
        )
        channel.config = normalise_channel_config(
            channel.platform,
            next_policy,
            provider_config if isinstance(provider_config, dict) else existing_provider,
        )
        if isinstance(params.get("config"), dict):
            await validate_channel_policy_config(
                store,
                tenant_id,
                getattr(context, "workspace_id", None),
                channel.config,
                allowed_departments=_addressing_departments(context),
            )
    if isinstance(params.get("credential_refs"), dict):
        current = (
            await store.get_credential_ref(tenant_id, channel.credential_ref)
            if channel.credential_ref else None
        )
        bundle = credential_reference_bundle(
            channel.platform, params["credential_refs"], existing=current
        )
        missing = [
            key for key, configured in credential_presence(
                channel.platform, bundle
            ).items() if not configured
        ]
        if missing:
            raise ValueError(
                f"{channel.platform} requires credential references: {', '.join(missing)}"
            )
        retired_credential_ref = channel.credential_ref
        # Rotation gets a fresh opaque id.  Reconciliation revisions can then
        # change without hashing/exposing the external secret-store name.
        channel.credential_ref = f"cred_{uuid.uuid4().hex[:16]}"
        await store.set_credential_ref(tenant_id, channel.credential_ref, bundle)
    if "unpaired_behavior" in params:
        channel.unpaired_behavior = str(params["unpaired_behavior"])
    if "enabled" in params:
        channel.enabled = bool(params["enabled"])
    await store.upsert_channel(channel)
    if retired_credential_ref and retired_credential_ref != channel.credential_ref:
        await store.delete_credential_ref(tenant_id, retired_credential_ref)
    return {"channel": channel.id}


async def _disconnect_channel(
    store: Any, tenant_id: str, params: dict[str, Any], context: Any
) -> dict:
    _require_author(context)
    from .control_approval import require_unchanged_approval_context

    await require_unchanged_approval_context(
        store, None, "control.channel.disconnect", params, context
    )
    channel_id = str(params["channel_id"])
    if await store.get_channel(tenant_id, channel_id) is None:
        raise LookupError("channel not found")
    await store.delete_channel(tenant_id, channel_id)
    return {"channel": channel_id}


def _pairing_code() -> str:
    return secrets.token_urlsafe(6)[:8].upper()


async def _pair_channel(store: Any, tenant_id: str, params: dict[str, Any], context: Any) -> dict:
    _require_author(context)
    from .control_approval import require_unchanged_approval_context

    await require_unchanged_approval_context(
        store, None, "control.channel.pair", params, context
    )
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
    from .control_approval import require_unchanged_approval_context

    await require_unchanged_approval_context(
        store, None, "control.channel.bind", params, context
    )
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
    from .control_approval import require_unchanged_approval_context

    await require_unchanged_approval_context(
        store, None, "control.channel.unbind", params, context
    )
    channel_id = str(params["channel_id"])
    binding_id = str(params["binding_id"])
    rows = await store.list_channel_bindings(tenant_id, channel_id)
    if not any(row.id == binding_id for row in rows):
        raise LookupError("binding not found")
    await store.delete_channel_binding(tenant_id, binding_id)
    return {"channel": channel_id, "binding": binding_id}


async def _retry_channel_delivery(
    store: Any, tenant_id: str, params: dict[str, Any], context: Any
) -> dict:
    from .control_approval import require_unchanged_approval_context
    from .control_safety import ControlConflict

    await require_unchanged_approval_context(
        store, None, "control.channel.delivery.retry", params, context
    )
    expected = datetime.fromisoformat(str(params["expected_updated_at"]))
    if expected.tzinfo is None:
        raise ValueError("expected_updated_at must include a timezone")
    receipt = await store.retry_terminal_channel_delivery(
        tenant_id,
        str(params["channel_id"]),
        str(params["message_id"]),
        expected,
    )
    if receipt is None:
        raise ControlConflict("delivery changed before retry")
    return {"delivery": channel_delivery_view(receipt)}


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
        "control.channel.delivery.retry": _retry_channel_delivery,
        "control.eval_case.archive": archive_eval_case,
        "control.eval_case.restore": restore_eval_case,
        "control.eval_case.upsert": upsert_eval_case,
    }
    handler = handlers.get(verb)
    if handler is None:
        return None
    return await handler(store, context.tenant_id, params, context)
