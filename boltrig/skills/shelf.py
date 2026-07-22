"""The SkillShelfAdapter: an on-demand skill library behind the chokepoint.

Round Fifteen (the extension contract). Skills are still loaded eagerly by id at
spawn (that path is unchanged). This adds the OTHER mode the brief asked for: an
agent browses a project's skill SHELF by description and pulls one off it only
when a job matches - progressive disclosure, not every body in context.

It is a normal adapter (the MemoryAdapter / ControlPlaneAdapter pattern), so every
shelf operation runs the dispatch chokepoint - grant check + audit - and is
tenant-scoped. Three verbs, all read/compose (consequence low):

  * ``skill.search``   - the shelf: lightweight descriptions only (id, version,
    when-to-use), NEVER the prompt_fragment body. This is the progressive-
    disclosure step (FR-SKILL-01).
  * ``skill.describe`` - one skill's SELECTION metadata: its description, its
    ``tool_grants`` (what it would want), and its ``context_requirements`` (the
    JSON Schema the job must satisfy) - still no body.
  * ``skill.load``     - resolve the skill (with ``extends`` inheritance), validate
    the caller's per-job ``context`` against the merged requirements, and return
    the composed body bound to that context: the customised instance for this run
    (FR-SKILL-02).

Load returns the skill's ``tool_grants`` as DATA (what the skill wants), it does
NOT grant them - the caller still can only call verbs it already holds, so a
loaded skill can never escalate (SEC-57, the same "content is data, not authority"
rule as recalled memory).
"""

from __future__ import annotations

from typing import Any

from jsonschema import Draft202012Validator

from boltrig.adapters.base import AdapterError, Credential, ErrorClass, Result, VerbSpec
from boltrig.models import ContextRequirementsUnmet, InvocationContext

from .loader import SkillNotFound, resolve_skill
from .schema import SkillValidationError

_OBJ: dict = {"type": "object"}


def _matches(skill: Any, query: str) -> bool:
    if not query:
        return True
    q = query.lower()
    return q in (skill.id or "").lower() or q in (skill.description or "").lower()


class SkillShelfAdapter:
    """The per-project skill shelf as governed ``skill.*`` verbs."""

    id = "skill-shelf"
    version = "0.1.0"
    runtime = "script"
    source = "builtin"

    def __init__(self, store: Any) -> None:
        self._store = store

    def describe(self) -> list[VerbSpec]:
        return [
            VerbSpec(
                verb_id="skill.search", noun_id="skill",
                input_schema={"type": "object", "properties": {
                    "query": {"type": "string"}, "limit": {"type": "integer"}}},
                output_schema=_OBJ, consequence="low",
                description="Browse the skill shelf by description (no bodies)"),
            VerbSpec(
                verb_id="skill.describe", noun_id="skill",
                input_schema={"type": "object",
                              "properties": {"id": {"type": "string"}},
                              "required": ["id"]},
                output_schema=_OBJ, consequence="low",
                description="A skill's selection metadata + its context_requirements"),
            VerbSpec(
                verb_id="skill.load", noun_id="skill",
                input_schema={"type": "object",
                              "properties": {"id": {"type": "string"},
                                             "context": {"type": "object"}},
                              "required": ["id"]},
                output_schema=_OBJ, consequence="low",
                description="Load a skill's body bound to this job's context"),
        ]

    async def execute(
        self, verb: str, params: dict, credential: Credential | None, context: InvocationContext
    ) -> Result:
        tenant = context.tenant_id
        if verb == "skill.search":
            return await self._search(tenant, params)
        if verb == "skill.describe":
            return await self._describe(tenant, params)
        if verb == "skill.load":
            return await self._load(tenant, params)
        return Result.failure(AdapterError(ErrorClass.INVALID, f"unknown verb {verb}"))

    async def health(self) -> str:
        return "ok"

    # --- the shelf: descriptions only, never bodies (SEC-57 / FR-SKILL-01) ---
    async def _search(self, tenant: str, params: dict) -> Result:
        query = str(params.get("query") or "")
        limit = max(1, int(params.get("limit") or 50))
        skills = await self._store.list_skills(tenant)
        shelf = [
            {"id": s.id, "version": s.version,
             "description": s.description or s.id,  # fall back to the id as a label
             "tool_grant_count": len(s.tool_grants), "extends": s.extends}
            for s in skills if _matches(s, query)
        ]
        shelf.sort(key=lambda e: e["id"])
        return Result.success({"skills": shelf[:limit], "count": len(shelf)})

    async def _describe(self, tenant: str, params: dict) -> Result:
        skill = await self._store.get_skill(tenant, params["id"])
        if skill is None:
            return Result.failure(AdapterError(ErrorClass.NOT_FOUND, f"unknown skill {params['id']}"))
        # selection metadata: what it is, what it wants, what the job must supply -
        # NOT the prompt_fragment body (that comes from skill.load).
        return Result.success({
            "id": skill.id, "version": skill.version,
            "description": skill.description or skill.id,
            "extends": skill.extends, "tool_grants": skill.tool_grants,
            "context_requirements": skill.context_requirements,
        })

    async def _load(self, tenant: str, params: dict) -> Result:
        try:
            resolved = await resolve_skill(self._store, tenant, params["id"])
        except SkillNotFound:
            return Result.failure(AdapterError(ErrorClass.NOT_FOUND, f"unknown skill {params['id']}"))
        except SkillValidationError as exc:  # e.g. a cyclic extends chain
            return Result.failure(AdapterError(ErrorClass.INVALID, str(exc)))

        job_context = {k: v for k, v in (params.get("context") or {}).items() if v is not None}
        schema = resolved.context_requirements or {}
        required = schema.get("required") or []
        properties = schema.get("properties") or {}
        missing = [k for k in required if k not in job_context]
        errors: list[str] = []
        if properties or required:
            errors = [e.message for e in Draft202012Validator(schema).iter_errors(job_context)]
        if missing or errors:
            detail = "; ".join(errors) if errors else "missing required context"
            raise ContextRequirementsUnmet(
                f"skill '{params['id']}' context unmet: {detail}", missing=missing or errors
            )

        # The customised instance: the composed body bound to this job's context.
        # tool_grants are returned as DATA (what the skill wants) - loading does
        # NOT grant them; the caller still only holds its own grants (SEC-57).
        return Result.success({
            "id": resolved.id, "version": resolved.version,
            "description": resolved.description or resolved.id,
            "prompt_fragment": resolved.prompt_fragment,
            "tool_grants": resolved.tool_grants,
            "context_requirements": schema,
            "bound_context": job_context,
        })


def build_skill_shelf_adapter(store: Any) -> SkillShelfAdapter:
    """Construct the skill-shelf adapter for registration in bootstrap."""
    return SkillShelfAdapter(store)
