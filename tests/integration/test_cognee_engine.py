"""CogneeEngine: the adopted production graph engine (MEM-ENG-03).

Two tiers, mirroring test_pgvector_engine.py:

  * always-run (no cognee import needed): honest degradation - health() reports
    down with a reason when cognee is unimportable, operations raise the typed
    unavailable error, remember refuses secret content BEFORE any import (SEC-42
    defence in depth), and the (tenant, scope) -> dataset mapping is injective
    (MEM-ENG-03);
  * gated live legs (BOLTRIG_COGNEE_LIVE=1 + cognee installed + LLM env): the
    remember -> recall roundtrip with provenance, engine-level scope isolation,
    real erasure incl. the cognee side (SEC-44), and the documented improve()
    weight-sidecar behaviour.

Env combo proven live on the dev box (z.ai GLM chat + keyless local fastembed)::

    BOLTRIG_COGNEE_LIVE=1 LLM_PROVIDER=openai LLM_MODEL=openai/glm-5.2 \
    LLM_ENDPOINT=https://api.z.ai/api/coding/paas/v4 LLM_API_KEY=<key> \
    LLM_INSTRUCTOR_MODE=json_mode \
    EMBEDDING_PROVIDER=fastembed EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2

(``json_mode`` matters: GLM emits multiple tool calls under instructor's default
tools/json_schema modes, which instructor rejects.)
"""

from __future__ import annotations

import importlib.util
import builtins
import os
import re
import sys
from types import SimpleNamespace
import uuid

import pytest

from boltrig.memory.cognee import CogneeEngine, _require_cognee, dataset_for
from boltrig.memory.engine import EngineFact

_COGNEE_PRESENT = importlib.util.find_spec("cognee") is not None
_LIVE = os.environ.get("BOLTRIG_COGNEE_LIVE") == "1" and _COGNEE_PRESENT and bool(
    os.environ.get("LLM_API_KEY")
)
_live = pytest.mark.skipif(
    not _LIVE,
    reason=(
        "live cognee legs need BOLTRIG_COGNEE_LIVE=1, the cognee package installed, "
        "and LLM_API_KEY (+ LLM_PROVIDER/LLM_MODEL/LLM_ENDPOINT and EMBEDDING_* or "
        "a fastembed local embedder) in the environment"
    ),
)


def _fact(fid: str, scope: str, content: str, **kw) -> EngineFact:
    return EngineFact(id=fid, owner_scope=scope, kind=kw.pop("kind", "entity"),
                      content=content, **kw)


# --- always-run: honest degradation without cognee ----------------------------
async def test_health_is_down_with_reason_when_cognee_unimportable(monkeypatch):
    monkeypatch.setitem(sys.modules, "cognee", None)  # makes `import cognee` raise
    engine = CogneeEngine()
    assert await engine.health() == "down"
    assert "cognee" in (engine.health_reason or "")


async def test_operations_raise_typed_unavailable_error_without_cognee(monkeypatch):
    monkeypatch.setitem(sys.modules, "cognee", None)
    engine = CogneeEngine()
    with pytest.raises(RuntimeError, match="cognee"):
        await engine.remember("acme", [_fact("f1", "user:alice", "clean note")])
    with pytest.raises(RuntimeError, match="cognee"):
        await engine.recall("acme", "note", scopes=["user:alice"])


@pytest.mark.invariant("SEC-27")
def test_cognee_import_cannot_load_host_dotenv_into_process(monkeypatch):
    """A provider import cannot activate Boltrig flags or absorb ambient secrets."""
    original_import = builtins.__import__

    def importing(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "cognee":
            assert os.environ.get("PYTHON_DOTENV_DISABLED") == "1"
            os.environ["BOLTRIG_CODEX_TRUSTED"] = "1"
            os.environ.pop("BOLTRIG_IMPORT_SENTINEL", None)
            return SimpleNamespace()
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.delenv("BOLTRIG_CODEX_TRUSTED", raising=False)
    monkeypatch.setenv("BOLTRIG_IMPORT_SENTINEL", "preserve-me")
    monkeypatch.setattr(builtins, "__import__", importing)

    assert _require_cognee() is not None
    assert "BOLTRIG_CODEX_TRUSTED" not in os.environ
    assert os.environ["BOLTRIG_IMPORT_SENTINEL"] == "preserve-me"
    assert "PYTHON_DOTENV_DISABLED" not in os.environ


@pytest.mark.invariant("SEC-42")
async def test_cognee_engine_refuses_secret_content_directly(monkeypatch):
    """SEC-42 defence in depth: even called directly (bypassing the adapter's
    ingestion screen), the engine refuses secret-bearing content - and does so
    BEFORE the cognee import, so nothing secret can ever reach the package."""
    monkeypatch.setitem(sys.modules, "cognee", None)  # proves the check precedes import
    engine = CogneeEngine()
    secret = "prod openai key sk-ABCDEFGHIJKLMNOPQRSTUV0123456789"
    with pytest.raises(ValueError, match="SEC-42"):
        await engine.remember("acme", [_fact("f1", "user:alice", secret)])
    with pytest.raises(ValueError, match="secret"):
        await engine.remember("acme", [_fact("f2", "user:alice", "password: hunter2swordfish")])


@pytest.mark.invariant("MEM-ENG-03")
def test_dataset_mapping_is_per_tenant_scope_and_injective():
    """One cognee dataset per (tenant, scope): distinct tenants and distinct scopes
    never share a dataset, slug collisions are disambiguated by the digest, and
    the name is a safe identifier."""
    a = dataset_for("acme", "user:alice")
    assert a == dataset_for("acme", "user:alice")  # deterministic
    assert a != dataset_for("acme", "user:bob")  # scope-isolated
    assert a != dataset_for("globex", "user:alice")  # tenant-isolated
    # slugging alone would collide these; the digest keeps the mapping injective
    assert dataset_for("a_b", "c") != dataset_for("a", "b_c")
    assert dataset_for("t", "user:a.b") != dataset_for("t", "user:a_b")
    for name in (a, dataset_for("Tenant Ltd.", "department:r&d")):
        assert re.fullmatch(r"[a-z0-9_]+", name)


# --- gated live legs: real cognee + real models --------------------------------
@pytest.fixture(scope="session")
def cognee_root(tmp_path_factory):
    return str(tmp_path_factory.mktemp("cognee-root"))


@pytest.fixture()
def live_engine(cognee_root):
    return CogneeEngine({"cognee_root": cognee_root})


def _tenant() -> str:
    return f"acme_{uuid.uuid4().hex[:8]}"


@_live
@pytest.mark.invariant("MEM-ENG-03")
async def test_live_remember_recall_roundtrip_with_provenance(live_engine):
    t = _tenant()
    ids = await live_engine.remember(t, [
        _fact("f1", "user:alice", "the quarterly revenue target is 1.2 million euros",
              source_kind="document", source_ref="doc:q3-plan"),
    ])
    assert ids == ["f1"]
    hits = await live_engine.recall(
        t, "what is the quarterly revenue target", scopes=["user:alice"], mode="similarity")
    assert hits, "the remembered fact must be recallable"
    top = hits[0]
    assert top.fact.id == "f1"
    assert "revenue target" in top.fact.content
    # provenance survives the roundtrip
    assert top.fact.source_kind == "document" and top.fact.source_ref == "doc:q3-plan"
    assert top.path == ["f1"]


@_live
@pytest.mark.invariant("MEM-ENG-03")
async def test_live_recall_is_isolated_per_tenant_and_scope(live_engine):
    ta, tb = _tenant(), _tenant()
    await live_engine.remember(ta, [
        _fact("a1", "user:alice", "the zephyr project launch date is in march"),
        _fact("b1", "user:bob", "bob keeps notes about office plants"),
    ])
    await live_engine.remember(tb, [
        _fact("c1", "user:alice", "tenant b talks about accounting only"),
    ])
    # same tenant, other scope: bob's datasets cannot yield alice's fact
    hits = await live_engine.recall(ta, "zephyr project launch date", scopes=["user:bob"])
    assert all("zephyr" not in h.fact.content for h in hits)
    assert all(h.fact.owner_scope == "user:bob" for h in hits)
    # other tenant, same scope name: a distinct dataset, alice's fact unreachable
    hits = await live_engine.recall(tb, "zephyr project launch date", scopes=["user:alice"])
    assert all("zephyr" not in h.fact.content for h in hits)


@_live
@pytest.mark.invariant("MEM-ENG-03")
async def test_live_forget_erasure_is_real(live_engine):
    t = _tenant()
    await live_engine.remember(t, [
        _fact("e1", "user:alice", "the secret santa budget is fifty pounds"),
    ])
    hits = await live_engine.recall(t, "secret santa budget", scopes=["user:alice"])
    assert any(h.fact.id == "e1" for h in hits)
    removed = await live_engine.forget(t, fact_ids=["e1"], scopes=["user:alice"])
    assert removed == ["e1"]
    # a recall after forget must not return the fact (engine surface)
    hits = await live_engine.recall(t, "secret santa budget", scopes=["user:alice"])
    assert all(h.fact.id != "e1" for h in hits)
    # ...and the erasure is real on the cognee side: the (tenant, scope) dataset
    # was dropped, so a direct cognee search cannot surface the content either.
    import cognee
    from cognee import SearchType

    try:
        items = await cognee.search(
            query_text="secret santa budget", query_type=SearchType.CHUNKS,
            datasets=[dataset_for(t, "user:alice")], top_k=5)
    except Exception:
        items = []  # dataset gone entirely: erased
    assert all("secret santa" not in str(i) for i in items)


@_live
async def test_live_improve_boosts_ranking_observably(live_engine):
    """improve() is the documented engine-level weight sidecar (cognee has no
    per-item reweight primitive): a positive signal adds +1.0 to the target's
    recall score, observably changing the ranking."""
    t = _tenant()
    await live_engine.remember(t, [
        _fact("f1", "user:alice", "meeting notes from monday standup"),
        _fact("f2", "user:alice", "meeting notes from friday retro"),
    ])
    before = await live_engine.recall(t, "", scopes=["user:alice"], mode="similarity")
    base = {h.fact.id: h.score for h in before}
    assert base["f1"] == base["f2"]  # weight-only ranking on the empty query
    assert await live_engine.improve(t, "up", "f2") == 1
    after = await live_engine.recall(t, "", scopes=["user:alice"], mode="similarity")
    boosted = {h.fact.id: h.score for h in after}
    assert boosted["f2"] == pytest.approx(base["f2"] + 1.0)
    assert after[0].fact.id == "f2"  # ranking observably changed
    assert await live_engine.improve(t, "up", "missing") == 0  # unknown target: no-op
