"""Declarative skill, noun, verb and binding control specs."""

from boltrig.adapters.base import VerbSpec

from .control_specs import _OBJ, _STRING, _STRINGS, _spec


def _skill_noun_specs() -> list[VerbSpec]:
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
                "description": _STRING,
            },
            ("id",),
            "Author or replace a skill",
        ),
        *[
            _spec(
                f"control.skill.{action}",
                {"id": _STRING},
                ("id",),
                f"{action.title()} a skill without deleting any version",
                additional=False,
            )
            for action in ("archive", "restore")
        ],
        _spec(
            "control.noun.define",
            {"id": _STRING, "description": _STRING, "schema": _OBJ},
            ("id",),
            "Define or replace a noun",
        ),
        *[
            _spec(
                f"control.noun.{action}",
                {"id": _STRING},
                ("id",),
                f"{action.title()} a noun without deleting its verbs",
                additional=False,
            )
            for action in ("archive", "restore")
        ],
    ]


def _verb_binding_specs() -> list[VerbSpec]:
    return [
        _spec(
            "control.verb.define",
            {
                "id": _STRING,
                "noun_id": _STRING,
                "input_schema": _OBJ,
                "output_schema": _OBJ,
                "description": _STRING,
                "consequence": {"type": "string", "enum": ["low", "high"]},
                "idempotency_mode": {
                    "type": "string",
                    "enum": ["cacheable", "disabled"],
                },
                "identity_mode": {
                    "type": "string",
                    "enum": ["service-principal", "delegated"],
                },
                "degraded_mode": _OBJ,
            },
            ("id", "noun_id"),
            "Define or replace a verb with safe consequence defaults",
        ),
        *[
            _spec(
                f"control.verb.{action}",
                {"id": _STRING},
                ("id",),
                f"{action.title()} a verb without deleting its binding",
                additional=False,
            )
            for action in ("archive", "restore")
        ],
        _spec(
            "control.binding.set",
            {
                "verb_id": _STRING,
                "target_type": {"type": "string", "enum": ["adapter", "agent"]},
                "target_ref": _STRING,
                "rate_limit": {
                    "type": "object",
                    "properties": {
                        "per": {"type": "string", "enum": ["minute", "hour"]},
                        "max": {"type": "integer", "minimum": 1},
                        "scope": {"type": "string", "enum": ["tenant", "verb"]},
                    },
                    "required": ["per", "max"],
                    "additionalProperties": False,
                },
            },
            ("verb_id", "target_type", "target_ref"),
            "Bind a verb to an adapter or reasoning-agent profile",
        ),
    ]


def registry_specs() -> list[VerbSpec]:
    return [*_skill_noun_specs(), *_verb_binding_specs()]
