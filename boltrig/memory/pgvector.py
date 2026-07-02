"""The Postgres + pgvector production Memory Engine (MEM-ENG-02).

Same contract and semantics as ``VectorMemoryEngine`` (its offline reference), but
the vector/graph store is Postgres with the ``pgvector`` extension, so recall is
backed by an ANN index at scale and facts are durable. It is consolidation-faithful
by design: memory lives in the ONE Boltrig Postgres (no separate vector database),
in engine-owned tables (``memory_vectors`` + ``memory_vector_edges``) alongside the
governance ledger the kernel keeps (``memory_facts``).

Isolation is identical to the reference engine and is provable by construction:

  * every query is filtered by ``owner_scope = ANY($scopes)`` in SQL, so an
    out-of-scope row is never read;
  * graph traversal loads only edges whose BOTH endpoints are in scope, so a
    hostile cross-scope edge - including multi-hop - is structurally unfollowable
    (SEC-40);
  * the kernel re-checks scope on everything returned (defence-in-depth).

No extra Python dependency: vectors are sent as pgvector's text literal
(``'[..]'::vector``) and distances use the cosine operator ``<=>``.
"""

from __future__ import annotations

from boltrig.store.postgres import normalize_dsn

from .embeddings import DEFAULT_DIM, Embedder, HashingEmbedder
from .engine import EngineFact, RecallHit, signal_delta


def _vec_literal(vec: list[float]) -> str:
    """pgvector text input form: '[0.1,0.2,...]'."""
    return "[" + ",".join(f"{x:.7g}" for x in vec) + "]"


# Engine-owned schema. Idempotent, and mirrored in store/schema.sql so the unified
# store provisions pgvector by default; running both is a no-op. dim is bound to
# DEFAULT_DIM here and in the schema - a deployment that changes it changes both.
_ENGINE_SCHEMA = f"""
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS memory_vectors (
    tenant_id   TEXT NOT NULL,
    id          TEXT NOT NULL,
    owner_scope TEXT NOT NULL,
    kind        TEXT NOT NULL DEFAULT 'entity',
    content     TEXT NOT NULL DEFAULT '',
    data_class  TEXT NOT NULL DEFAULT 'standard',
    source_kind TEXT NOT NULL DEFAULT 'verb_result',
    source_ref  TEXT,
    embedding   vector({DEFAULT_DIM}),
    weight      DOUBLE PRECISION NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id)
);
CREATE INDEX IF NOT EXISTS memory_vectors_scope_idx
    ON memory_vectors (tenant_id, owner_scope, kind);
CREATE TABLE IF NOT EXISTS memory_vector_edges (
    tenant_id TEXT NOT NULL,
    src       TEXT NOT NULL,
    dst       TEXT NOT NULL,
    PRIMARY KEY (tenant_id, src, dst)
);
"""


class PgVectorMemoryEngine:
    """Durable, scope-isolated vector recall on Postgres + pgvector."""

    def __init__(
        self,
        dsn: str,
        embedder: Embedder | None = None,
        *,
        dim: int = DEFAULT_DIM,
        apply_schema: bool = True,
    ) -> None:
        self._dsn = normalize_dsn(dsn)
        self._embedder: Embedder = embedder or HashingEmbedder(dim)
        self.dim = self._embedder.dim
        self._apply_schema = apply_schema
        self._pool = None

    async def _ensure(self):
        if self._pool is None:
            import asyncpg

            self._pool = await asyncpg.create_pool(self._dsn, min_size=1, max_size=5)
            if self._apply_schema:
                async with self._pool.acquire() as conn:
                    await conn.execute(_ENGINE_SCHEMA)
        return self._pool

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def remember(self, tenant_id: str, facts: list[EngineFact]) -> list[str]:
        pool = await self._ensure()
        ids: list[str] = []
        async with pool.acquire() as conn:
            async with conn.transaction():
                for f in facts:
                    emb = _vec_literal(self._embedder.embed(f.content))
                    await conn.execute(
                        """INSERT INTO memory_vectors
                             (tenant_id, id, owner_scope, kind, content, data_class,
                              source_kind, source_ref, embedding)
                           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9::vector)
                           ON CONFLICT (tenant_id, id) DO UPDATE SET
                             owner_scope=EXCLUDED.owner_scope, kind=EXCLUDED.kind,
                             content=EXCLUDED.content, data_class=EXCLUDED.data_class,
                             source_kind=EXCLUDED.source_kind, source_ref=EXCLUDED.source_ref,
                             embedding=EXCLUDED.embedding""",
                        tenant_id, f.id, f.owner_scope, f.kind, f.content, f.data_class,
                        f.source_kind, f.source_ref, emb,
                    )
                    for dst in f.relates_to:
                        await conn.execute(
                            """INSERT INTO memory_vector_edges (tenant_id, src, dst)
                               VALUES ($1,$2,$3) ON CONFLICT DO NOTHING""",
                            tenant_id, f.id, dst,
                        )
                    ids.append(f.id)
        return ids

    async def recall(
        self, tenant_id, query, *, scopes, mode="graph_completion", limit=20, max_hops=4
    ) -> list[RecallHit]:
        pool = await self._ensure()
        scope_list = list(scopes)
        has_query = bool((query or "").strip())
        qv = _vec_literal(self._embedder.embed(query)) if has_query else None

        async with pool.acquire() as conn:
            # in-scope node set (scope-filtered in SQL: out-of-scope rows never read)
            rows = await conn.fetch(
                """SELECT id, owner_scope, kind, content, data_class, source_kind,
                          source_ref, weight FROM memory_vectors
                   WHERE tenant_id=$1 AND owner_scope = ANY($2::text[])""",
                tenant_id, scope_list,
            )
            facts: dict[str, EngineFact] = {}
            weight: dict[str, float] = {}
            for r in rows:
                facts[r["id"]] = EngineFact(
                    id=r["id"], owner_scope=r["owner_scope"], kind=r["kind"],
                    content=r["content"], data_class=r["data_class"],
                    source_kind=r["source_kind"], source_ref=r["source_ref"],
                )
                weight[r["id"]] = float(r["weight"] or 0.0)
            if not facts:
                return []
            ids = list(facts)

            # cosine similarity per in-scope node (1 - distance). No query -> flat.
            sim: dict[str, float] = {}
            if has_query:
                srows = await conn.fetch(
                    """SELECT id, 1 - (embedding <=> $3::vector) AS s
                       FROM memory_vectors
                       WHERE tenant_id=$1 AND owner_scope = ANY($2::text[])
                         AND embedding IS NOT NULL""",
                    tenant_id, scope_list, qv,
                )
                sim = {r["id"]: float(r["s"]) for r in srows}

            # in-scope edges only (BOTH endpoints in scope) -> SEC-40 by construction
            erows = await conn.fetch(
                """SELECT src, dst FROM memory_vector_edges
                   WHERE tenant_id=$1 AND src = ANY($2::text[]) AND dst = ANY($2::text[])""",
                tenant_id, ids,
            )

        adj: dict[str, list[str]] = {i: [] for i in ids}
        for e in erows:
            adj[e["src"]].append(e["dst"])
            facts[e["src"]].relates_to.append(e["dst"])

        def _score(fid: str) -> float:
            base = (sim.get(fid, 0.0) if has_query else 1.0)
            return base + weight.get(fid, 0.0)

        # seeds: ranked by score; a non-positive cosine is not a match when querying
        if has_query:
            seeds = [i for i in sorted(ids, key=_score, reverse=True) if _score(i) > 0.0]
        else:
            seeds = sorted(ids, key=_score, reverse=True)

        if mode == "similarity":
            return [
                RecallHit(fact=facts[i], score=_score(i), hops=0, path=[i]) for i in seeds[:limit]
            ]

        hits: list[RecallHit] = []
        seen: set[str] = set()
        frontier = [(i, 0, [i]) for i in seeds]
        while frontier and len(hits) < limit:
            fid, hops, path = frontier.pop(0)
            if fid in seen:
                continue
            seen.add(fid)
            hits.append(RecallHit(fact=facts[fid], score=_score(fid), hops=hops, path=path))
            if hops >= max_hops:
                continue
            for nid in adj.get(fid, []):
                if nid in facts and nid not in seen:  # in-scope by construction
                    frontier.append((nid, hops + 1, path + [nid]))
        return hits[:limit]

    async def improve(self, tenant_id: str, signal: str, target: str) -> int:
        pool = await self._ensure()
        delta = signal_delta(signal)
        async with pool.acquire() as conn:
            res = await conn.execute(
                "UPDATE memory_vectors SET weight = weight + $3 WHERE tenant_id=$1 AND id=$2",
                tenant_id, target, delta,
            )
        # asyncpg returns e.g. "UPDATE 1"
        try:
            return int(res.split()[-1])
        except (ValueError, IndexError):
            return 0

    async def forget(self, tenant_id, *, fact_ids=None, source_ref=None, scopes=None) -> list[str]:
        pool = await self._ensure()
        scope_list = list(scopes) if scopes is not None else None
        async with pool.acquire() as conn:
            async with conn.transaction():
                # resolve targets, scope-filtered (a caller may only erase in scope)
                targets: set[str] = set()
                if fact_ids:
                    if scope_list is None:
                        rows = await conn.fetch(
                            "SELECT id FROM memory_vectors WHERE tenant_id=$1 AND id = ANY($2::text[])",
                            tenant_id, list(fact_ids),
                        )
                    else:
                        rows = await conn.fetch(
                            """SELECT id FROM memory_vectors WHERE tenant_id=$1
                               AND id = ANY($2::text[]) AND owner_scope = ANY($3::text[])""",
                            tenant_id, list(fact_ids), scope_list,
                        )
                    targets |= {r["id"] for r in rows}
                if source_ref is not None:
                    if scope_list is None:
                        rows = await conn.fetch(
                            "SELECT id FROM memory_vectors WHERE tenant_id=$1 AND source_ref=$2",
                            tenant_id, source_ref,
                        )
                    else:
                        rows = await conn.fetch(
                            """SELECT id FROM memory_vectors WHERE tenant_id=$1
                               AND source_ref=$2 AND owner_scope = ANY($3::text[])""",
                            tenant_id, source_ref, scope_list,
                        )
                    targets |= {r["id"] for r in rows}

                removed: set[str] = set(targets)
                # derived: in-scope relationship nodes referencing a removed node
                if removed:
                    if scope_list is None:
                        drows = await conn.fetch(
                            """SELECT DISTINCT e.src AS id FROM memory_vector_edges e
                               JOIN memory_vectors v ON v.tenant_id=e.tenant_id AND v.id=e.src
                               WHERE e.tenant_id=$1 AND e.dst = ANY($2::text[])
                                 AND v.kind='relationship'""",
                            tenant_id, list(removed),
                        )
                    else:
                        drows = await conn.fetch(
                            """SELECT DISTINCT e.src AS id FROM memory_vector_edges e
                               JOIN memory_vectors v ON v.tenant_id=e.tenant_id AND v.id=e.src
                               WHERE e.tenant_id=$1 AND e.dst = ANY($2::text[])
                                 AND v.kind='relationship' AND v.owner_scope = ANY($3::text[])""",
                            tenant_id, list(removed), scope_list,
                        )
                    removed |= {r["id"] for r in drows}

                if removed:
                    rl = list(removed)
                    await conn.execute(
                        "DELETE FROM memory_vectors WHERE tenant_id=$1 AND id = ANY($2::text[])",
                        tenant_id, rl,
                    )
                    # prune dangling edges either side of a removed node
                    await conn.execute(
                        """DELETE FROM memory_vector_edges WHERE tenant_id=$1
                           AND (src = ANY($2::text[]) OR dst = ANY($2::text[]))""",
                        tenant_id, rl,
                    )
        return sorted(removed)

    async def health(self) -> str:
        try:
            pool = await self._ensure()
            async with pool.acquire() as conn:
                await conn.execute("SELECT 1")
            return "ok"
        except Exception:  # pragma: no cover - exercised only on a real outage
            return "down"
