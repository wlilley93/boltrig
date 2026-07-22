"""Skills loader/shelf edge cases: cyclic extends is loud, limit is clamped."""

from __future__ import annotations

import pytest

from boltrig.models import GrantSet, InvocationContext, Skill
from boltrig.skills.loader import resolve_skill
from boltrig.skills.schema import SkillValidationError
from boltrig.skills.shelf import build_skill_shelf_adapter
from boltrig.store import InMemoryStore

T = "acme"


def _skill(skill_id: str, extends: str | None = None) -> Skill:
    return Skill(id=skill_id, tenant_id=T, version="1.0.0",
                 prompt_fragment=f"body of {skill_id}", extends=extends)


async def test_cyclic_extends_chain_raises_instead_of_resolving_partial():
    store = InMemoryStore()
    await store.upsert_skill(_skill("a", extends="b"))
    await store.upsert_skill(_skill("b", extends="a"))
    with pytest.raises(SkillValidationError, match="cyclic"):
        await resolve_skill(store, T, "a")


async def test_self_extending_skill_raises():
    store = InMemoryStore()
    await store.upsert_skill(_skill("self", extends="self"))
    with pytest.raises(SkillValidationError, match="cyclic"):
        await resolve_skill(store, T, "self")


async def test_skill_search_clamps_a_nonpositive_limit():
    store = InMemoryStore()
    await store.upsert_skill(_skill("one"))
    await store.upsert_skill(_skill("two"))
    shelf = build_skill_shelf_adapter(store)
    ctx = InvocationContext(tenant_id=T, grants=GrantSet.of(["*"]), actor="u")
    out = await shelf.execute("skill.search", {"limit": -5}, None, ctx)
    assert out.ok
    # shelf[:-5] would slice oddly; a clamped limit returns real entries.
    assert len(out.output["skills"]) == 1
    assert out.output["count"] == 2
