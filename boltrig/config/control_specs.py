"""Schemas for the governed ``control.*`` surface.

Keeping the declarative verb catalogue separate leaves the adapter focused on
execution and makes additions reviewable without growing another monolith.
"""

from __future__ import annotations

from typing import Any

from boltrig.adapters.base import VerbSpec
from boltrig.models import COST_TIERS

from .control_workflow_specs import permanent_fleet_specs, workflow_specs

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
                "cost_tier": {"type": "string", "enum": list(COST_TIERS)},
                "model_endpoint": _STRING,
            },
            ("name", "runtime"),
            "Author or replace an agent capability profile",
        ),
        *[
            _spec(
                f"control.capability.{action}",
                {"name": _STRING},
                ("name",),
                f"{action.title()} an agent capability without deleting it",
                additional=False,
            )
            for action in ("retire", "restore")
        ],
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
        *[
            _spec(
                f"control.model_endpoint.{action}",
                {"id": _STRING},
                ("id",),
                f"{action.title()} a model endpoint without deleting its configuration",
                additional=False,
            )
            for action in ("retire", "restore")
        ],
    ]


def _registry_specs() -> list[VerbSpec]:
    from .control_registry_specs import registry_specs

    return registry_specs()


def _mcp_registration_spec() -> VerbSpec:
    return _spec(
        "control.mcp_server.register",
        {
            "id": _STRING,
            "url": _STRING,
            # Reviewed SEC-61 waiver for an operator-vetted internal server.
            "allow_internal": {"type": "boolean"},
            # References name secret-store keys; raw material has no field.
            "credential_ref": _STRING,
            "credential_id": _STRING,
            "credential_store": _STRING,
            "credential_kind": _STRING,
        },
        ("id", "url"),
        "Register an external MCP server, inert until human review",
        consequence="low",
        additional=False,
    )


def _mcp_update_spec() -> VerbSpec:
    return _spec(
        "control.mcp_server.update",
        {
            "server_id": _STRING,
            "url": {"type": "string", "maxLength": 2048},
            "allow_internal": {"type": "boolean"},
            "credential_mode": {
                "type": "string",
                "enum": ["preserve", "replace", "remove"],
            },
            "credential_ref": {"type": "string", "maxLength": 1024},
            "credential_id": {"type": "string", "maxLength": 200},
            "credential_store": {"type": "string", "maxLength": 100},
            "credential_kind": {"type": "string", "maxLength": 100},
        },
        ("server_id", "url", "allow_internal", "credential_mode"),
        "Replace an inactive MCP server configuration and require re-probing",
        additional=False,
    )


def _mcp_lifecycle_specs() -> list[VerbSpec]:
    descriptions = {
        "probe": "Probe an MCP server and retain a bounded discovery receipt",
        "activate": "Activate an inactive MCP server from its approved tool snapshot",
        "deactivate": "Deactivate an MCP server while preserving its published tool snapshot",
        "retire": "Retire an inactive MCP server without deleting its history",
        "restore": "Restore a retired MCP server to inactive state",
        "delete": "Delete a non-active MCP server and its retained history",
    }
    return [
        _spec(
            f"control.mcp_server.{action}",
            {"server_id": _STRING},
            ("server_id",),
            description,
            additional=False,
        )
        for action, description in descriptions.items()
    ]


def _adapter_specs() -> list[VerbSpec]:
    lifecycle = (
        ("activate", "Activate a reviewed adapter and publish its verb bindings"),
        (
            "deactivate",
            "Suspend a live adapter and unpublish its verbs pending re-review",
        ),
        (
            "delete",
            "Delete a non-live adapter with its registry rows and credential ref",
        ),
    )
    return [
        _spec(
            "control.adapter.generate",
            {"adapter_id": _STRING, "spec": _OBJ},
            ("adapter_id", "spec"),
            "Generate and register an inert adapter from an OpenAPI document",
            consequence="low",
        ),
        *[
            _spec(
                f"control.adapter.{action}",
                {"adapter_id": _STRING},
                ("adapter_id",),
                description,
            )
            for action, description in lifecycle
        ],
        _mcp_registration_spec(),
        _mcp_update_spec(),
        *_mcp_lifecycle_specs(),
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
            additional=False,
        ),
        _spec(
            "control.notification.test",
            {"id": _STRING},
            ("id",),
            "Queue a static test to the delegated user's verified notification route",
            consequence="low",
            additional=False,
            idempotency_mode="disabled",
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
    from .control_work_specs import work_specs

    return [
        *workflow_specs(),
        *_profile_specs(),
        *permanent_fleet_specs(),
        *_registry_specs(),
        *_adapter_specs(),
        *_administration_specs(),
        *_budget_specs(),
        *work_specs(),
        *compatibility_specs(),
    ]
