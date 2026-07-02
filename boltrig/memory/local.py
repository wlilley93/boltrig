"""A minimal in-process Memory Engine reference for dev / offline (P9).

This is NOT a production knowledge-graph engine (MEM-ENG-01 says adopt Cognee for
that). It is the engine analogue of ``InMemoryStore``: just enough to exercise the
interface contract and the kernel's isolation guarantees offline - naive keyword
matching for similarity, explicit edges for the graph, and scope-bounded traversal
so a hostile cross-scope recall (including multi-hop) cannot reach an out-of-scope
fact. The kernel re-checks scope regardless; this engine simply does not cheat.
"""

from __future__ import annotations

from .engine import EngineFact, RecallHit, signal_delta


def _tokens(text: str) -> set[str]:
    return {t for t in "".join(c.lower() if c.isalnum() else " " for c in text).split() if t}


class LocalMemoryEngine:
    def __init__(self) -> None:
        self._facts: dict[str, dict[str, EngineFact]] = {}  # tenant -> id -> fact
        self._weight: dict[tuple[str, str], float] = {}  # (tenant, id) -> boost

    def _tenant(self, tenant_id: str) -> dict[str, EngineFact]:
        return self._facts.setdefault(tenant_id, {})

    async def remember(self, tenant_id: str, facts: list[EngineFact]) -> list[str]:
        store = self._tenant(tenant_id)
        ids: list[str] = []
        for f in facts:
            store[f.id] = f
            ids.append(f.id)
        return ids

    async def recall(
        self, tenant_id, query, *, scopes, mode="graph_completion", limit=20, max_hops=4
    ) -> list[RecallHit]:
        store = self._tenant(tenant_id)
        allowed = set(scopes)
        q = _tokens(query)

        def _in_scope(f: EngineFact) -> bool:
            return f.owner_scope in allowed

        def _score(f: EngineFact) -> float:
            overlap = len(q & _tokens(f.content))
            base = float(overlap) if q else 1.0
            return base + self._weight.get((tenant_id, f.id), 0.0)

        # seeds: in-scope facts that match the query (or all in-scope if no query)
        seeds = sorted(
            (f for f in store.values() if _in_scope(f) and (not q or q & _tokens(f.content))),
            key=_score, reverse=True,
        )
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
        # a positive signal boosts the target's recall weight; scope is untouched.
        delta = signal_delta(signal)
        if target in self._tenant(tenant_id):
            self._weight[(tenant_id, target)] = self._weight.get((tenant_id, target), 0.0) + delta
            return 1
        return 0

    async def forget(self, tenant_id, *, fact_ids=None, source_ref=None, scopes=None) -> list[str]:
        store = self._tenant(tenant_id)
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
            removed.add(fid)
        # derived edges/facts: drop relationship nodes that referenced a removed
        # node, and prune dangling edges everywhere (complete erasure, SEC-44).
        for f in list(store.values()):
            if f.kind == "relationship" and any(r in removed for r in f.relates_to) and _erasable(f):
                store.pop(f.id, None)
                removed.add(f.id)
            else:
                f.relates_to = [r for r in f.relates_to if r not in removed]
        return sorted(removed)

    async def health(self) -> str:
        return "ok"
