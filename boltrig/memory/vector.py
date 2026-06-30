"""The native vector Memory Engine reference (MEM-ENG-02).

This is the engine-agnostic interface's first-class *vector* implementation: it
ranks recall by true cosine similarity over embeddings (not the naive keyword
overlap of ``LocalMemoryEngine``), while keeping every isolation guarantee the
interface requires. It is in-process and dependency-free (it uses
``HashingEmbedder`` by default), so the binding suite exercises real vector recall
offline and deterministically. ``PgVectorMemoryEngine`` persists the SAME
semantics to Postgres + pgvector for scale; both share this module's contract:

  * recall ranks in-scope facts by cosine similarity to the query embedding;
  * ``graph_completion`` seeds by vector similarity then traverses explicit edges
    WITHOUT ever leaving the caller's permitted scopes (SEC-40) - a hostile
    cross-scope edge, including multi-hop, is never followed;
  * ``improve`` only reweights, never changing a fact's scope or authority
    (SEC-41); ``forget`` removes the node and its derived edges (SEC-44).

The kernel re-checks scope on everything this engine returns; the engine simply
does not cheat.
"""

from __future__ import annotations

from .embeddings import DEFAULT_DIM, Embedder, HashingEmbedder, cosine
from .engine import EngineFact, RecallHit


class VectorMemoryEngine:
    """In-process embedding-backed engine. The reference vector recall engine."""

    def __init__(self, embedder: Embedder | None = None, *, dim: int = DEFAULT_DIM) -> None:
        self._embedder: Embedder = embedder or HashingEmbedder(dim)
        self.dim = self._embedder.dim
        self._facts: dict[str, dict[str, EngineFact]] = {}  # tenant -> id -> fact
        self._vecs: dict[str, dict[str, list[float]]] = {}  # tenant -> id -> embedding
        self._weight: dict[tuple[str, str], float] = {}  # (tenant, id) -> boost

    def _tenant(self, tenant_id: str) -> dict[str, EngineFact]:
        return self._facts.setdefault(tenant_id, {})

    def _tenant_vecs(self, tenant_id: str) -> dict[str, list[float]]:
        return self._vecs.setdefault(tenant_id, {})

    async def remember(self, tenant_id: str, facts: list[EngineFact]) -> list[str]:
        store = self._tenant(tenant_id)
        vecs = self._tenant_vecs(tenant_id)
        ids: list[str] = []
        for f in facts:
            store[f.id] = f
            vecs[f.id] = self._embedder.embed(f.content)
            ids.append(f.id)
        return ids

    async def recall(
        self, tenant_id, query, *, scopes, mode="graph_completion", limit=20, max_hops=4
    ) -> list[RecallHit]:
        store = self._tenant(tenant_id)
        vecs = self._tenant_vecs(tenant_id)
        allowed = set(scopes)
        has_query = bool((query or "").strip())
        qv = self._embedder.embed(query) if has_query else None

        def _in_scope(f: EngineFact) -> bool:
            return f.owner_scope in allowed

        def _score(f: EngineFact) -> float:
            boost = self._weight.get((tenant_id, f.id), 0.0)
            if qv is None:  # no query -> every in-scope fact is an equal baseline seed
                return 1.0 + boost
            return cosine(qv, vecs.get(f.id, [])) + boost

        # seeds: in-scope facts, ranked by cosine to the query (a positive match,
        # or all in-scope when there is no query). A non-positive cosine is not a
        # match, so it is excluded from the seed set when a query is present.
        candidates = [f for f in store.values() if _in_scope(f)]
        if has_query:
            scored = [(f, _score(f)) for f in candidates]
            seeds = [f for f, s in sorted(scored, key=lambda kv: kv[1], reverse=True) if s > 0.0]
        else:
            seeds = sorted(candidates, key=_score, reverse=True)

        if mode == "similarity":
            return [RecallHit(fact=f, score=_score(f), hops=0, path=[f.id]) for f in seeds[:limit]]

        # graph_completion: BFS over explicit edges, NEVER leaving the allowed
        # scopes (an out-of-scope neighbour is not traversed, SEC-40).
        hits: list[RecallHit] = []
        seen: set[str] = set()
        frontier = [(f, 0, [f.id]) for f in seeds]
        while frontier and len(hits) < limit:
            f, hops, path = frontier.pop(0)
            if f.id in seen:
                continue
            seen.add(f.id)
            hits.append(RecallHit(fact=f, score=_score(f), hops=hops, path=path))
            if hops >= max_hops:
                continue
            for nid in f.relates_to:
                nbr = store.get(nid)
                if nbr is not None and _in_scope(nbr) and nbr.id not in seen:
                    frontier.append((nbr, hops + 1, path + [nbr.id]))
        return hits[:limit]

    async def improve(self, tenant_id: str, signal: str, target: str) -> int:
        delta = 1.0 if signal not in ("down", "negative", "fail") else -1.0
        if target in self._tenant(tenant_id):
            self._weight[(tenant_id, target)] = self._weight.get((tenant_id, target), 0.0) + delta
            return 1
        return 0

    async def forget(self, tenant_id, *, fact_ids=None, source_ref=None, scopes=None) -> list[str]:
        store = self._tenant(tenant_id)
        vecs = self._tenant_vecs(tenant_id)
        allowed = set(scopes) if scopes is not None else None

        def _erasable(f: EngineFact) -> bool:
            return allowed is None or f.owner_scope in allowed

        targets: set[str] = set()
        for fid in fact_ids or []:
            f = store.get(fid)
            if f is not None and _erasable(f):
                targets.add(fid)
        if source_ref is not None:
            targets |= {f.id for f in store.values() if f.source_ref == source_ref and _erasable(f)}

        removed: set[str] = set()
        for fid in targets:
            store.pop(fid, None)
            vecs.pop(fid, None)
            removed.add(fid)
        # derived edges/facts: drop relationship nodes that referenced a removed
        # node, and prune dangling edges everywhere (complete erasure, SEC-44).
        for f in list(store.values()):
            if f.kind == "relationship" and any(r in removed for r in f.relates_to) and _erasable(f):
                store.pop(f.id, None)
                vecs.pop(f.id, None)
                removed.add(f.id)
            else:
                f.relates_to = [r for r in f.relates_to if r not in removed]
        return sorted(removed)

    async def health(self) -> str:
        return "ok"
