"""Shared mutation helpers behind the governed ``control.*`` adapter."""

from __future__ import annotations

import uuid
from dataclasses import replace
from typing import Any, cast

from boltrig.models import (
    AdapterHealth,
    AdapterRecord,
    Consequence,
    IdempotencyMode,
    Noun,
    RateLimit,
    Skill,
    TargetType,
    UserInvitation,
    Verb,
    VerbBinding,
    utcnow,
)
from .author_ratchet import assert_author_ratchet, is_active_author
from .control_safety import (
    ControlConflict,
    ensure_activation_safe,
    ensure_adapter_id_available,
)

_ADMIN_ROLES = frozenset({"org-admin", "superadmin", "admin"})


def safe_consequence(verb_id: str, explicit: Any) -> str:
    """Use a high consequence for mutation-shaped names when none is supplied."""
    destructive = frozenset(
        {
            "delete",
            "remove",
            "destroy",
            "drop",
            "purge",
            "wipe",
            "erase",
            "send",
            "email",
            "post",
            "pay",
            "transfer",
            "charge",
            "refund",
            "deactivate",
            "revoke",
            "cancel",
            "terminate",
            "approve",
            "publish",
        }
    )
    if explicit in ("low", "high"):
        return str(explicit)
    tail = verb_id.rsplit(".", 1)[-1].lower()
    return "high" if any(token in tail for token in destructive) else "low"


async def upsert_skill_record(store: Any, tenant_id: str, params: dict[str, Any]) -> Skill:
    skill = Skill(
        id=params["id"],
        tenant_id=tenant_id,
        version=params.get("version", "1.0.0"),
        prompt_fragment=params.get("prompt_fragment", ""),
        tool_grants=params.get("tool_grants", []),
        context_requirements=params.get("context_requirements", {}),
        extends=params.get("extends"),
        locale=params.get("locale", "en"),
        description=params.get("description", ""),
    )
    await store.upsert_skill(skill)
    return skill


async def upsert_noun_record(store: Any, tenant_id: str, params: dict[str, Any]) -> Noun:
    noun = Noun(
        id=params["id"],
        tenant_id=tenant_id,
        description=params.get("description", ""),
        schema=params.get("schema", {}),
    )
    await store.upsert_noun(noun)
    return noun


async def upsert_verb_record(store: Any, tenant_id: str, params: dict[str, Any]) -> Verb:
    consequence = safe_consequence(params["id"], params.get("consequence"))
    verb = Verb(
        id=params["id"],
        tenant_id=tenant_id,
        noun_id=params["noun_id"],
        input_schema=params.get("input_schema", {}),
        output_schema=params.get("output_schema", {}),
        description=params.get("description", ""),
        consequence=Consequence(consequence),
        degraded_mode=params.get("degraded_mode"),
        identity_mode=params.get("identity_mode", "service-principal"),
        idempotency_mode=IdempotencyMode(params.get("idempotency_mode", "cacheable")),
    )
    await store.upsert_verb(verb)
    return verb


async def set_binding_record(
    store: Any, tenant_id: str, verb_id: str, params: dict[str, Any]
) -> VerbBinding:
    rate_limit = params.get("rate_limit")
    binding = VerbBinding(
        verb_id=verb_id,
        tenant_id=tenant_id,
        target_type=TargetType(params["target_type"]),
        target_ref=params["target_ref"],
        rate_limit=RateLimit(**rate_limit) if isinstance(rate_limit, dict) else None,
    )
    await store.upsert_binding(binding)
    return binding


async def record_inert_adapter(
    store: Any,
    tenant_id: str,
    adapter: Any,
    *,
    created_by: str | None,
    spec_ref: str | None = None,
) -> None:
    created = await store.create_adapter_if_absent(
        AdapterRecord(
            id=adapter.id,
            tenant_id=tenant_id,
            version=getattr(adapter, "version", "0"),
            runtime=getattr(adapter, "runtime", "script"),
            source=getattr(adapter, "source", "generated"),
            module_ref=type(adapter).__module__,
            # spec_ref is what boot rehydration rebuilds the instance FROM (for
            # an MCP consumer, its url); without it the row is a phantom after
            # the first restart.
            spec_ref=spec_ref,
            health=AdapterHealth.UNKNOWN,
            created_by=created_by,
            activated=False,
        )
    )
    if not created:
        raise ControlConflict("adapter id already exists")


async def generate_adapter_record(
    store: Any,
    loader: Any,
    tenant_id: str,
    params: dict[str, Any],
    *,
    actor: str,
) -> Any:
    from boltrig.adapters.generator import generate_adapter_from_spec
    from .control_generated_adapter import (
        generated_adapter_from_record,
        generated_adapter_projection,
        stamp_generated_adapter,
    )

    await ensure_adapter_id_available(store, loader, tenant_id, params["adapter_id"])
    adapter = generate_adapter_from_spec(params["spec"], adapter_id=params["adapter_id"])
    spec_ref = generated_adapter_projection(adapter)
    await record_inert_adapter(
        store,
        tenant_id,
        adapter,
        created_by=actor,
        spec_ref=spec_ref,
    )
    if loader.peek(tenant_id, adapter.id) is not None:
        raise ControlConflict("adapter id became live during registration")
    record = await store.get_adapter(tenant_id, adapter.id)
    if record is None:
        raise ControlConflict("generated adapter registration was not retained")
    adapter = generated_adapter_from_record(record)
    stamp_generated_adapter(adapter, record)
    loader.register(tenant_id, adapter)
    return adapter


async def activate_adapter_record(
    store: Any,
    loader: Any,
    registry: Any,
    tenant_id: str,
    adapter_id: str,
    *,
    reviewer: str,
    credentials: Any = None,
) -> list[str]:
    record = await store.get_adapter(tenant_id, adapter_id)
    if record is None:
        raise LookupError("adapter not found")
    from .control_generated_adapter import (
        is_generated_adapter_record,
        reconcile_generated_adapter,
    )

    adapter = (
        await reconcile_generated_adapter(loader, tenant_id, record)
        if is_generated_adapter_record(record)
        else await loader.get(tenant_id, adapter_id)
    )
    if adapter is None:
        # A store row this kernel never rebuilt (another replica's
        # registration, or a boot skip): rebuild it on demand when the row
        # carries everything an honest reconstruction needs, and refuse loudly
        # otherwise - never pend or fail opaquely on a row that exists.
        from .control_rehydrate import rehydrate_adapter_instance

        adapter = await rehydrate_adapter_instance(
            store, credentials, loader, tenant_id, record
        )
        if adapter is None:
            raise ControlConflict(
                "adapter cannot be reconstructed from its store row; "
                "delete and re-register it"
            )
    connect = getattr(adapter, "connect", None)
    if connect is not None:
        # A consuming adapter (MCP, US-MCP-03) discovers its verbs HERE: connect()
        # runs tools/list against the external server so describe() below
        # publishes the server's actual tools (schemas + consequence hints), not
        # an empty catalogue. The credential comes from the same kernel seam
        # dispatch uses (SEC-04/05); a credential-less HTTP consumer fails closed
        # inside connect() rather than activating silently with zero verbs.
        credential = (
            await credentials.resolve_for_adapter(tenant_id, adapter_id)
            if credentials is not None
            else None
        )
        await connect(credential)
    await ensure_activation_safe(store, tenant_id, adapter_id, adapter)
    activate = getattr(adapter, "review_and_activate", None)
    if activate is not None:
        activate(reviewer)
    verbs = await registry.register_adapter_verbs(tenant_id, adapter)
    record.activated = True
    await store.upsert_adapter(record)
    if is_generated_adapter_record(record):
        from .control_generated_adapter import stamp_generated_adapter

        stamp_generated_adapter(adapter, record)
    return cast(list[str], verbs)


def _principal_role(context: Any) -> str:
    role = str((context.extra or {}).get("principal_role") or "")
    if role not in _ADMIN_ROLES:
        raise PermissionError("organisation administration requires an authenticated admin")
    return role


def _reject_escalation(role: str, target_role: Any, scope: Any) -> None:
    from boltrig.identity.rbac import _role_rank

    if target_role is not None and _role_rank(str(target_role)) < _role_rank(role):
        raise PermissionError("cannot grant a role ranked above the caller")
    if isinstance(scope, dict) and scope.get("all") and role != "superadmin":
        raise PermissionError("only the owner may grant all-authority scope")


async def update_user_record(
    store: Any, tenant_id: str, params: dict[str, Any], *, context: Any
) -> Any:
    role = _principal_role(context)
    _reject_escalation(role, params.get("role"), params.get("scope"))
    user = await store.get_user(tenant_id, params["user_id"])
    if user is None:
        raise LookupError("user not found")
    # Build the RESULTING record, ask the ratchet about THAT, then persist it (D2).
    changes: dict[str, Any] = {}
    if "role" in params:
        changes["role"] = params["role"]
    if isinstance(params.get("scope"), dict):
        changes["scope"] = params["scope"]
    if params.get("status") in {"active", "deactivated"}:
        changes["status"] = params["status"]
    updated = replace(user, **changes)
    await assert_author_ratchet(
        store, tenant_id, user_id=updated.id, stays_author=is_active_author(updated)
    )
    await store.upsert_user(updated)
    return updated


async def deactivate_user_record(store: Any, tenant_id: str, user_id: str, *, context: Any) -> Any:
    _principal_role(context)
    user = await store.get_user(tenant_id, user_id)
    if user is None:
        raise LookupError("user not found")
    # The same crossing by another route (D2): a deactivated user is not an
    # active author.
    await assert_author_ratchet(store, tenant_id, user_id=user.id, stays_author=False)
    user.status = "deactivated"
    await store.upsert_user(user)
    return user


async def create_invitation_record(
    store: Any, tenant_id: str, params: dict[str, Any], *, context: Any
) -> tuple[UserInvitation, str]:
    from boltrig.identity.invites import generate_invite_token, hash_invite_token
    from boltrig.identity.tokens import bounded_expiry

    role = _principal_role(context)
    _reject_escalation(role, params.get("role"), params.get("scope"))
    email = str(params.get("email") or "").strip()
    if not email:
        raise ValueError("email is required")
    provision_org = str(params.get("provision_org_name") or "").strip() or None
    if provision_org is not None and role != "superadmin":
        raise PermissionError("only the owner may provision an organisation")
    workspace_id = str(params.get("workspace_id") or "").strip() or None
    if workspace_id is not None and await store.get_workspace(tenant_id, workspace_id) is None:
        raise LookupError("workspace not found")
    secret = generate_invite_token()
    invitation = UserInvitation(
        id=uuid.uuid4().hex,
        tenant_id=tenant_id,
        email=email,
        intended_role=params.get("role", "agent"),
        intended_scope=params.get("scope", {}),
        invited_by=context.on_behalf_of or context.actor,
        expires_at=bounded_expiry(utcnow(), params.get("ttl_days", 14)),
        token_hash=hash_invite_token(secret),
        workspace_id=workspace_id,
        provision_workspace_name=(
            str(params.get("provision_workspace_name") or "").strip() or None
        ),
        provision_org_name=provision_org,
    )
    if not await store.add_invitation_if_no_pending(invitation):
        raise ControlConflict("a pending invitation already exists for this email")
    return invitation, secret


async def revoke_invitation_record(
    store: Any, tenant_id: str, invite_id: str, *, context: Any
) -> Any:
    _principal_role(context)
    invitation = await store.get_invitation(tenant_id, invite_id)
    if invitation is None:
        raise LookupError("invitation not found")
    if invitation.status == "revoked":
        return invitation
    invitation.status = "revoked"
    await store.update_invitation(invitation)
    return invitation
