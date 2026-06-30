"""PgVectorMemoryEngine parity on real Postgres + pgvector (MEM-ENG-02).

These run only when BOLTRIG_TEST_DATABASE_URL points at a Postgres with the
``vector`` extension available (CI provides the pgvector image; offline they skip
cleanly, P9). They prove the durable native engine behaves identically to the
in-process reference: cosine-ranked recall (MEM-VEC-01) and scope-bounded
traversal incl. multi-hop (SEC-40), plus complete erasure (SEC-44).
"""

from __future__ import annotations

import asyncio
import os

import pytest

from boltrig.memory import EngineFact
from boltrig.memory.pgvector import PgVectorMemoryEngine

DSN = os.environ.get("BOLTRIG_TEST_DATABASE_URL")
_pg = pytest.mark.skipif(not DSN, reason="set BOLTRIG_TEST_DATABASE_URL for pgvector tests")
T = "acme_pgvec_test"


async def _fresh() -> PgVectorMemoryEngine:
    engine = PgVectorMemoryEngine(DSN)
    await engine._ensure()
    async with engine._pool.acquire() as conn:  # clean slate for this test tenant
        await conn.execute("DELETE FROM memory_vector_edges WHERE tenant_id=$1", T)
        await conn.execute("DELETE FROM memory_vectors WHERE tenant_id=$1", T)
    return engine


@_pg
@pytest.mark.invariant("MEM-VEC-01")
def test_pgvector_recall_ranks_by_cosine():
    async def run():
        engine = await _fresh()
        try:
            await engine.remember(T, [
                EngineFact(id="f1", owner_scope="user:alice", kind="entity",
                           content="database migration plan for the postgres cluster"),
                EngineFact(id="f2", owner_scope="user:alice", kind="entity",
                           content="postgres database migration"),
                EngineFact(id="f3", owner_scope="user:alice", kind="entity",
                           content="lunch menu with sandwiches and salad"),
            ])
            hits = await engine.recall(
                T, "postgres database migration", scopes=["user:alice"], mode="similarity")
            ids = [h.fact.id for h in hits]
            assert "f3" not in ids
            assert set(ids) == {"f1", "f2"}
            assert ids[0] == "f2"  # closest match first
            assert hits[0].score >= hits[-1].score
        finally:
            await engine.close()

    asyncio.run(run())


@_pg
@pytest.mark.invariant("SEC-40")
def test_pgvector_recall_is_scope_bounded_multihop():
    async def run():
        engine = await _fresh()
        try:
            await engine.remember(T, [
                EngineFact(id="a1", owner_scope="user:alice", kind="entity",
                           content="migration plan", relates_to=["b1"]),
                EngineFact(id="b1", owner_scope="user:bob", kind="entity",
                           content="bob migration secret", relates_to=["c1"]),
                EngineFact(id="c1", owner_scope="user:carol", kind="entity",
                           content="carol migration secret"),
            ])
            hits = await engine.recall(
                T, "migration", scopes=["user:alice"], mode="graph_completion", max_hops=4)
            assert {h.fact.owner_scope for h in hits} == {"user:alice"}
            assert all("secret" not in h.fact.content for h in hits)
        finally:
            await engine.close()

    asyncio.run(run())


@_pg
@pytest.mark.invariant("SEC-44")
def test_pgvector_forget_is_complete():
    async def run():
        engine = await _fresh()
        try:
            await engine.remember(T, [
                EngineFact(id="e1", owner_scope="user:alice", kind="entity",
                           content="project apollo"),
                EngineFact(id="r1", owner_scope="user:alice", kind="relationship",
                           content="apollo owned by alice", relates_to=["e1"]),
            ])
            removed = await engine.forget(T, fact_ids=["e1"], scopes=["user:alice"])
            # the node AND its derived relationship are removed (complete)
            assert set(removed) == {"e1", "r1"}
            hits = await engine.recall(T, "apollo", scopes=["user:alice"], mode="similarity")
            assert hits == []
        finally:
            await engine.close()

    asyncio.run(run())
