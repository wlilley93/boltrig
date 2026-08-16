"""Workflow and permanent-fleet schemas for the governed control surface."""

from __future__ import annotations

from typing import Any

from boltrig.adapters.base import VerbSpec
from boltrig.models import COST_TIERS

from .control_workflow_schema import WORKFLOW_DEFINITION_SCHEMA

_OBJ: dict[str, Any] = {"type": "object"}
_STRING: dict[str, Any] = {"type": "string"}
_STRINGS: dict[str, Any] = {"type": "array", "items": _STRING}


def _spec(
    verb_id: str,
    properties: dict[str, Any],
    required: tuple[str, ...],
    description: str,
    *,
    additional: bool = True,
    consequence: str = "high",
) -> VerbSpec:
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
    }
    if required:
        input_schema["required"] = list(required)
    if not additional:
        input_schema["additionalProperties"] = False
    return VerbSpec(
        verb_id=verb_id,
        noun_id="control",
        input_schema=input_schema,
        output_schema=_OBJ,
        consequence=consequence,
        description=description,
        idempotency_mode="cacheable",
    )


def _draft_lane_specs() -> list[VerbSpec]:
    """Chat-first authoring: iterate a draft freely (LOW consequence, no HITL
    hold), publish deliberately (HIGH). A draft is a non-runnable working copy
    under a reserved id prefix - never on the runnable shelf, never triggerable
    - so the approval-per-edit cost falls only on publish."""
    return [
        _spec(
            "control.workflow.draft.upsert",
            {
                "id": _STRING,
                "definition": WORKFLOW_DEFINITION_SCHEMA,
                "intent_tags": _STRINGS,
            },
            ("id",),
            "Save a non-runnable draft of a workflow definition (low-consequence iteration)",
            additional=False,
            consequence="low",
        ),
        _spec(
            "control.workflow.publish",
            {"id": _STRING, "version": _STRING},
            ("id",),
            "Promote a saved draft to a runnable workflow version (approval binds to the draft)",
            additional=False,
        ),
    ]


def workflow_specs() -> list[VerbSpec]:
    specs = [
        _spec(
            "control.workflow.upsert",
            {
                "id": _STRING,
                "version": _STRING,
                "definition": WORKFLOW_DEFINITION_SCHEMA,
                "intent_tags": _STRINGS,
            },
            ("id",),
            "Author or replace a workspace-scoped workflow definition; provenance is kernel-owned",
            additional=False,
        ),
        _spec(
            "control.workflow.schedule",
            {"workflow_id": _STRING, "cron": _STRING, "timezone": _STRING},
            ("workflow_id", "cron"),
            "Validate and persist a workflow cron schedule",
        ),
        _spec(
            "control.workflow.schedule_occurrence.retry",
            {
                "workflow_id": _STRING,
                "scheduled_for": _STRING,
                "run_id": _STRING,
            },
            ("workflow_id", "scheduled_for", "run_id"),
            "Retry one exact terminal failed schedule occurrence under its original snapshots",
            additional=False,
        ),
        *[
            _spec(
                f"control.workflow.{action}",
                {"workflow_id": _STRING},
                ("workflow_id",),
                f"{action.title()} a stored workflow without deleting it",
            )
            for action in ("unschedule", "archive", "restore")
        ],
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
    specs.extend(_draft_lane_specs())
    specs.append(
        _spec(
            "control.workflow.trigger_binding.create",
            {
                "workflow_id": _STRING,
                "name": _STRING,
                "source": {"type": "string", "enum": ["webhook", "channel"]},
                "channel_id": _STRING,
            },
            ("workflow_id", "name", "source"),
            "Approve and bind an authenticated event source to a workflow",
            additional=False,
        )
    )
    specs.extend(
        _spec(
            f"control.workflow.trigger_binding.{action}",
            {"workflow_id": _STRING, "trigger_id": _STRING},
            ("workflow_id", "trigger_id"),
            f"{action.title()} an approved workflow event-source binding",
            additional=False,
        )
        for action in ("enable", "disable", "rotate")
    )
    return specs


def permanent_fleet_specs() -> list[VerbSpec]:
    nullable_integer = {"type": ["integer", "null"], "minimum": 0}
    budget = {
        "type": ["object", "null"],
        "properties": {
            "token_limit": nullable_integer,
            "cost_limit_micros": nullable_integer,
            "hard_stop": {"type": "boolean"},
            "window": {
                "type": "string",
                "enum": ["run", "daily", "monthly"],
            },
        },
        "additionalProperties": False,
    }
    head = {
        "type": "object",
        "properties": {
            "name": _STRING,
            "routing_id": _STRING,
            "purpose": _STRING,
            "brief": _STRING,
            "runtime": {"type": "string", "enum": ["codex", "script"]},
            "model_endpoint": {"type": ["string", "null"]},
            "supported_skills": _STRINGS,
            "max_depth": {"type": "integer", "minimum": 1, "maximum": 5},
            "cost_tier": {"type": "string", "enum": list(COST_TIERS)},
            "budget": budget,
        },
        "required": [
            "name",
            "routing_id",
            "purpose",
            "runtime",
            "supported_skills",
            "max_depth",
            "cost_tier",
        ],
        "additionalProperties": False,
    }
    hierarchy = {
        "type": "object",
        "properties": {
            "chief": head,
            "departments": {
                "type": "array",
                "items": head,
                "minItems": 1,
                "maxItems": 32,
            },
        },
        "required": ["chief", "departments"],
        "additionalProperties": False,
    }
    return [
        _spec(
            "control.permanent_fleet.apply",
            {"hierarchy": hierarchy},
            ("hierarchy",),
            "Version a closed permanent-fleet hierarchy; restart required until a worker observes it",
            additional=False,
        )
    ]
