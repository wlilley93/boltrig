"""Prepared, approval-safe external-MCP registration amendments and deletion."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal, cast
from urllib.parse import urlsplit

from boltrig.adapters.base import Result
from boltrig.models import InvocationContext, utcnow
from boltrig.store.mcp_lifecycle import (
    McpCredentialAmendment,
)

from .control_mcp import _validated_mcp_url
from .control_rehydrate import consumer_spec, reconcile_mcp_adapter
from .control_safety import ControlConflict

_CREDENTIAL_FIELDS = frozenset(
    {
        "credential_ref",
        "credential_id",
        "credential_store",
        "credential_kind",
    }
)
CredentialMode = Literal["preserve", "replace", "remove"]


def safe_digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class PreparedMcpAmendment:
    spec_ref: str
    credential_amendment: McpCredentialAmendment
    requested_config: dict[str, Any]


@dataclass(frozen=True)
class ApprovedMcpMutation:
    created_at: datetime
    updated_at: datetime
    revision: int
    spec_digest: str
    credential_digest: str | None
    state: str


async def effective_mcp_credential_id(
    store: Any, tenant_id: str, record: Any
) -> str | None:
    spec = consumer_spec(record.spec_ref)
    if spec["credential_binding_explicit"]:
        return spec["credential_id"]
    legacy_id = f"{record.id}-mcp-token"
    return legacy_id if await store.has_credential_ref(tenant_id, legacy_id) else None


def _credential_fields_present(params: dict[str, Any]) -> bool:
    return any(field in params for field in _CREDENTIAL_FIELDS)


def _amendment_inputs(
    params: dict[str, Any], current_config_revision: int
) -> tuple[str, bool, CredentialMode]:
    if type(current_config_revision) is not int or current_config_revision < 1:
        raise ControlConflict("invalid MCP configuration revision")
    url = _validated_mcp_url(params.get("url"))
    allow_internal = params.get("allow_internal")
    mode_value = str(params.get("credential_mode") or "")
    if type(allow_internal) is not bool:
        raise ControlConflict("MCP allow_internal must be boolean")
    if mode_value not in {"preserve", "replace", "remove"}:
        raise ControlConflict("invalid MCP credential amendment mode")
    return url, allow_internal, cast(CredentialMode, mode_value)


def _credential_amendment(
    record: Any,
    params: dict[str, Any],
    mode: CredentialMode,
    current_id: str | None,
    current_config_revision: int,
) -> tuple[McpCredentialAmendment, str | None, dict[str, str] | None]:
    if mode != "replace":
        if _credential_fields_present(params):
            raise ControlConflict(
                "credential fields are only valid in replace mode"
            )
        final_id = current_id if mode == "preserve" else None
        return McpCredentialAmendment(mode), final_id, None
    ref = params.get("credential_ref")
    if not isinstance(ref, str) or not ref.strip():
        raise ControlConflict(
            "replacement MCP credential reference is required"
        )
    requested_id = params.get("credential_id")
    if requested_id is not None and not isinstance(requested_id, str):
        raise ControlConflict("replacement MCP credential id is invalid")
    credential_id = (
        requested_id
        if requested_id is not None
        else f"{record.id}-mcp-token-r{current_config_revision + 1}"
    )
    metadata = {
        "store": str(params.get("credential_store") or "env"),
        "ref": ref,
        "kind": str(params.get("credential_kind") or "api_key"),
    }
    try:
        amendment = McpCredentialAmendment(
            "replace", credential_id, metadata
        )
    except ValueError as exc:
        raise ControlConflict("invalid MCP credential replacement") from exc
    return (
        amendment,
        credential_id,
        dict(amendment.credential_metadata or {}),
    )


def _prepared_amendment(
    url: str,
    allow_internal: bool,
    mode: CredentialMode,
    amendment: McpCredentialAmendment,
    final_credential_id: str | None,
    metadata: dict[str, str] | None,
) -> PreparedMcpAmendment:
    spec_ref = json.dumps(
        {
            "url": url,
            "allow_internal": allow_internal,
            "credential_id": final_credential_id,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    parsed = urlsplit(url)
    hostname = parsed.hostname or ""
    shown_host = f"[{hostname}]" if ":" in hostname else hostname
    origin = f"{parsed.scheme.lower()}://{shown_host}"
    if parsed.port is not None:
        origin = f"{origin}:{parsed.port}"
    digest = safe_digest(
        {
            "spec_ref": spec_ref,
            "credential_mode": mode,
            "credential_metadata": metadata,
        }
    )
    return PreparedMcpAmendment(
        spec_ref,
        amendment,
        {
            "endpoint": {
                "origin": origin,
                "path_redacted": bool((parsed.path or "").strip("/")),
                "internal_egress_allowed": allow_internal,
            },
            "credential_mode": mode,
            "credential_configured": final_credential_id is not None,
            "digest": digest,
        },
    )


async def prepare_mcp_amendment(
    store: Any,
    tenant_id: str,
    record: Any,
    params: dict[str, Any],
    *,
    current_config_revision: int,
) -> PreparedMcpAmendment:
    url, allow_internal, mode = _amendment_inputs(
        params, current_config_revision
    )
    current_id = await effective_mcp_credential_id(
        store, tenant_id, record
    )
    amendment, final_id, metadata = _credential_amendment(
        record,
        params,
        mode,
        current_id,
        current_config_revision,
    )
    return _prepared_amendment(
        url,
        allow_internal,
        mode,
        amendment,
        final_id,
        metadata,
    )


def _approved_server(context: InvocationContext) -> dict[str, Any]:
    resource = context.extra.get("approval_resource_context")
    server = resource.get("mcp_server") if isinstance(resource, dict) else None
    if not isinstance(server, dict):
        raise PermissionError("approved MCP resource snapshot is missing")
    return server


def _changed_at_after(value: datetime) -> datetime:
    now = utcnow()
    return now if now > value else value + timedelta(microseconds=1)


def _approved_mutation(context: InvocationContext) -> ApprovedMcpMutation:
    approved = _approved_server(context)
    try:
        credential_digest = approved["credential_config_digest"]
        if credential_digest is not None and not isinstance(
            credential_digest, str
        ):
            raise TypeError
        return ApprovedMcpMutation(
            created_at=datetime.fromisoformat(
                str(approved["lifecycle_created_at"])
            ),
            updated_at=datetime.fromisoformat(
                str(approved["lifecycle_updated_at"])
            ),
            revision=int(approved["config_revision"]),
            spec_digest=str(approved["mcp_spec_digest"]),
            credential_digest=credential_digest,
            state=str(approved["state"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise PermissionError(
            "approved MCP resource generations are invalid"
        ) from exc


async def _execute_mcp_update(
    store: Any,
    loader: Any,
    credentials: Any,
    params: dict[str, Any],
    context: InvocationContext,
    record: Any,
    approved: ApprovedMcpMutation,
    changed_at: datetime,
) -> Result:
    prepared = await prepare_mcp_amendment(
        store,
        context.tenant_id,
        record,
        params,
        current_config_revision=approved.revision,
    )
    result = await store.amend_mcp_server_registration(
        context.tenant_id,
        record.id,
        expected_state=approved.state,
        expected_created_at=approved.created_at,
        expected_updated_at=approved.updated_at,
        expected_spec_digest=approved.spec_digest,
        expected_credential_config_digest=approved.credential_digest,
        expected_config_revision=approved.revision,
        spec_ref=prepared.spec_ref,
        changed_at=changed_at,
        credential_amendment=prepared.credential_amendment,
    )
    if result is None:
        raise ControlConflict("MCP registration changed during amendment")
    credentials.replace_adapter_credential_binding(
        context.tenant_id, record.id, result.current_credential_id
    )
    loader.unload(context.tenant_id, record.id)
    await reconcile_mcp_adapter(
        store, credentials, loader, context.tenant_id, result.adapter
    )
    return Result.success(
        {
            "id": record.id,
            "state": "inert",
            "updated": True,
            "reprobe_required": True,
            "config_revision": result.lifecycle.config_revision,
        }
    )


async def _execute_mcp_delete(
    store: Any,
    loader: Any,
    credentials: Any,
    context: InvocationContext,
    record: Any,
    approved: ApprovedMcpMutation,
    changed_at: datetime,
) -> Result:
    result = await store.delete_mcp_server_registration(
        context.tenant_id,
        record.id,
        expected_state=approved.state,
        expected_created_at=approved.created_at,
        expected_updated_at=approved.updated_at,
        expected_spec_digest=approved.spec_digest,
        expected_credential_config_digest=approved.credential_digest,
        expected_config_revision=approved.revision,
        changed_at=changed_at,
    )
    if result is None:
        raise ControlConflict("MCP registration changed during deletion")
    loader.unload(context.tenant_id, record.id)
    credentials.replace_adapter_credential_binding(
        context.tenant_id, record.id, None
    )
    return Result.success({"id": record.id, "deleted": True})


async def execute_mcp_registration_mutation(
    store: Any,
    loader: Any,
    credentials: Any,
    verb: str,
    params: dict[str, Any],
    context: InvocationContext,
    record: Any,
) -> Result:
    approved = _approved_mutation(context)
    changed_at = _changed_at_after(approved.updated_at)
    if verb == "control.mcp_server.update":
        return await _execute_mcp_update(
            store,
            loader,
            credentials,
            params,
            context,
            record,
            approved,
            changed_at,
        )
    return await _execute_mcp_delete(
        store,
        loader,
        credentials,
        context,
        record,
        approved,
        changed_at,
    )


__all__ = [
    "ApprovedMcpMutation",
    "PreparedMcpAmendment",
    "effective_mcp_credential_id",
    "execute_mcp_registration_mutation",
    "prepare_mcp_amendment",
    "safe_digest",
]
