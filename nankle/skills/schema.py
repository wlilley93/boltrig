"""Parse and validate a skill from its YAML library shape (S7.4, US-SKL-01).

A skill is *data*: adding or editing one never touches kernel or runtime code
(P1). The on-disk shape is::

    id: analysis/ticket-decomposition
    version: 1.0.0                       # semver
    extends: analysis/base-decomposition # optional parent for inheritance
    locale: en                           # optional, defaults to "en"
    prompt_fragment: |
      ...the skill's contribution to the system prompt...
    tool_grants:                         # verb-grant tokens (P8, SEC-07)
      - jira.read
      - jira.write
    context_requirements:                # a JSON Schema the spawn context
      type: object                       # must satisfy (ContextRequirementsUnmet)
      properties:
        ticket_id: { type: string }
      required: [ticket_id]

``parse_skill`` turns one such document into a frozen-contract
:class:`nankle.models.Skill`, raising :class:`SkillValidationError` with every
problem it found so a library author sees all of them at once.
"""

from __future__ import annotations

import re
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from nankle.models import Skill

# Pragmatic semver: MAJOR.MINOR.PATCH with optional -prerelease and +build.
_SEMVER = re.compile(
    r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"
)

DEFAULT_LOCALE = "en"


class SkillValidationError(ValueError):
    """A skill document failed validation (US-SKL-01).

    Carries every collected message so the author can fix them in one pass.
    """

    def __init__(self, skill_id: str | None, errors: list[str]) -> None:
        self.skill_id = skill_id
        self.errors = errors
        where = f" for skill '{skill_id}'" if skill_id else ""
        super().__init__(f"invalid skill{where}: " + "; ".join(errors))


def parse_skill(doc: dict, tenant_id: str) -> Skill:
    """Validate ``doc`` and build a :class:`Skill` for ``tenant_id`` (US-SKL-01).

    Raises :class:`SkillValidationError` listing all problems. ``id`` and
    ``version`` are mandatory; everything else is optional but type-checked, and
    ``context_requirements`` (when present) must be a valid JSON Schema.
    """
    errors: list[str] = []

    if not isinstance(doc, dict):
        raise SkillValidationError(None, ["document is not a mapping"])

    skill_id = doc.get("id")
    if not isinstance(skill_id, str) or not skill_id.strip():
        errors.append("'id' is required and must be a non-empty string")
        skill_id_for_error: str | None = None
    else:
        skill_id_for_error = skill_id

    version = doc.get("version")
    if not isinstance(version, str) or not _SEMVER.match(version):
        errors.append("'version' is required and must be semver (e.g. 1.0.0)")

    prompt_fragment = doc.get("prompt_fragment", "")
    if not isinstance(prompt_fragment, str):
        errors.append("'prompt_fragment' must be a string")
        prompt_fragment = ""

    tool_grants = doc.get("tool_grants", []) or []
    if not isinstance(tool_grants, list) or not all(
        isinstance(g, str) for g in tool_grants
    ):
        errors.append("'tool_grants' must be a list of grant-token strings")
        tool_grants = [g for g in tool_grants if isinstance(g, str)] if isinstance(
            tool_grants, list
        ) else []

    extends = doc.get("extends")
    if extends is not None and (not isinstance(extends, str) or not extends.strip()):
        errors.append("'extends' must be a skill-id string when present")
        extends = None

    locale = doc.get("locale", DEFAULT_LOCALE)
    if not isinstance(locale, str) or not locale.strip():
        errors.append("'locale' must be a non-empty string")
        locale = DEFAULT_LOCALE

    description = doc.get("description", "") or ""
    if not isinstance(description, str):
        errors.append("'description' must be a string when present")
        description = ""

    context_requirements = doc.get("context_requirements", {}) or {}
    if not isinstance(context_requirements, dict):
        errors.append("'context_requirements' must be a JSON Schema object")
        context_requirements = {}
    elif context_requirements:
        try:  # the requirements are themselves a JSON Schema (validated at spawn)
            Draft202012Validator.check_schema(context_requirements)
        except SchemaError as exc:
            errors.append(f"'context_requirements' is not a valid JSON Schema: {exc.message}")

    if errors:
        raise SkillValidationError(skill_id_for_error, errors)

    return Skill(
        id=skill_id,
        tenant_id=tenant_id,
        version=version,
        prompt_fragment=prompt_fragment,
        tool_grants=list(tool_grants),
        context_requirements=dict(context_requirements),
        extends=extends,
        locale=locale,
        description=description,
    )


def _as_object_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Normalise a (possibly empty) context-requirements schema to object shape."""
    out: dict[str, Any] = {"type": "object", "properties": {}, "required": []}
    if not schema:
        return out
    props = schema.get("properties")
    if isinstance(props, dict):
        out["properties"].update(props)
    required = schema.get("required")
    if isinstance(required, (list, tuple)):
        out["required"] = [k for k in required]
    return out
