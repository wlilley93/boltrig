from __future__ import annotations

import json

from boltrig.memory.engine import EngineFact
from boltrig.memory.projection_adapters import (
    CogneeProjection,
    Mem0Projection,
    build_memory_projection_fanout,
)
from boltrig.models import InvocationContext
from boltrig.store import InMemoryStore


T = "acme"


class _Mem0Client:
    def __init__(self):
        self.add_calls = []
        self.search_calls = []
        self.deleted = []
        self.items = []

    async def add(self, **kwargs):
        self.add_calls.append(kwargs)
        memory_id = f"mem-{len(self.add_calls)}"
        self.items.append({
            "id": memory_id,
            "memory": kwargs["messages"][0]["content"],
            "score": 0.91,
            "metadata": kwargs["metadata"],
        })
        return {"results": [self.items[-1]]}

    async def search(self, query, **kwargs):
        self.search_calls.append((query, kwargs))
        user_id = kwargs["filters"]["user_id"]
        return {"results": [
            item for item in self.items
            if item["metadata"]["owner_scope"] == user_id.split(":", 1)[1]
        ]}

    async def get_all(self, **kwargs):
        user_id = _filter_value(kwargs["filters"], "user_id")
        fact_id = _filter_value(kwargs["filters"], "fact_id")
        return {"results": [
            item for item in self.items
            if item["metadata"]["owner_scope"] == user_id.split(":", 1)[1]
            and item["metadata"]["fact_id"] == fact_id
        ]}

    async def delete(self, *, memory_id):
        self.deleted.append(memory_id)


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


def _filter_value(filters, key):
    if key in filters:
        return filters[key]
    for item in filters.get("AND", []):
        if key in item:
            return item[key]
    return None


async def test_mem0_projection_writes_scoped_metadata_and_recalls_labelled_hits():
    client = _Mem0Client()
    projection = Mem0Projection(client=client)
    fact = _fact()

    written = await projection.remember(T, fact, _ctx())
    hits = await projection.recall(
        T, "alice", scopes=["user:alice"], mode="similarity", limit=5, max_hops=1,
        context=_ctx())

    assert client.add_calls[0]["user_id"] == "acme:user:alice"
    assert client.add_calls[0]["infer"] is False
    assert client.add_calls[0]["metadata"]["boltrig_authority"] == "kernel_ledger"
    assert client.search_calls[0][1]["filters"] == {"user_id": "acme:user:alice"}
    assert json.loads(written.projection_ref)["memory_id"] == "mem-1"
    assert hits[0].fact_id == "f1"
    assert hits[0].content == "alice likes blue"
    assert json.loads(hits[0].projection_ref)["entity"] == "acme:user:alice"


async def test_mem0_projection_delete_uses_memory_ref_or_metadata_lookup():
    client = _Mem0Client()
    projection = Mem0Projection(client=client)
    fact = _fact()
    written = await projection.remember(T, fact, _ctx())

    await projection.forget(T, fact_id=fact.id, projection_ref=written.projection_ref, context=_ctx())
    await projection.forget(
        T,
        fact_id=fact.id,
        projection_ref=json.dumps({"entity": "acme:user:alice", "event_id": "evt-1"}),
        context=_ctx(),
    )

    assert client.deleted == ["mem-1", "mem-1"]


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
        "primary_projection": "mem0",
        "projections": [
            {"id": "mem0", "enabled": "false"},
            {"id": "cognee", "enabled": "true"},
        ],
    })

    assert fanout is not None
    assert fanout.enabled() is True


def test_projection_fanout_builder_treats_false_strings_as_disabled():
    fanout = build_memory_projection_fanout(InMemoryStore(), {
        "primary_projection": "mem0",
        "projections": [
            {"id": "mem0", "enabled": "false"},
            {"id": "cognee", "enabled": "0"},
        ],
    })

    assert fanout is None
