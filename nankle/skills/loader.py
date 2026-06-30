"""Load the skill library from disk and resolve inheritance (US-SKL-01/02/03).

Three jobs:

* :func:`load_skills_dir` walks a directory tree, parses every ``*.yaml`` file
  and upserts the skills into the store (US-SKL-01).
* :func:`resolve_skill` walks a skill's ``extends`` chain and produces one
  merged, flattened :class:`Skill`: prompt fragments concatenated parent-first,
  the UNION of ``tool_grants``, and merged ``context_requirements``. Merging
  builds fresh objects, so a base skill is never mutated by a child (US-SKL-02).
* :func:`select_locale` picks a localised variant of a skill, falling back to
  the default locale when the requested one is absent (US-SKL-03).

Everything is offline-safe and depends only on ``pyyaml`` (already a dep).
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml

from nankle.models import Skill

from .schema import DEFAULT_LOCALE, _as_object_schema, parse_skill


class SkillNotFound(LookupError):
    """A skill (or one of its ``extends`` ancestors) is not in the store.

    Fail-closed (K-13): an unresolved reference is an error, not a silent skip.
    """


async def load_skills_dir(store: Any, tenant_id: str, path: str) -> list[str]:
    """Parse every ``*.yaml`` skill under ``path`` and upsert it (US-SKL-01).

    Returns the list of skill ids loaded, in directory-walk order. A file that
    is empty or not a mapping is skipped; a file that fails validation raises
    (a broken library should be loud, not silently partial).
    """
    root = Path(path)
    loaded: list[str] = []
    for file in sorted(root.rglob("*.yaml")) + sorted(root.rglob("*.yml")):
        text = file.read_text(encoding="utf-8")
        doc = yaml.safe_load(text)
        if not isinstance(doc, dict):
            continue  # empty file or a list/scalar: nothing to load
        skill = parse_skill(doc, tenant_id)
        await store.upsert_skill(skill)
        loaded.append(skill.id)
    return loaded


async def _chain(store: Any, tenant_id: str, skill_id: str) -> list[Skill]:
    """Load ``skill_id`` and its ``extends`` ancestors, root-first.

    Guards against a cyclic ``extends`` chain via a ``seen`` set.
    """
    chain: list[Skill] = []
    seen: set[str] = set()
    current: str | None = skill_id
    while current is not None:
        if current in seen:
            break  # cycle: stop walking, keep what we have
        seen.add(current)
        skill = await store.get_skill(tenant_id, current)
        if skill is None:
            raise SkillNotFound(
                f"unknown skill '{current}' for tenant '{tenant_id}'"
            )
        chain.append(skill)
        current = skill.extends
    chain.reverse()  # root-first so the child augments the parent
    return chain


async def resolve_skill(store: Any, tenant_id: str, skill_id: str) -> Skill:
    """Return a flattened :class:`Skill` with inheritance merged (US-SKL-02).

    * ``prompt_fragment``: parent-first, non-empty fragments joined by blank lines
      (a child appends to / extends the parent's prompt).
    * ``tool_grants``: order-preserving UNION (a child can only add authority).
    * ``context_requirements``: merged object schema (union of properties, with
      the child overriding on a key clash; union of ``required``).

    The merge builds new lists/dicts and deep-copies schema fragments, so the
    stored base skills are never mutated (US-SKL-02). The returned skill's
    ``extends`` is ``None`` because it is already fully resolved.
    """
    chain = await _chain(store, tenant_id, skill_id)
    leaf = chain[-1]  # the originally-requested skill

    prompt_fragments: list[str] = []
    tool_grants: list[str] = []
    merged_req: dict[str, Any] = {"type": "object", "properties": {}, "required": []}

    for skill in chain:
        if skill.prompt_fragment:
            prompt_fragments.append(skill.prompt_fragment)
        for grant in skill.tool_grants:
            if grant not in tool_grants:  # order-preserving union
                tool_grants.append(grant)
        req = _as_object_schema(skill.context_requirements)
        merged_req["properties"].update(copy.deepcopy(req["properties"]))
        for key in req["required"]:
            if key not in merged_req["required"]:
                merged_req["required"].append(key)

    return Skill(
        id=skill_id,
        tenant_id=tenant_id,
        version=leaf.version,
        prompt_fragment="\n\n".join(prompt_fragments),
        tool_grants=tool_grants,
        context_requirements=merged_req,
        extends=None,
        locale=leaf.locale,
        description=leaf.description,
    )


def _locale_id(base_id: str, locale: str) -> str:
    """The id convention for a non-default locale variant: ``base@locale``."""
    return f"{base_id}@{locale}"


async def select_locale(
    store: Any, tenant_id: str, base_id: str, locale: str
) -> Skill:
    """Resolve the ``locale`` variant of ``base_id``, else the default (US-SKL-03).

    Locale variants are stored under ``base@locale`` (e.g.
    ``writing/long-form@fr``); the default-locale skill is stored under the bare
    ``base_id``. When the requested variant is absent we fall back to the
    default so a missing translation never blocks a spawn.
    """
    if locale and locale != DEFAULT_LOCALE:
        variant_id = _locale_id(base_id, locale)
        if await store.get_skill(tenant_id, variant_id) is not None:
            return await resolve_skill(store, tenant_id, variant_id)
    return await resolve_skill(store, tenant_id, base_id)
