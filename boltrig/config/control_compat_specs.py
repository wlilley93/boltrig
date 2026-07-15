"""Schemas for legacy HTTP mutations now backed by governed control verbs."""

from __future__ import annotations

from typing import Any

from boltrig.adapters.base import VerbSpec

_OBJ: dict[str, Any] = {"type": "object"}
_STRING: dict[str, Any] = {"type": "string"}
_STRINGS: dict[str, Any] = {"type": "array", "items": _STRING}
_BOOL: dict[str, Any] = {"type": "boolean"}
_INT: dict[str, Any] = {"type": "integer"}


def _spec(
    verb_id: str,
    properties: dict[str, Any],
    required: tuple[str, ...],
    description: str,
    *,
    idempotency_mode: str = "cacheable",
) -> VerbSpec:
    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = list(required)
    return VerbSpec(
        verb_id=verb_id,
        noun_id="control",
        input_schema=schema,
        output_schema=_OBJ,
        consequence="high",
        description=description,
        idempotency_mode=idempotency_mode,
    )


def _tenancy_specs() -> list[VerbSpec]:
    return [
        _spec(
            "control.ai_key.set",
            {
                "level": _STRING,
                "scope_id": _STRING,
                "provider": _STRING,
                "model": _STRING,
                "api_key": _STRING,
                "base_url": _STRING,
            },
            ("level", "scope_id", "provider", "model", "api_key"),
            "Set a scoped model-provider key through the sealed credential store",
        ),
        _spec(
            "control.ai_key.delete",
            {"level": _STRING, "scope_id": _STRING},
            ("level", "scope_id"),
            "Delete a scoped model-provider key and clear its sealed credential",
        ),
        _spec(
            "control.org.update",
            {
                "name": _STRING,
                "slug": _STRING,
                "settings": _OBJ,
                "allow_own_ai_keys": _BOOL,
                "require_two_factor": _BOOL,
            },
            (),
            "Update the authenticated principal's organisation settings",
        ),
        _spec(
            "control.workspace.create",
            {"name": _STRING, "settings": _OBJ},
            ("name",),
            "Create a workspace and seat the authenticated creator as owner",
        ),
        _spec(
            "control.workspace.update",
            {
                "workspace_id": _STRING,
                "name": _STRING,
                "settings": _OBJ,
                "status": {"type": "string", "enum": ["active", "archived"]},
            },
            ("workspace_id",),
            "Update a workspace managed by the authenticated principal",
        ),
        _spec(
            "control.workspace.member.add",
            {
                "workspace_id": _STRING,
                "user_id": _STRING,
                "role": _STRING,
                "permissions": _OBJ,
            },
            ("workspace_id", "user_id"),
            "Add or update a member in a managed workspace",
        ),
        _spec(
            "control.workspace.member.remove",
            {"workspace_id": _STRING, "user_id": _STRING},
            ("workspace_id", "user_id"),
            "Remove a member from a managed workspace",
        ),
    ]


def _channel_specs() -> list[VerbSpec]:
    configuration = {
        "name": _STRING,
        "config": _OBJ,
        "enabled": _BOOL,
        "unpaired_behavior": _STRING,
    }
    binding = {
        "channel_id": _STRING,
        "external_user_id": _STRING,
        "subject": _STRING,
        "role": _STRING,
    }
    return [
        _spec(
            "control.channel.connect",
            {"platform": _STRING, "signing_secret": _STRING, **configuration},
            ("platform", "name"),
            "Connect a governed inbound messaging channel",
        ),
        _spec(
            "control.channel.configure",
            {"channel_id": _STRING, **configuration},
            ("channel_id",),
            "Configure a governed messaging channel",
        ),
        _spec(
            "control.channel.disconnect",
            {"channel_id": _STRING},
            ("channel_id",),
            "Disconnect a governed messaging channel",
        ),
        _spec(
            "control.channel.pair",
            {**binding, "ttl_minutes": _INT},
            ("channel_id", "external_user_id", "subject"),
            "Issue a one-time pairing code for an external sender",
            idempotency_mode="disabled",
        ),
        _spec(
            "control.channel.bind",
            binding,
            ("channel_id", "external_user_id", "subject"),
            "Bind an external sender directly to an internal identity",
        ),
        _spec(
            "control.channel.unbind",
            {"channel_id": _STRING, "binding_id": _STRING},
            ("channel_id", "binding_id"),
            "Remove an external-sender binding from a channel",
        ),
    ]


def compatibility_specs() -> list[VerbSpec]:
    """Compatibility writes use the same high-consequence policy as control APIs."""
    return [
        *_tenancy_specs(),
        *_channel_specs(),
        _spec(
            "control.eval_case.upsert",
            {
                "id": _STRING,
                "target_kind": _STRING,
                "target_ref": _STRING,
                "input": _OBJ,
                "assertions": _OBJ,
                "labels": _STRINGS,
            },
            ("target_kind", "target_ref"),
            "Create or replace an author-scoped evaluation case",
        ),
    ]
