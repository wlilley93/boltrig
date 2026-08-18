"""Governed integration-connection setup and lifecycle operations."""

from __future__ import annotations

import uuid
from typing import Any
from urllib.parse import urlsplit

from boltrig.adapters.base import Result
from boltrig.kernel.integration_credentials import integration_manual_secret_ref
from boltrig.kernel.integration_scope import acting_owner
from boltrig.models.integration_auth import IntegrationSecretContract
from boltrig.models.integrations import INTEGRATION_SCOPE_LEVELS, IntegrationConnection

from .control_approval import require_unchanged_approval_context
from .control_safety import ControlConflict


def validate_integration_secret_fields(
    contract: IntegrationSecretContract, submitted: object
) -> tuple[dict[str, str] | None, str | None]:
    """Apply a provider's closed manual-secret contract inside the control adapter."""
    if not isinstance(submitted, dict):
        return None, "fields_required"
    declared = {field.name: field for field in contract.fields}
    if any(not isinstance(name, str) for name in submitted) or set(submitted) - set(declared):
        return None, "unknown_fields"
    values: dict[str, str] = {}
    for name, field in declared.items():
        raw = submitted.get(name)
        if raw is None:
            if field.required:
                return None, "required_field_missing"
            continue
        if not isinstance(raw, str):
            return None, "field_must_be_string"
        value = raw if field.secret else raw.strip()
        if not field.min_length <= len(value) <= field.max_length:
            return None, "field_length_invalid"
        if any(ord(character) < 32 or ord(character) == 127 for character in value):
            return None, "field_contains_control_characters"
        if name == "base_url":
            parsed = urlsplit(value)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.query
                or parsed.fragment
            ):
                return None, "base_url_must_be_canonical_https_origin"
        values[name] = value
    return values, None


def integration_connection_accounts(
    contract: IntegrationSecretContract,
    fields: dict[str, str],
    fallback_label: str,
) -> list[dict[str, object]]:
    account_id = (
        fields.get(contract.account_id_field)
        if contract.account_id_field is not None
        else "default"
    )
    account_label = (
        fields.get(contract.account_label_field)
        if contract.account_label_field is not None
        else fallback_label
    )
    return [
        {
            "id": account_id or "default",
            "label": account_label or fallback_label,
            "selected": True,
        }
    ]


async def integration_setup_refusal(
    store: Any,
    loader: Any,
    credentials: Any,
    tenant_id: str,
    item: Any,
    level: str = "org",
    scope_id: str = "",
) -> str | None:
    """Return the exact fail-closed reason for one provider-declared setup.

    Every reason lives here rather than half here and half in the caller, so the
    HTTP pre-check and the governed handler cannot disagree about whether a setup
    is offerable -- the 409 body and the ControlConflict are the same string.
    """
    if item.certification != "certified":
        return "not_certified"
    if "manual_secret" not in item.auth:
        return "manual_secret_not_declared"
    if item.secret_contract is None:
        return "typed_secret_contract_not_configured"
    if not item.adapter_id:
        return "adapter_not_registered"
    adapter = await store.get_adapter(tenant_id, item.adapter_id)
    if adapter is None:
        return "adapter_not_registered"
    if not adapter.activated:
        return "adapter_not_activated"
    health = loader.health_of(tenant_id, item.adapter_id) if loader is not None else "unknown"
    if health not in {"ok", "degraded"}:
        return "adapter_health_unverified" if health == "unknown" else "adapter_down"
    if credentials is None:
        return "credential_resolver_unavailable"
    if level not in INTEGRATION_SCOPE_LEVELS:
        return "unsupported_scope_level"
    if level != "org":
        if not scope_id:
            # An agent or service token has no personal scope to connect into.
            return "user_scope_requires_human_identity"
        org = await store.get_org(tenant_id)
        if org is None or not org.allow_own_integration_credentials:
            # Refused BEFORE anything is sealed. Without this an opted-out org
            # would still accept the secret and store it sealed, while
            # `pick_connection` skips the user row the policy forbids -- leaving
            # a live credential that nobody can use and nobody can find.
            return "own_integration_credentials_not_allowed"
    if await credentials.has_adapter_credential_reference(
        tenant_id, item.adapter_id, level, scope_id
    ):
        return "adapter_credential_already_bound"
    return None


async def _connect(
    store: Any,
    loader: Any,
    credentials: Any,
    params: dict[str, Any],
    context: Any,
) -> Result:
    integration_id = str(params["integration_id"])
    item = await store.get_integration_catalogue(context.tenant_id, integration_id)
    if item is None:
        raise LookupError("integration not found")
    # The scope is decided BEFORE the refusal ladder runs, because the ladder's
    # answer depends on it: asking adapter-wide would refuse a member connecting
    # their own credential because the ORG already has one.
    level = str(params.get("level") or "org")
    scope_id = "" if level == "org" else acting_owner(context)
    refusal = await integration_setup_refusal(
        store, loader, credentials, context.tenant_id, item, level, scope_id
    )
    if refusal is not None:
        raise ControlConflict(refusal)
    contract = item.secret_contract
    assert contract is not None and item.adapter_id is not None
    fields, reason = validate_integration_secret_fields(contract, params.get("secret"))
    if reason is not None or fields is None:
        raise ValueError(reason or "invalid_setup_fields")
    label = str(params["label"]).strip()
    if not 1 <= len(label) <= 200:
        raise ValueError("invalid_connection_label")

    connection_id = f"conn_{uuid.uuid4().hex}"
    credential_id = f"integration:{item.id}:{uuid.uuid4().hex}"
    # The CONNECTION is built first and the credential sealed second, because the
    # seal has to carry the row's scope_id and only __post_init__ derives it for
    # an org row. Deriving it a second time here would reintroduce exactly the
    # drift the model comment says that derivation exists to prevent.
    connection = IntegrationConnection(
        id=connection_id,
        tenant_id=context.tenant_id,
        integration_id=item.id,
        adapter_id=item.adapter_id,
        label=label,
        credential_ref=credential_id,
        credential_owned=True,
        accounts=integration_connection_accounts(contract, fields, label),
        level=level,
        scope_id=scope_id,
    )
    credential = integration_manual_secret_ref(
        item.id,
        item.adapter_id,
        contract.credential_kind,
        contract.version,
        fields,
        level=connection.level,
        scope_id=connection.scope_id,
    )
    if not await store.create_integration_connection_with_credential(connection, credential):
        raise ControlConflict("active_connection_exists")
    return Result.success(
        {"connection_id": connection_id, "integration_id": item.id, "level": connection.level}
    )


async def _revoke(
    store: Any,
    loader: Any,
    credentials: Any,
    params: dict[str, Any],
    context: Any,
) -> Result:
    await require_unchanged_approval_context(
        store, loader, "control.integration.revoke", params, context
    )
    connection_id = str(params["connection_id"])
    previous = await store.get_integration_connection(context.tenant_id, connection_id)
    if previous is None:
        raise LookupError("integration connection not found")
    if previous.level != "org" and previous.scope_id != acting_owner(context):
        # Fail-closed and checked HERE, not only at the route: the control verb
        # is reachable directly, so a route-only check is bypassable. An org
        # admin cleaning up after a departing member is not covered yet and
        # would need its own path rather than a hole in this one.
        raise ControlConflict("not_your_integration_connection")
    if previous.health == "revoked":
        return Result.success({"connection_id": connection_id})
    revoked, credential_ref, deleted = await store.revoke_integration_connection_with_credential(
        context.tenant_id, connection_id
    )
    if revoked is None:
        return Result.success({"connection_id": connection_id})
    detached = bool(
        credential_ref
        and credentials is not None
        and credentials.unbind_adapter_credential(
            context.tenant_id, previous.adapter_id, credential_ref, previous.level
        )
    )
    return Result.success(
        {
            "connection_id": connection_id,
            "integration_id": previous.integration_id,
            "credential_detached": detached,
            "owned_credential_deleted": deleted,
        }
    )


async def execute_integration_operation(
    store: Any,
    loader: Any,
    credentials: Any,
    verb: str,
    params: dict[str, Any],
    context: Any,
) -> Result | None:
    if verb == "control.integration.connect":
        return await _connect(store, loader, credentials, params, context)
    if verb == "control.integration.revoke":
        return await _revoke(store, loader, credentials, params, context)
    return None
