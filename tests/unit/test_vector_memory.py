"""The native vector Memory Engine: real cosine-ranked recall, offline (MEM-ENG-02).

``VectorMemoryEngine`` + ``HashingEmbedder`` give genuine vector recall with no
model, no network and no provider key, so these run in the normal offline suite
and prove two things the engine claims:

  * MEM-VEC-01: recall ranks by cosine similarity to the query - a fact that shares
    the query's terms outranks one that does not, and an unrelated fact (cosine ~0)
    is not returned at all;
  * SEC-40: the vector engine is scope-bounded exactly like the naive reference - a
    hostile cross-scope edge, including multi-hop, is never traversed.
"""

import asyncio
import json
import math
import re
from pathlib import Path

import pytest

from boltrig.memory import (
    DEFAULT_DIM,
    EngineFact,
    HashingEmbedder,
    ModelEmbedder,
    VectorMemoryEngine,
    build_embedder,
    cosine,
)

T = "acme"


def test_build_embedder_selects_offline_by_default_and_model_when_configured():
    # no config -> the deterministic offline embedder (no network)
    assert isinstance(build_embedder(None), HashingEmbedder)
    assert isinstance(build_embedder({}), HashingEmbedder)
    # a configured embedding section -> the model-backed seam (constructed, not called)
    e = build_embedder(
        {"embedding": {"base_url": "http://local-embed/v1", "model": "e5-small", "dim": 384}}
    )
    assert isinstance(e, ModelEmbedder)
    assert e.dim == 384 and e.base_url == "http://local-embed/v1" and e.model == "e5-small"


class _EmbeddingResponse:
    def __init__(self, body: bytes, headers: dict[str, str] | None = None) -> None:
        self._body = body
        self.headers = headers or {}
        self.read_sizes: list[int] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self, size: int = -1) -> bytes:
        self.read_sizes.append(size)
        return self._body if size < 0 else self._body[:size]


class _EmbeddingOpener:
    def __init__(self, response: _EmbeddingResponse) -> None:
        self.response = response

    def open(self, _request, *, timeout):
        assert timeout > 0
        return self.response


def _patch_embedding_response(monkeypatch, response: _EmbeddingResponse) -> None:
    import urllib.request

    monkeypatch.setattr(
        urllib.request,
        "build_opener",
        lambda *_handlers: _EmbeddingOpener(response),
    )


@pytest.mark.invariant("SEC-196")
def test_model_embedder_bounds_and_validates_the_remote_vector(monkeypatch):
    raw = json.dumps({"data": [{"embedding": [3.0, 4.0]}]}).encode()
    response = _EmbeddingResponse(raw, {"content-length": str(len(raw))})
    _patch_embedding_response(monkeypatch, response)

    vector = ModelEmbedder(
        base_url="https://models.example/v1", model="embed", dim=2
    ).embed("hello")

    assert vector == [0.6, 0.8]
    assert response.read_sizes == [1024 * 1024 + 1]


@pytest.mark.invariant("SEC-196")
def test_model_embedder_rejects_declared_oversize_before_reading(monkeypatch):
    response = _EmbeddingResponse(
        b"{}", {"content-length": str(1024 * 1024 + 1)}
    )
    _patch_embedding_response(monkeypatch, response)

    with pytest.raises(ValueError, match="safety boundary"):
        ModelEmbedder(
            base_url="https://models.example/v1", model="embed", dim=2
        ).embed("hello")

    assert response.read_sizes == []


@pytest.mark.parametrize(
    "embedding",
    [
        [1.0],
        [1.0, math.inf],
        [1.0, math.nan],
    ],
)
def test_model_embedder_rejects_malformed_vectors(monkeypatch, embedding):
    raw = json.dumps({"data": [{"embedding": embedding}]}).encode()
    response = _EmbeddingResponse(raw)
    _patch_embedding_response(monkeypatch, response)

    with pytest.raises(ValueError, match="dimension|non-finite"):
        ModelEmbedder(
            base_url="https://models.example/v1", model="embed", dim=2
        ).embed("hello")


def test_embedding_dim_matches_schema():
    """The pgvector column dimension in schema.sql must equal DEFAULT_DIM, or a
    durable insert fails at runtime. Pin them together so changing one without the
    other turns the build red (Fix: dim coupling)."""
    schema = Path(__file__).resolve().parents[2] / "boltrig" / "store" / "schema.sql"
    text = schema.read_text(encoding="utf-8")
    m = re.search(r"embedding\s+vector\((\d+)\)", text)
    assert m, "memory_vectors.embedding vector(N) column not found in schema.sql"
    assert int(m.group(1)) == DEFAULT_DIM, (
        f"schema.sql vector({m.group(1)}) != DEFAULT_DIM {DEFAULT_DIM}; update both"
    )


def test_embedder_is_deterministic_and_unit_norm():
    e = HashingEmbedder(dim=128)
    a = e.embed("postgres database migration plan")
    b = e.embed("postgres database migration plan")
    assert a == b  # deterministic across calls (stable hashing, not salted hash())
    assert len(a) == 128
    norm = sum(x * x for x in a) ** 0.5
    assert abs(norm - 1.0) < 1e-9  # L2-normalised -> cosine is a dot product
    # an empty / token-less string yields the zero vector (cosine 0 to everything)
    assert e.embed("") == [0.0] * 128
    # related text is closer than unrelated text under cosine
    related = e.embed("database migration for postgres")
    unrelated = e.embed("sandwich lunch menu options")
    assert cosine(a, related) > cosine(a, unrelated)


@pytest.mark.invariant("MEM-VEC-01")
def test_vector_recall_ranks_by_cosine():
    engine = VectorMemoryEngine()
    asyncio.run(engine.remember(T, [
        EngineFact(id="f1", owner_scope="user:alice", kind="entity",
                   content="database migration plan for the postgres cluster"),
        EngineFact(id="f2", owner_scope="user:alice", kind="entity",
                   content="postgres database migration"),
        EngineFact(id="f3", owner_scope="user:alice", kind="entity",
                   content="lunch menu with sandwiches and salad"),
    ]))
    hits = asyncio.run(engine.recall(
        T, "postgres database migration", scopes=["user:alice"], mode="similarity"))
    ids = [h.fact.id for h in hits]
    # the unrelated fact (cosine ~0) is not a match -> excluded entirely
    assert "f3" not in ids
    # the two relevant facts are returned, best-first (scores descending)
    assert set(ids) == {"f1", "f2"}
    assert hits[0].score >= hits[-1].score
    # the closest fact (an exact subset of the query terms) ranks first
    assert ids[0] == "f2"


@pytest.mark.invariant("SEC-40")
def test_vector_engine_recall_is_scope_bounded_multihop():
    engine = VectorMemoryEngine()
    # a HOSTILE engine state: alice's fact edges into bob's scope, and bob's fact
    # edges deeper to carol - a multi-hop leak attempt.
    asyncio.run(engine.remember(T, [
        EngineFact(id="a1", owner_scope="user:alice", kind="entity",
                   content="migration plan", relates_to=["b1"]),
        EngineFact(id="b1", owner_scope="user:bob", kind="entity",
                   content="bob migration secret", relates_to=["c1"]),
        EngineFact(id="c1", owner_scope="user:carol", kind="entity",
                   content="carol migration secret"),
    ]))
    hits = asyncio.run(engine.recall(
        T, "migration", scopes=["user:alice"], mode="graph_completion", max_hops=4))
    scopes = {h.fact.owner_scope for h in hits}
    assert scopes == {"user:alice"}  # never crossed into bob/carol
    assert all("secret" not in h.fact.content for h in hits)
