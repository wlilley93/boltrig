from __future__ import annotations

from boltrig.memory.engine import EngineFact
from boltrig.memory.projection_adapters import (
    CogneeProjection,
    build_memory_projection_fanout,
)
from boltrig.models import InvocationContext
from boltrig.store import InMemoryStore


T = "acme"


class _CogneeEngine:
    def __init__(self):
        self.facts = {}
        self.forgotten = []

    async def remember(self, tenant_id, facts):
        for fact in facts:
            self.facts[(tenant_id, fact.id)] = fact
        return [fact.id for fact in facts]

    async def recall(self, tenant_id, query, *, scopes, mode, limit, max_hops):
        from boltrig.memory.engine import RecallHit

        return [
            RecallHit(fact=fact, score=1.0, path=[fact.id])
            for (tenant, _), fact in self.facts.items()
            if tenant == tenant_id and fact.owner_scope in scopes and query in fact.content
        ][:limit]

    async def forget(self, tenant_id, *, fact_ids=None, scopes=None):
        self.forgotten.extend(fact_ids or [])
        return list(fact_ids or [])


def _ctx():
    return InvocationContext(tenant_id=T, actor="alice")


def _fact(fid="f1", scope="user:alice", content="alice likes blue"):
    return EngineFact(id=fid, owner_scope=scope, kind="entity", content=content)


async def test_cognee_projection_wraps_existing_engine_without_authority():
    engine = _CogneeEngine()
    projection = CogneeProjection(engine=engine)
    fact = _fact(content="deep graph note")

    assert (await projection.remember(T, fact, _ctx())).projection_ref == "cognee:f1"
    hits = await projection.recall(
        T, "deep", scopes=["user:alice"], mode="similarity", limit=5, max_hops=1,
        context=_ctx())
    deleted = await projection.forget(T, fact_id="f1", projection_ref=None, context=_ctx())

    assert hits[0].projection_ref == "cognee:f1"
    assert deleted.projection_ref == "cognee:f1"
    assert engine.forgotten == ["f1"]


def test_projection_fanout_builder_uses_enabled_manifest_entries_only():
    fanout = build_memory_projection_fanout(InMemoryStore(), {
        "primary_projection": "cognee",
        "projections": [
            {"id": "cognee", "enabled": "true"},
        ],
    })

    assert fanout is not None
    assert fanout.enabled() is True


def test_projection_fanout_builder_treats_false_strings_as_disabled():
    fanout = build_memory_projection_fanout(InMemoryStore(), {
        "primary_projection": "cognee",
        "projections": [
            {"id": "cognee", "enabled": "0"},
        ],
    })

    assert fanout is None
