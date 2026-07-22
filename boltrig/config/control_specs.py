"""Schemas for the governed ``control.*`` surface.

Keeping the declarative verb catalogue separate leaves the adapter focused on
execution and makes additions reviewable without growing another monolith.
"""

from __future__ import annotations

from typing import Any

from boltrig.adapters.base import VerbSpec

_OBJ: dict[str, Any] = {"type": "object"}
_STRING: dict[str, Any] = {"type": "string"}
_STRINGS: dict[str, Any] = {"type": "array", "items": _STRING}


def _input(
    properties: dict[str, Any],
    required: tuple[str, ...] = (),
    *,
    additional: bool = True,
) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = list(required)
    if not additional:
        schema["additionalProperties"] = False
    return schema


def _spec(
    verb_id: str,
    properties: dict[str, Any],
    required: tuple[str, ...],
    description: str,
    *,
    consequence: str = "high",
    additional: bool = True,
    idempotency_mode: str = "cacheable",
) -> VerbSpec:
    return VerbSpec(
        verb_id=verb_id,
        noun_id="control",
        input_schema=_input(properties, required, additional=additional),
        output_schema=_OBJ,
        consequence=consequence,
        description=description,
        idempotency_mode=idempotency_mode,
    )


def _workflow_specs() -> list[VerbSpec]:
    return [
        _spec(
            "control.workflow.upsert",
            {
                "id": _STRING,
                "version": _STRING,
                "source": _STRING,
                "definition": _OBJ,
                "intent_tags": _STRINGS,
            },
            ("id",),
            "Author or replace a workspace-scoped workflow definition",
        ),
        _spec(
            "control.workflow.schedule",
            {"workflow_id": _STRING, "cron": _STRING, "timezone": _STRING},
            ("workflow_id", "cron"),
            "Validate and persist a workflow cron schedule",
        ),
        _spec(
            "control.workflow.trigger",
            {"workflow_id": _STRING, "inputs": _OBJ},
            ("workflow_id",),
            "Queue a stored workflow on the configured executor",
        ),
        _spec(
            "control.workflow.execute",
            {"workflow_id": _STRING, "inputs": _OBJ},
            ("workflow_id",),
            "Execute a stored workflow through governed step dispatch",
        ),
    ]


def _profile_specs() -> list[VerbSpec]:
    return [
        _spec(
            "control.capability.upsert",
            {
                "name": _STRING,
                "runtime": _STRING,
                "supported_skills": _STRINGS,
                "max_depth": {"type": "integer"},
                "is_ephemeral": {"type": "boolean"},
                "cost_tier": _STRING,
                "model_endpoint": _STRING,
            },
            ("name", "runtime"),
            "Author or replace an agent capability profile",
        ),
        _spec(
            "control.model_endpoint.upsert",
            {
                "id": _STRING,
                "kind": _STRING,
                "model": _STRING,
                "base_url": _STRING,
                "fallback": _STRING,
                "data_class": _STRING,
            },
            ("id", "kind", "model"),
            "Author or replace a model endpoint",
        ),
    ]


def _registry_specs() -> list[VerbSpec]:
    return [
        _spec(
            "control.skill.upsert",
            {
                "id": _STRING,
                "version": _STRING,
                "prompt_fragment": _STRING,
                "tool_grants": _STRINGS,
                "context_requirements": _OBJ,
                "extends": _STRING,
                "locale": _STRING,
            },
            ("id",),
            "Author or replace a skill",
        ),
        _spec(
            "control.noun.define",
            {"id": _STRING, "description": _STRING, "schema": _OBJ},
            ("id",),
            "Define or replace a noun",
        ),
        _spec(
            "control.verb.define",
            {
                "id": _STRING,
                "noun_id": _STRING,
                "input_schema": _OBJ,
                "output_schema": _OBJ,
                "description": _STRING,
                "consequence": {"type": "string", "enum": ["low", "high"]},
                "idempotency_mode": {"type": "string", "enum": ["cacheable", "disabled"]},
            },
            ("id", "noun_id"),
            "Define or replace a verb with safe consequence defaults",
        ),
        _spec(
            "control.binding.set",
            {
                "verb_id": _STRING,
                "target_type": {"type": "string", "enum": ["adapter", "agent"]},
                "target_ref": _STRING,
            },
            ("verb_id", "target_type", "target_ref"),
            "Bind a verb to an adapter or reasoning-agent profile",
        ),
    ]


def _adapter_specs() -> list[VerbSpec]:
    return [
        _spec(
            "control.adapter.generate",
            {"adapter_id": _STRING, "spec": _OBJ},
            ("adapter_id", "spec"),
            "Generate and register an inert adapter from an OpenAPI document",
            consequence="low",
        ),
        _spec(
            "control.adapter.activate",
            {"adapter_id": _STRING},
            ("adapter_id",),
            "Activate a reviewed adapter and publish its verb bindings",
        ),
        _spec(
            "control.mcp_server.register",
            {
                "id": _STRING,
                "url": _STRING,
                # credential params NAME a secret-store key (bind_mcp_credential);
                # raw secret material has no param here and stays refused.
                "credential_ref": _STRING,
                "credential_id": _STRING,
                "credential_store": _STRING,
                "credential_kind": _STRING,
            },
            ("id",),
            "Register an external MCP server, inert until human review",
            consequence="low",
            additional=False,
        ),
    ]


def _administration_specs() -> list[VerbSpec]:
    return [
        _spec(
            "control.config.upsert",
            {"section": _STRING, "value": {}},
            ("section", "value"),
            "Update a manifest section and record a revision",
        ),
        _spec(
            "control.config.rollback",
            {"section": _STRING, "revision_id": {"type": "integer"}},
            ("section", "revision_id"),
            "Restore a prior manifest-section revision",
        ),
        _spec(
            "control.user.update",
            {
                "user_id": _STRING,
                "role": _STRING,
                "scope": _OBJ,
                "status": _STRING,
            },
            ("user_id",),
            "Update a user below the authenticated principal's authority ceiling",
        ),
        _spec(
            "control.user.deactivate",
            {"user_id": _STRING},
            ("user_id",),
            "Deactivate a user and immediately revoke their access",
        ),
        _spec(
            "control.invitation.create",
            {
                "email": _STRING,
                "role": _STRING,
                "scope": _OBJ,
                "ttl_days": {"type": "integer"},
                "workspace_id": _STRING,
                "provision_workspace_name": _STRING,
                "provision_org_name": _STRING,
            },
            ("email",),
            "Create an expiring, single-use invitation below the caller's ceiling",
            idempotency_mode="disabled",
        ),
        _spec(
            "control.invitation.revoke",
            {"invite_id": _STRING},
            ("invite_id",),
            "Revoke a pending invitation before it is accepted",
            idempotency_mode="disabled",
        ),
        _spec(
            "control.notification.route",
            {
                "id": _STRING,
                "event_type": _STRING,
                "channel": _STRING,
                "target": _STRING,
                "enabled": {"type": "boolean"},
            },
            ("event_type", "channel"),
            "Create or update the delegated user's notification route",
        ),
    ]


def _budget_specs() -> list[VerbSpec]:
    non_negative = {"type": "integer", "minimum": 0}
    return [
        _spec(
            "control.budget.upsert",
            {
                "scope_type": {
                    "type": "string",
                    "enum": ["tenant", "department", "workflow"],
                },
                "scope_id": _STRING,
                "token_limit": non_negative,
                "cost_limit_micros": non_negative,
                "hard_stop": {"type": "boolean"},
                "window": {
                    "type": "string",
                    "enum": ["run", "daily", "monthly"],
                },
            },
            ("scope_type", "scope_id"),
            "Create or replace a budget policy while preserving usage counters",
            additional=False,
        ),
        _spec(
            "control.budget.reset",
            {
                "scope_type": {
                    "type": "string",
                    "enum": ["tenant", "department", "workflow"],
                },
                "scope_id": _STRING,
                "reason": _STRING,
                "reset_tokens": {"type": "boolean"},
                "reset_cost": {"type": "boolean"},
            },
            ("scope_type", "scope_id", "reason"),
            "Reset selected budget usage counters with an audited reason",
            additional=False,
            idempotency_mode="disabled",
        ),
    ]


def control_specs() -> list[VerbSpec]:
    """Return the complete caller-discoverable control-plane verb catalogue."""
    from .control_compat_specs import compatibility_specs

    return [
        *_workflow_specs(),
        *_profile_specs(),
        *_registry_specs(),
        *_adapter_specs(),
        *_administration_specs(),
        *_budget_specs(),
        *compatibility_specs(),
    ]
