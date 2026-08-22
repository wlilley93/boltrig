"""Schemas for legacy HTTP mutations now backed by governed control verbs."""

from __future__ import annotations

from typing import Any

from boltrig.adapters.base import VerbSpec
from boltrig.models import EVAL_TARGET_KINDS

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
    consequence: str = "high",
    idempotency_mode: str = "cacheable",
    additional: bool = True,
) -> VerbSpec:
    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = list(required)
    if not additional:
        schema["additionalProperties"] = False
    return VerbSpec(
        verb_id=verb_id,
        noun_id="control",
        input_schema=schema,
        output_schema=_OBJ,
        consequence=consequence,
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
                "base_url": _STRING,
                "modality": {"type": "string", "enum": ["text", "vision"]},
                "proposal_id": _STRING,
                "secret_digest": _STRING,
            },
            (
                "level",
                "scope_id",
                "provider",
                "model",
                "proposal_id",
                "secret_digest",
            ),
            "Consume one caller-bound envelope-sealed AI-key proposal",
            additional=False,
        ),
        _spec(
            "control.ai_key.delete",
            {
                "level": _STRING,
                "scope_id": _STRING,
                "modality": {"type": "string", "enum": ["text", "vision"]},
            },
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
                "allow_own_integration_credentials": _BOOL,
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
    credential_refs = {
        "type": "object",
        "additionalProperties": {"type": "string", "minLength": 1},
    }
    configuration = {
        "name": _STRING,
        "config": _OBJ,
        "provider_config": _OBJ,
        "credential_refs": credential_refs,
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
            {
                "platform": _STRING,
                # Legacy webhook compatibility only. Socket providers refuse it.
                "signing_secret": _STRING,
                "signing_secret_ref": _STRING,
                **configuration,
            },
            ("platform", "name"),
            "Connect a governed channel using provider-specific secret-store references",
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
        _spec(
            "control.channel.delivery.retry",
            {
                "channel_id": _STRING,
                "message_id": _STRING,
                "expected_updated_at": _STRING,
            },
            ("channel_id", "message_id", "expected_updated_at"),
            "Retry one exact terminal failed channel delivery after configuration repair",
            additional=False,
        ),
    ]


def compatibility_specs() -> list[VerbSpec]:
    """Compatibility writes are high consequence except explicit inert/intake seams."""
    return [
        *_tenancy_specs(),
        *_channel_specs(),
        _spec(
            "control.integration.connect",
            {
                "integration_id": _STRING,
                "label": _STRING,
                # The provider-specific closed contract is enforced again by
                # the adapter. This secret-shaped key makes the dispatcher
                # redact the entire submitted contract from projections.
                "secret": _OBJ,
                # Whose credential this is: "org" (default) or "user". There is
                # deliberately no scope_id here -- identity is
                # authenticated-by-construction (K-3), so the kernel derives the
                # owner from the caller rather than believing the request.
                "level": _STRING,
            },
            ("integration_id", "label", "secret"),
            "Seal a certified provider contract and bind one integration connection",
            consequence="low",
            additional=False,
            idempotency_mode="disabled",
        ),
        _spec(
            "control.integration.revoke",
            {"connection_id": _STRING},
            ("connection_id",),
            "Revoke an integration connection and detach its owned credential reference",
            additional=False,
        ),
        _spec(
            "control.integration.revoke_member",
            {"connection_id": _STRING},
            ("connection_id",),
            "Revoke another member's personal integration connection as an administrator",
            additional=False,
        ),
        _spec(
            "control.eval_case.archive",
            {"id": _STRING},
            ("id",),
            "Archive an evaluation case without deleting its fixture or run history",
            additional=False,
        ),
        _spec(
            "control.eval_case.restore",
            {"id": _STRING},
            ("id",),
            "Restore an archived evaluation case",
            additional=False,
        ),
        _spec(
            "control.eval_case.upsert",
            {
                "id": _STRING,
                "target_kind": {
                    "type": "string",
                    "enum": list(EVAL_TARGET_KINDS),
                },
                "target_ref": {
                    "type": "string",
                    "minLength": 1,
                    "pattern": r".*\S.*",
                },
                "input": _OBJ,
                "assertions": _OBJ,
                "labels": _STRINGS,
            },
            ("target_kind", "target_ref"),
            "Create or replace an author-scoped evaluation case",
        ),
    ]
