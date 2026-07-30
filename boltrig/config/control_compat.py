"""Compatibility mutations routed through the governed ``control.*`` adapter.

These helpers are the sole write implementation shared by the legacy HTTP
surfaces and direct control-plane callers.  Authorization is repeated here so
an agent invoking a discoverable control verb cannot bypass an HTTP route guard.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from typing import Any

from boltrig.models import (
    AI_CONFIG_LEVELS,
    WORKSPACE_ROLES,
    Workspace,
    WorkspaceMember,
    utcnow,
)
from .control_safety import ControlConflict

_ADMIN_ROLES = frozenset({"org-admin", "superadmin", "admin"})
_WORKSPACE_ADMIN_ROLES = frozenset({"owner", "admin"})


def _role(context: Any) -> str:
    return str((context.extra or {}).get("principal_role") or "")


def _require_admin(context: Any) -> None:
    if _role(context) not in _ADMIN_ROLES:
        raise PermissionError("organisation administration requires an authenticated admin")


async def _managed_workspace(store: Any, tenant_id: str, workspace_id: str, context: Any) -> Any:
    workspace = await store.get_workspace(tenant_id, workspace_id)
    if workspace is None:
        raise LookupError("workspace not found")
    if _role(context) in _ADMIN_ROLES:
        return workspace
    member = await store.get_workspace_member(tenant_id, workspace_id, context.actor)
    if member is None or member.role not in _WORKSPACE_ADMIN_ROLES:
        raise PermissionError("must be a workspace owner/admin to manage it")
    return workspace


async def _authorise_ai_key(
    store: Any, tenant_id: str, level: str, scope_id: str, context: Any
) -> None:
    if level not in AI_CONFIG_LEVELS:
        raise ValueError(f"level must be one of {sorted(AI_CONFIG_LEVELS)}")
    is_admin = _role(context) in _ADMIN_ROLES
    if level == "org":
        _require_admin(context)
        if scope_id != tenant_id:
            raise PermissionError("org AI key must target the active organisation")
        return
    org = await store.get_org(tenant_id)
    if org is None or not org.allow_own_ai_keys:
        raise PermissionError("organisation does not allow own AI keys")
    if level == "workspace":
        if is_admin:
            return
        member = await store.get_workspace_member(tenant_id, scope_id, context.actor)
        if member is None or member.role not in _WORKSPACE_ADMIN_ROLES:
            raise PermissionError("must be a workspace owner/admin to set its AI key")
        return
    if not is_admin and scope_id != context.actor:
        raise PermissionError("may only set your own user AI key")


def _workspace_slug(name: str) -> str:
    from boltrig.identity.tenancy import default_org_slug

    return f"{default_org_slug(name) or 'workspace'}-{uuid.uuid4().hex[:6]}"


def _workspace_view(workspace: Any) -> dict[str, Any]:
    return {
        "id": workspace.id,
        "name": workspace.name,
        "slug": workspace.slug,
        "status": workspace.status,
        "settings": workspace.settings,
        "created_at": workspace.created_at.isoformat() if workspace.created_at else None,
        "updated_at": workspace.updated_at.isoformat() if workspace.updated_at else None,
    }


def _workspace_member_view(member: Any) -> dict[str, Any]:
    return {
        "user_id": member.user_id,
        "workspace_id": member.workspace_id,
        "role": member.role,
        "permissions": member.permissions,
        "created_at": member.created_at.isoformat() if member.created_at else None,
    }


def _org_view(org: Any) -> dict[str, Any]:
    return {
        "id": org.id,
        "name": org.name,
        "slug": org.slug,
        "settings": org.settings,
        "allow_own_ai_keys": bool(org.allow_own_ai_keys),
        "require_two_factor": bool(org.require_two_factor),
        "created_at": org.created_at.isoformat() if org.created_at else None,
        "updated_at": org.updated_at.isoformat() if org.updated_at else None,
    }


async def _set_ai_key(store: Any, tenant_id: str, params: dict[str, Any], context: Any) -> dict:
    level = str(params["level"]).strip()
    scope_id = str(params["scope_id"]).strip()
    await _authorise_ai_key(store, tenant_id, level, scope_id, context)
    provider = str(params["provider"]).strip()
    model = str(params["model"]).strip()
    proposal_id = str(params["proposal_id"]).strip()
    secret_digest = str(params["secret_digest"]).strip()
    if not provider or not model or not proposal_id or not secret_digest:
        raise ValueError(
            "provider, model, proposal_id and secret_digest are required"
        )
    base_url = str(params.get("base_url") or "").strip() or None
    proposal = await store.get_ai_key_secret_proposal(tenant_id, proposal_id)
    approval_id = str((context.extra or {}).get("approval_request_id") or "")
    if (
        proposal is None
        or proposal.approval_id != approval_id
        or not approval_id
        or not (context.extra or {}).get("approved_by")
    ):
        raise PermissionError("exact AI-key proposal approval evidence is missing")
    from .control_approval import require_unchanged_approval_context

    await require_unchanged_approval_context(
        store, None, "control.ai_key.set", params, context
    )
    config = await store.consume_ai_key_secret_proposal(
        tenant_id,
        proposal_id,
        requested_by=context.actor,
        requested_on_behalf_of=context.on_behalf_of,
        workspace_id=context.workspace_id,
        level=level,
        scope_id=scope_id,
        provider=provider,
        model=model,
        base_url=base_url,
        secret_digest=secret_digest,
        now=utcnow(),
    )
    if config is None:
        raise ControlConflict(
            "AI-key proposal changed, expired or was already consumed"
        )
    return {
        "level": level,
        "scope_id": scope_id,
        "provider": provider,
        "model": model,
        "base_url": base_url,
        "proposal_id": proposal_id,
    }


async def _delete_ai_key(store: Any, tenant_id: str, params: dict[str, Any], context: Any) -> dict:
    level = str(params["level"]).strip()
    scope_id = str(params["scope_id"]).strip()
    await _authorise_ai_key(store, tenant_id, level, scope_id, context)
    existing = await store.get_ai_config(tenant_id, level, scope_id)
    if existing is None:
        raise LookupError("AI key not found")
    await store.delete_ai_config(tenant_id, level, scope_id)
    await store.set_credential_ref(tenant_id, existing.credential_ref, {})
    return {"level": level, "scope_id": scope_id}


async def _update_org(store: Any, tenant_id: str, params: dict[str, Any], context: Any) -> dict:
    from boltrig.identity.tenancy import ensure_default_org

    _require_admin(context)
    org = replace(await ensure_default_org(store, tenant_id))
    if isinstance(params.get("name"), str) and params["name"].strip():
        org.name = params["name"].strip()
    if isinstance(params.get("slug"), str) and params["slug"].strip():
        org.slug = params["slug"].strip()
    if isinstance(params.get("settings"), dict):
        org.settings = params["settings"]
    if "allow_own_ai_keys" in params:
        org.allow_own_ai_keys = bool(params["allow_own_ai_keys"])
    if "require_two_factor" in params:
        org.require_two_factor = bool(params["require_two_factor"])
    await store.update_org(org)
    return {"organisation": _org_view(org)}


async def _create_workspace(
    store: Any, tenant_id: str, params: dict[str, Any], context: Any
) -> dict:
    _require_admin(context)
    name = str(params.get("name") or "").strip()
    if not name:
        raise ValueError("name is required")
    workspace = Workspace(
        id=uuid.uuid4().hex,
        tenant_id=tenant_id,
        name=name,
        slug=_workspace_slug(name),
        settings=params.get("settings") if isinstance(params.get("settings"), dict) else {},
    )
    await store.create_workspace(workspace)
    await store.add_workspace_member(
        WorkspaceMember(
            user_id=context.actor,
            workspace_id=workspace.id,
            tenant_id=tenant_id,
            role="owner",
        )
    )
    return {"workspace": _workspace_view(workspace)}


async def _update_workspace(
    store: Any, tenant_id: str, params: dict[str, Any], context: Any
) -> dict:
    workspace = replace(await _managed_workspace(store, tenant_id, params["workspace_id"], context))
    if isinstance(params.get("name"), str) and params["name"].strip():
        workspace.name = params["name"].strip()
    if isinstance(params.get("settings"), dict):
        workspace.settings = params["settings"]
    if params.get("status") in {"active", "archived"}:
        workspace.status = params["status"]
    await store.update_workspace(workspace)
    return {"workspace": _workspace_view(workspace)}


async def _add_workspace_member(
    store: Any, tenant_id: str, params: dict[str, Any], context: Any
) -> dict:
    workspace_id = str(params["workspace_id"])
    await _managed_workspace(store, tenant_id, workspace_id, context)
    user_id = str(params.get("user_id") or "").strip()
    role = str(params.get("role") or "member").strip()
    if not user_id:
        raise ValueError("user_id is required")
    if role not in WORKSPACE_ROLES:
        raise ValueError(f"role must be one of {sorted(WORKSPACE_ROLES)}")
    if await store.get_user(tenant_id, user_id) is None:
        raise LookupError("unknown user")
    member = WorkspaceMember(
        user_id=user_id,
        workspace_id=workspace_id,
        tenant_id=tenant_id,
        role=role,
        permissions=(
            params.get("permissions") if isinstance(params.get("permissions"), dict) else {}
        ),
    )
    await store.add_workspace_member(member)
    return {"member": _workspace_member_view(member)}


async def _remove_workspace_member(
    store: Any, tenant_id: str, params: dict[str, Any], context: Any
) -> dict:
    workspace_id = str(params["workspace_id"])
    user_id = str(params["user_id"])
    await _managed_workspace(store, tenant_id, workspace_id, context)
    await store.remove_workspace_member(tenant_id, workspace_id, user_id)
    return {"workspace_id": workspace_id, "user": user_id}


async def execute_compat_operation(
    store: Any, verb: str, params: dict[str, Any], context: Any
) -> dict[str, Any] | None:
    """Execute one migrated legacy mutation, or return ``None`` when unmatched."""
    tenant_id = context.tenant_id
    handlers = {
        "control.ai_key.set": _set_ai_key,
        "control.ai_key.delete": _delete_ai_key,
        "control.org.update": _update_org,
        "control.workspace.create": _create_workspace,
        "control.workspace.update": _update_workspace,
        "control.workspace.member.add": _add_workspace_member,
        "control.workspace.member.remove": _remove_workspace_member,
    }
    handler = handlers.get(verb)
    if handler is not None:
        return await handler(store, tenant_id, params, context)
    from .control_channel_ops import execute_channel_compat

    return await execute_channel_compat(store, verb, params, context)
