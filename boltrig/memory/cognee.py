"""Cognee Memory Engine (MEM-ENG-03): the ADOPTED production graph engine.

Cognee is the reference production Memory Engine: self-hostable, permissively
licensed, provider-agnostic for extraction/embedding (so sensitive data can use a
local endpoint, SEC-43). It is ADOPTED behind ``MemoryEngine``, not built here.
This module is the single place that touches the ``cognee`` package; it
lazy-imports inside methods so the rest of Boltrig is import-safe and offline-safe
without it.

Tenancy mapping (SEC-40 defence in depth). One cognee dataset per
``(tenant_id, owner_scope)``::

    dataset = "bt_" + slug(tenant) + "_" + slug(scope) + "_" + sha256(tenant NUL scope)[:10]

``recall`` and ``forget`` only ever address the datasets of the scopes they are
given, so a cross-tenant or cross-scope read is impossible at the engine level
too - the kernel (MemoryAdapter) re-checks scope on everything returned
regardless. The digest suffix keeps the mapping injective after slugging, so two
distinct (tenant, scope) pairs can never share a dataset.

Honest degradations (documented, not hidden):

  * SEC-42 defence in depth: ``remember`` refuses secret-bearing content via
    ``boltrig.kernel.pii.contains_secret`` BEFORE anything is imported or sent to
    cognee. The adapter blocks secrets first; this is the cheap second net.
  * Provenance mapping (fact ids, explicit edges, improve() weights) lives in an
    in-instance index; cognee stores the content durably but the id mapping is
    per-process. The durable governance ledger is the kernel store's
    ``memory_facts`` - the engine index is a session cache.
  * ``improve``: cognee has no per-item reweight primitive (its ``improve()`` is a
    graph-enrichment pipeline), so improve() is an engine-level weight sidecar
    applied at recall scoring, exactly like the native engines (SEC-41: scope and
    authority untouched).
  * ``recall``: both modes retrieve via cognee CHUNKS search (cognee's own
    GRAPH_COMPLETION returns LLM prose, not fact nodes, so it cannot honour the
    ``RecallHit`` contract); ``graph_completion`` mode then traverses the engine's
    explicit ``relates_to`` edges without ever leaving the permitted scopes.
  * ``forget``: REAL erasure (SEC-44). The affected (tenant, scope) dataset is
    dropped in cognee (data + graph + vectors via ``cognee.forget``) and rebuilt
    from the surviving facts only, so a recall after forget cannot return the
    fact from any layer.

Model configuration. Cognee reads its own env names (pydantic settings):
``LLM_PROVIDER`` / ``LLM_MODEL`` / ``LLM_ENDPOINT`` / ``LLM_API_KEY`` and
``EMBEDDING_PROVIDER`` / ``EMBEDDING_MODEL`` / ``EMBEDDING_ENDPOINT`` /
``EMBEDDING_API_KEY`` / ``EMBEDDING_DIMENSIONS`` (OpenAI-compatible endpoints
included; ``fastembed`` gives keyless local embeddings). The engine maps its
config block onto those env names without overriding values already set::

    {"llm": {"provider": ..., "model": ..., "endpoint": ..., "api_key": ...},
     "embedding": {...same keys..., "dimensions": ...},
     "cognee_root": "/dir/for/cognee/data+system"}
"""

from __future__ import annotations

import hashlib
import os
import re
import threading
from typing import Any

from boltrig.kernel.pii import contains_secret

from .engine import EngineFact, RecallHit, signal_delta

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_COGNEE_IMPORT_LOCK = threading.Lock()


def _slug(value: str, max_len: int = 24) -> str:
    return _SLUG_RE.sub("_", value.lower()).strip("_")[:max_len] or "x"


def dataset_for(tenant_id: str, owner_scope: str) -> str:
    """The injective (tenant, scope) -> cognee dataset mapping (MEM-ENG-03)."""
    digest = hashlib.sha256(f"{tenant_id}\x00{owner_scope}".encode()).hexdigest()[:10]
    return f"bt_{_slug(tenant_id)}_{_slug(owner_scope)}_{digest}"


def _item_payload(item: Any) -> tuple[str, float | None]:
    """Text + score from one cognee search hit (dict or SearchResultItem shaped)."""
    if isinstance(item, dict):
        return str(item.get("text") or item.get("content") or item), item.get("score")
    return (getattr(item, "text", None) or str(item)), getattr(item, "score", None)


def _require_cognee() -> Any:
    # Cognee imports python-dotenv and may otherwise load the host repository's
    # ambient .env into os.environ. A projection library must never activate
    # unrelated Boltrig process settings or ingest undelegated credentials. The
    # documented python-dotenv kill switch prevents the load; the snapshot is a
    # defence-in-depth cleanup for any other import-time mutation.
    with _COGNEE_IMPORT_LOCK:
        before = dict(os.environ)
        os.environ["PYTHON_DOTENV_DISABLED"] = "1"
        try:
            import cognee
        except ImportError as exc:  # pragma: no cover - exercised via monkeypatched import
            raise RuntimeError(
                "CogneeEngine requires the 'cognee' package "
                "(pip install 'boltrig[cognee]'). Memory engines are ADOPTED, "
                "not built (MEM-ENG-01)."
            ) from exc
        finally:
            for key in set(os.environ) - set(before):
                os.environ.pop(key, None)
            for key, value in before.items():
                if os.environ.get(key) != value:
                    os.environ[key] = value
    return cognee


class CogneeEngine:
    """The adopted production engine. Construction is cheap (no import); the cognee
    library is required only when an operation runs, so config can be validated and
    the offline suite stays green without the package installed."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = dict(config or {})
        self._env_applied = False
        self._index: dict[str, dict[str, EngineFact]] = {}  # tenant -> id -> fact
        self._weight: dict[tuple[str, str], float] = {}  # (tenant, id) -> boost
        self._scopes: dict[str, set[str]] = {}  # tenant -> scopes with a live dataset
        self.health_reason: str | None = None

    # --- configuration -------------------------------------------------------
    def _prime_env(self) -> None:
        """Expose only explicitly configured Cognee model settings before import."""
        for section, prefix in (("llm", "LLM"), ("embedding", "EMBEDDING")):
            block = self._config.get(section) or {}
            for key in ("provider", "model", "endpoint", "api_key", "dimensions"):
                value = block.get(key)
                if value is not None:
                    os.environ.setdefault(f"{prefix}_{key.upper()}", str(value))

    def _apply_env(self, cognee: Any) -> None:
        """Map the manifest config onto cognee's env names (already-set env wins),
        and point cognee's data/system roots at ``cognee_root`` when given. Runs
        once, before cognee's cached settings are first read."""
        if self._env_applied:
            return
        root = self._config.get("cognee_root")
        if root:
            cognee.config.data_root_directory(str(root))
            cognee.config.system_root_directory(str(root))
        self._env_applied = True

    def _ready(self) -> Any:
        self._prime_env()
        cognee = _require_cognee()
        self._apply_env(cognee)
        return cognee

    def _dataset(self, tenant_id: str, owner_scope: str) -> str:
        return dataset_for(tenant_id, owner_scope)

    # --- MemoryEngine --------------------------------------------------------
    async def remember(self, tenant_id: str, facts: list[EngineFact]) -> list[str]:
        # SEC-42 defence in depth: refuse secret-bearing content before the cognee
        # import, so nothing secret can ever reach the package or its stores. The
        # adapter already screens at the ingestion boundary; this is the second net.
        for f in facts:
            secret_kind = contains_secret(f.content)
            if secret_kind:
                raise ValueError(
                    f"fact {f.id}: content contains a secret ({secret_kind}); "
                    "refusing to persist into cognee (SEC-42)"
                )
        cognee = self._ready()
        ids: list[str] = []
        touched: set[str] = set()
        for f in facts:
            ds = self._dataset(tenant_id, f.owner_scope)
            await cognee.add(f.content, dataset_name=ds)
            self._index.setdefault(tenant_id, {})[f.id] = f
            self._scopes.setdefault(tenant_id, set()).add(f.owner_scope)
            touched.add(ds)
            ids.append(f.id)
        if touched:
            await cognee.cognify(datasets=sorted(touched))
        return ids

    async def recall(
        self,
        tenant_id: str,
        query: str,
        *,
        scopes: list[str],
        mode: str = "graph_completion",
        limit: int = 20,
        max_hops: int = 4,
    ) -> list[RecallHit]:
        cognee = self._ready()
        allowed = set(scopes)
        store = self._index.get(tenant_id, {})
        in_scope = {fid: f for fid, f in store.items() if f.owner_scope in allowed}
        if not in_scope:
            return []

        def _boost(fid: str) -> float:
            return self._weight.get((tenant_id, fid), 0.0)

        scored: dict[str, float] = {}
        if (query or "").strip():
            # only the datasets of the requested scopes are ever addressed (SEC-40)
            live = self._scopes.get(tenant_id, set())
            datasets = [self._dataset(tenant_id, s) for s in scopes if s in live]
            if not datasets:
                return []
            from cognee import SearchType

            items = await cognee.search(
                query_text=query,
                query_type=SearchType.CHUNKS,
                datasets=datasets,
                top_k=max(limit * 4, limit),
            )
            for rank, item in enumerate(items):
                text, base = _item_payload(item)
                base = float(base) if base is not None else 1.0 / (1.0 + rank)
                for fid, f in in_scope.items():
                    if f.content and (f.content in text or text in f.content):
                        score = base + _boost(fid)
                        scored[fid] = max(score, scored.get(fid, float("-inf")))
        else:
            # no query -> all in-scope facts, weight-ranked (native-engine parity)
            scored = {fid: 1.0 + _boost(fid) for fid in in_scope}

        seeds = sorted(scored, key=lambda fid: scored[fid], reverse=True)
        if mode == "similarity":
            return [
                RecallHit(fact=in_scope[fid], score=scored[fid], hops=0, path=[fid])
                for fid in seeds[:limit]
            ]

        # graph_completion: BFS over explicit edges, NEVER leaving the allowed
        # scopes - an out-of-scope neighbour is not traversed (SEC-40).
        hits: list[RecallHit] = []
        seen: set[str] = set()
        frontier = [(fid, 0, [fid]) for fid in seeds]
        while frontier and len(hits) < limit:
            fid, hops, path = frontier.pop(0)
            if fid in seen:
                continue
            seen.add(fid)
            score = scored.get(fid, _boost(fid))
            hits.append(RecallHit(fact=in_scope[fid], score=score, hops=hops, path=path))
            if hops >= max_hops:
                continue
            for nid in in_scope[fid].relates_to:
                if nid in in_scope and nid not in seen:
                    frontier.append((nid, hops + 1, path + [nid]))
        return hits[:limit]

    async def improve(self, tenant_id: str, signal: str, target: str) -> int:
        """Engine-level weight sidecar: cognee has no per-item reweight primitive,
        so a signal adjusts the recall boost only - never scope or authority
        (SEC-41). Instance-scoped, exactly like the native engines' weights."""
        self._ready()
        delta = signal_delta(signal)
        if target in self._index.get(tenant_id, {}):
            key = (tenant_id, target)
            self._weight[key] = self._weight.get(key, 0.0) + delta
            return 1
        return 0

    async def forget(
        self,
        tenant_id: str,
        *,
        fact_ids: list[str] | None = None,
        source_ref: str | None = None,
        scopes: list[str] | None = None,
    ) -> list[str]:
        """REAL erasure (SEC-44): resolve targets (plus derived relationship nodes),
        then drop each affected (tenant, scope) dataset in cognee and rebuild it
        from the surviving facts only."""
        cognee = self._ready()
        store = self._index.get(tenant_id, {})
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
        affected_scopes: set[str] = set()
        for fid in targets:
            f = store.pop(fid, None)
            if f is not None:
                affected_scopes.add(f.owner_scope)
                removed.add(fid)
        # derived edges/facts: drop relationship nodes that referenced a removed
        # node, and prune dangling edges everywhere (complete erasure, SEC-44).
        for f in list(store.values()):
            if f.kind == "relationship" and any(r in removed for r in f.relates_to) and _erasable(f):
                store.pop(f.id, None)
                affected_scopes.add(f.owner_scope)
                removed.add(f.id)
            else:
                f.relates_to = [r for r in f.relates_to if r not in removed]

        # cognee-side erasure: drop + rebuild each affected dataset.
        live = self._scopes.get(tenant_id, set())
        for scope in affected_scopes & live:
            ds = self._dataset(tenant_id, scope)
            await cognee.forget(dataset=ds)
            survivors = [f for f in store.values() if f.owner_scope == scope]
            if survivors:
                for f in survivors:
                    await cognee.add(f.content, dataset_name=ds)
                await cognee.cognify(datasets=[ds])
            else:
                live.discard(scope)
        for fid in removed:
            self._weight.pop((tenant_id, fid), None)
        return sorted(removed)

    async def health(self) -> str:
        """'down' + reason when cognee is unimportable; 'degraded' + reason when it
        is importable but no LLM is configured (cognify would fail); else 'ok'."""
        try:
            self._ready()
        except Exception as exc:
            self.health_reason = f"cognee not importable: {exc}"
            return "down"
        llm_cfg = self._config.get("llm") or {}
        provider = os.environ.get("LLM_PROVIDER") or llm_cfg.get("provider") or "openai"
        api_key = os.environ.get("LLM_API_KEY") or llm_cfg.get("api_key")
        if provider not in ("ollama", "llama_cpp") and not api_key:
            self.health_reason = (
                "cognee importable but no LLM configured (set LLM_API_KEY or memory.llm.api_key)"
            )
            return "degraded"
        self.health_reason = None
        return "ok"
