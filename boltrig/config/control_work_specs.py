"""Governed Work-item lifecycle verb schemas."""

from __future__ import annotations

from typing import Any

from boltrig.adapters.base import VerbSpec

_STRING: dict[str, Any] = {"type": "string", "minLength": 1, "maxLength": 200}
_NULLABLE_STRING: dict[str, Any] = {
    "type": ["string", "null"],
    "minLength": 1,
    "maxLength": 200,
}


def _spec(
    verb_id: str,
    properties: dict[str, Any],
    required: list[str],
    description: str,
    *,
    consequence: str,
) -> VerbSpec:
    return VerbSpec(
        verb_id=verb_id,
        noun_id="control",
        input_schema={
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        },
        output_schema={"type": "object"},
        consequence=consequence,
        description=description,
    )


def work_specs() -> list[VerbSpec]:
    return [
        _spec(
            "control.work.create",
            {
                "intent": {"type": "string", "minLength": 1, "maxLength": 4000},
                "owner_member": {
                    "type": ["string", "null"],
                    "maxLength": 200,
                },
                "parent_id": _NULLABLE_STRING,
                "confidence": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1,
                },
                "convergent": {"type": "boolean"},
            },
            ["intent"],
            (
                "Create a canonical internal Work item in the active workspace. "
                "The fleet may claim and execute pending work, so creation requires "
                "an exact human approval."
            ),
            consequence="high",
        ),
        _spec(
            "control.work.assign",
            {"item_id": _STRING, "owner_member": _NULLABLE_STRING},
            ["item_id", "owner_member"],
            "Assign or unassign a visible Work item",
            consequence="low",
        ),
        _spec(
            "control.work.status",
            {
                "item_id": _STRING,
                "status": {
                    "type": "string",
                    "enum": [
                        "pending",
                        "blocked",
                        "awaiting_human",
                        "done",
                        "failed",
                        "cancelled",
                    ],
                },
            },
            ["item_id", "status"],
            "Apply an approved legal manual Work status transition",
            consequence="high",
        ),
        _spec(
            "control.work.reparent",
            {"item_id": _STRING, "parent_id": _NULLABLE_STRING},
            ["item_id", "parent_id"],
            "Reparent a Work subtree after approval and invariant validation",
            consequence="high",
        ),
    ]
