"""Sleep-distillation corpus builder (decision 0023) - DIS-1..3.

The corpus is a derived, rebuildable view over the governed record. These
tests bind its three refusal fences: the tenant fence, the sensitive-only
target fence, and erasure-by-exclusion with the watermark in the digest.
"""

from __future__ import annotations

import json

import pytest

from boltrig.distill import (
    CorpusDataClassRefused,
    CorpusTenantMismatch,
    PrefRecord,
    SftRecord,
    build_corpus,
    corpus_jsonl_lines,
)
from boltrig.models import (
    ActionType,
    AuditEvent,
    Conversation,
    ConversationMessage,
    EvalRun,
    HITLRequest,
    HITLResponse,
    HITLType,
    MemoryErasure,
    MessageRole,
    Urgency,
    User,
    utcnow,
)
from boltrig.store.memory import InMemoryStore

T = "acme"
BASE = "mlx-community/Qwen2.5-7B-Instruct-4bit@rev-abc"


async def _seeded_store(tenant: str = T) -> InMemoryStore:
    store = InMemoryStore()
    await store.upsert_user(User(id="u1", tenant_id=tenant))
    await store.create_conversation(
        Conversation(id="c1", tenant_id=tenant, user_id="u1")
    )
    return store


def _msg(conv: str, mid: str, role: MessageRole, content: str, **kw) -> ConversationMessage:
    return ConversationMessage(
        id=mid,
        conversation_id=conv,
        tenant_id=kw.pop("tenant_id", T),
        role=role,
        content=content,
        **kw,
    )


async def _clean_run(store: InMemoryStore, run_id: str, tenant: str = T) -> None:
    await store.audit_append(
        AuditEvent(
            tenant_id=tenant, ts=utcnow(), actor="agent", actor_tier="ephemeral",
            action_type=ActionType.TOOL_CALL, verb="ticket.create", status="ok",
            run_id=run_id,
        )
    )


@pytest.mark.invariant("DIS-1")
async def test_cross_tenant_record_is_refused_not_filtered():
    store = await _seeded_store()
    # a conversation row claiming another tenant is a refusal, never a filter
    await store.create_conversation(
        Conversation(id="c-evil", tenant_id=T, user_id="u1")
    )
    store._convs[(T, "c-evil")].tenant_id = "mallory"  # simulate a corrupted row
    with pytest.raises(CorpusTenantMismatch):
        await build_corpus(
            store, T, base_pin=BASE, target_tenant_id=T, target_data_class="sensitive"
        )


@pytest.mark.invariant("DIS-1")
async def test_target_endpoint_of_another_tenant_is_refused():
    store = await _seeded_store()
    with pytest.raises(CorpusTenantMismatch):
        await build_corpus(
            store, T, base_pin=BASE, target_tenant_id="other-tenant",
            target_data_class="sensitive",
        )


@pytest.mark.invariant("DIS-2")
async def test_standard_classed_target_is_refused():
    store = await _seeded_store()
    with pytest.raises(CorpusDataClassRefused):
        await build_corpus(
            store, T, base_pin=BASE, target_tenant_id=T, target_data_class="standard"
        )


@pytest.mark.invariant("DIS-3")
async def test_erased_conversation_is_excluded_and_watermark_changes_digest():
    store = await _seeded_store()
    await store.add_message(_msg("c1", "m1", MessageRole.USER, "make a ticket"))
    await store.add_message(
        _msg("c1", "m2", MessageRole.ASSISTANT, "done, ticket T-1", run_id="r1")
    )
    await _clean_run(store, "r1")

    before = await build_corpus(
        store, T, base_pin=BASE, target_tenant_id=T, target_data_class="sensitive"
    )
    assert [r.record_id for r in before.records] == ["sft:c1:m2"]
    assert before.erasure_watermark is None

    await store.add_memory_erasure(
        MemoryErasure(id="e1", tenant_id=T, requested_by="u1", target="c1", scope="conversation")
    )
    after = await build_corpus(
        store, T, base_pin=BASE, target_tenant_id=T, target_data_class="sensitive"
    )
    assert after.records == ()  # erasure is satisfied by exclusion at rebuild
    assert after.erasure_watermark is not None
    assert after.digest != before.digest  # the watermark is part of the digest


@pytest.mark.invariant("DIS-3")
async def test_erasure_by_run_id_excludes_the_conversation():
    store = await _seeded_store()
    await store.add_message(_msg("c1", "m1", MessageRole.USER, "hello"))
    await store.add_message(
        _msg("c1", "m2", MessageRole.ASSISTANT, "hi there", run_id="r9")
    )
    await _clean_run(store, "r9")
    await store.add_memory_erasure(
        MemoryErasure(id="e2", tenant_id=T, requested_by="u1", target="r9", scope="run")
    )
    corpus = await build_corpus(
        store, T, base_pin=BASE, target_tenant_id=T, target_data_class="sensitive"
    )
    assert corpus.records == ()


async def test_signals_hitl_eval_and_clean_run():
    store = await _seeded_store()
    # hitl_approved
    await store.create_hitl_request(
        HITLRequest(
            id="h1", tenant_id=T, run_id="r1", type=HITLType.APPROVAL,
            urgency=Urgency.BLOCKING, context="", question="ok?",
        )
    )
    await store.answer_hitl(
        HITLResponse(
            id="hr1", request_id="h1", tenant_id=T, decision="approve",
            respondent="u1", responded_at=utcnow(),
        )
    )
    await store.add_message(_msg("c1", "m1", MessageRole.USER, "do the thing"))
    await store.add_message(
        _msg("c1", "m2", MessageRole.ASSISTANT, "approved and done",
             run_id="r1", hitl_request_id="h1")
    )
    # eval_pass
    await store.add_eval_run(
        EvalRun(id="ev1", tenant_id=T, case_id="case", passed=True, score=0.9, run_id="r2")
    )
    await store.add_message(
        _msg("c1", "m3", MessageRole.ASSISTANT, "eval-passing answer", run_id="r2")
    )
    # clean_run
    await _clean_run(store, "r3")
    await store.add_message(
        _msg("c1", "m4", MessageRole.ASSISTANT, "clean answer", run_id="r3")
    )
    # unlabelled: no run, no hitl - never trains
    await store.add_message(_msg("c1", "m5", MessageRole.ASSISTANT, "unlabelled"))
    # denied run - never trains
    await store.audit_append(
        AuditEvent(
            tenant_id=T, ts=utcnow(), actor="agent", actor_tier="ephemeral",
            action_type=ActionType.TOOL_CALL, verb="ticket.delete", status="denied",
            run_id="r4",
        )
    )
    await store.add_message(
        _msg("c1", "m6", MessageRole.ASSISTANT, "denied answer", run_id="r4")
    )

    corpus = await build_corpus(
        store, T, base_pin=BASE, target_tenant_id=T, target_data_class="sensitive"
    )
    signals = {r.record_id: r.signal for r in corpus.records}
    assert signals == {
        "sft:c1:m2": "hitl_approved",
        "sft:c1:m3": "eval_pass",
        "sft:c1:m4": "clean_run",
    }
    scores = {r.record_id: r.eval_score for r in corpus.records}
    assert scores["sft:c1:m3"] == 0.9


async def test_superseded_reply_becomes_a_preference_pair():
    store = await _seeded_store()
    await store.add_message(_msg("c1", "m1", MessageRole.USER, "summarise this"))
    await store.add_message(
        _msg("c1", "m2", MessageRole.ASSISTANT, "a weak summary", run_id="r1")
    )
    await store.add_message(
        _msg("c1", "m3", MessageRole.ASSISTANT, "a strong summary", run_id="r2")
    )
    await store.mark_message_superseded(T, "m2", "m3")
    await _clean_run(store, "r2")

    corpus = await build_corpus(
        store, T, base_pin=BASE, target_tenant_id=T, target_data_class="sensitive"
    )
    prefs = [r for r in corpus.records if isinstance(r, PrefRecord)]
    assert len(prefs) == 1
    assert prefs[0].rejected == "a weak summary"
    assert prefs[0].chosen == "a strong summary"
    # the superseded turn is NOT also an sft record, and never enters continuity
    sft = [r for r in corpus.records if isinstance(r, SftRecord)]
    assert [r.completion for r in sft] == ["a strong summary"]
    assert all("a weak summary" not in dict(r.prompt).values() for r in sft)


async def test_secrets_refuse_the_record_and_pii_is_redacted():
    store = await _seeded_store()
    await store.add_message(_msg("c1", "m1", MessageRole.USER, "email bob@example.com"))
    await store.add_message(
        _msg("c1", "m2", MessageRole.ASSISTANT, "sent to bob@example.com", run_id="r1")
    )
    await _clean_run(store, "r1")
    # a secret anywhere in the trace refuses the whole record
    await store.add_message(
        _msg("c1", "m3", MessageRole.ASSISTANT,
             "the key is sk-ant-abcdefghijklmnop1234", run_id="r2")
    )
    await _clean_run(store, "r2")

    corpus = await build_corpus(
        store, T, base_pin=BASE, target_tenant_id=T, target_data_class="sensitive"
    )
    ids = [r.record_id for r in corpus.records]
    assert "sft:c1:m3" not in ids  # refused, not redacted
    (rec,) = [r for r in corpus.records if r.record_id == "sft:c1:m2"]
    assert "bob@example.com" not in rec.completion
    assert "[REDACTED:email]" in rec.completion
    assert all("bob@example.com" not in text for _, text in rec.prompt)


async def test_secure_hitl_answer_never_enters_a_corpus():
    store = await _seeded_store()
    await store.create_hitl_request(
        HITLRequest(
            id="h1", tenant_id=T, run_id="r1", type=HITLType.QUESTION,
            urgency=Urgency.BLOCKING, context="", question="api key?",
            secure=True, secure_purpose="credential",
        )
    )
    await store.answer_hitl(
        HITLResponse(
            id="hr1", request_id="h1", tenant_id=T, decision="approve",
            respondent="u1", responded_at=utcnow(),
        )
    )
    await store.add_message(
        _msg("c1", "m1", MessageRole.ASSISTANT, "thanks, connected",
             run_id="r1", hitl_request_id="h1")
    )
    await _clean_run(store, "r1")
    corpus = await build_corpus(
        store, T, base_pin=BASE, target_tenant_id=T, target_data_class="sensitive"
    )
    assert corpus.records == ()


async def test_digest_is_deterministic_and_pins_base_and_split():
    store = await _seeded_store()
    await store.add_message(_msg("c1", "m1", MessageRole.USER, "q"))
    await store.add_message(
        _msg("c1", "m2", MessageRole.ASSISTANT, "a", run_id="r1")
    )
    await _clean_run(store, "r1")
    one = await build_corpus(
        store, T, base_pin=BASE, target_tenant_id=T, target_data_class="sensitive"
    )
    two = await build_corpus(
        store, T, base_pin=BASE, target_tenant_id=T, target_data_class="sensitive"
    )
    assert one.digest == two.digest
    assert one.held_out == two.held_out  # split is id-deterministic, no RNG
    other_base = await build_corpus(
        store, T, base_pin="other-base@rev-z", target_tenant_id=T,
        target_data_class="sensitive",
    )
    assert other_base.digest != one.digest  # the base pin is in the digest


async def test_jsonl_round_trip_carries_digest_and_records():
    store = await _seeded_store()
    await store.add_message(_msg("c1", "m1", MessageRole.USER, "q"))
    await store.add_message(
        _msg("c1", "m2", MessageRole.ASSISTANT, "a", run_id="r1")
    )
    await _clean_run(store, "r1")
    corpus = await build_corpus(
        store, T, base_pin=BASE, target_tenant_id=T, target_data_class="sensitive"
    )
    lines = [json.loads(line) for line in corpus_jsonl_lines(corpus)]
    assert lines[0]["kind"] == "corpus"
    assert lines[0]["digest"] == corpus.digest
    assert lines[0]["base_pin"] == BASE
    assert [row["record_id"] for row in lines[1:]] == ["sft:c1:m2"]


async def test_digest_hashes_content_not_just_ids():
    """Same message ids, different scrubbed content => different digest. The
    digest's claim is "exactly what a trained adapter saw", so a scrubber
    change must never collapse two different corpora onto one digest."""
    async def store_with(content: str) -> InMemoryStore:
        store = await _seeded_store()
        await store.add_message(_msg("c1", "m1", MessageRole.USER, "q"))
        await store.add_message(
            _msg("c1", "m2", MessageRole.ASSISTANT, content, run_id="r1")
        )
        await _clean_run(store, "r1")
        return store

    one = await build_corpus(
        await store_with("answer A"), T, base_pin=BASE,
        target_tenant_id=T, target_data_class="sensitive",
    )
    two = await build_corpus(
        await store_with("answer B"), T, base_pin=BASE,
        target_tenant_id=T, target_data_class="sensitive",
    )
    assert [r.record_id for r in one.records] == [r.record_id for r in two.records]
    assert one.digest != two.digest


async def test_exact_duplicates_are_collapsed_and_reported():
    """Templated flows repeat identical turns by the hundred; training on the
    flood over-weights the template and squeezes output entropy (the silent-
    collapse failure mode). Exact dedup keeps one and reports the rest."""
    store = await _seeded_store()
    for i in range(5):
        cid = f"dup{i}"
        await store.create_conversation(
            Conversation(id=cid, tenant_id=T, user_id="u1")
        )
        await store.add_message(_msg(cid, f"{cid}u", MessageRole.USER, "same ask"))
        await store.add_message(
            _msg(cid, f"{cid}a", MessageRole.ASSISTANT, "same answer", run_id=f"rd{i}")
        )
        await _clean_run(store, f"rd{i}")
    corpus = await build_corpus(
        store, T, base_pin=BASE, target_tenant_id=T, target_data_class="sensitive"
    )
    assert len(corpus.records) == 1
    assert corpus.deduped == 4
    assert corpus.signal_counts == {"clean_run": 1}


async def test_records_carry_message_timestamps_for_recency_replay():
    store = await _seeded_store()
    await store.add_message(_msg("c1", "m1", MessageRole.USER, "q"))
    await store.add_message(
        _msg("c1", "m2", MessageRole.ASSISTANT, "a", run_id="r1")
    )
    await _clean_run(store, "r1")
    corpus = await build_corpus(
        store, T, base_pin=BASE, target_tenant_id=T, target_data_class="sensitive"
    )
    (rec,) = corpus.records
    assert rec.created_at is not None
    line = list(corpus_jsonl_lines(corpus))[1]
    assert json.loads(line)["created_at"] == rec.created_at.isoformat()


def test_manifest_carries_the_distill_section(tmp_path):
    """The extra whitelist must name 'distill' or bootstrap silently sees an
    empty section and registers nothing - found live on the first deploy."""
    from boltrig.config.manifest import load_manifest

    path = tmp_path / "manifest.yaml"
    path.write_text(
        "tenant_id: t\ndistill:\n  enabled: true\n  base_pin: base@rev\n",
        encoding="utf-8",
    )
    manifest = load_manifest(str(path))
    assert manifest.section("distill").get("base_pin") == "base@rev"


async def test_dedup_keeps_the_best_signal_copy():
    """Identical turns with different signals: the surviving record carries
    the strongest signal (a clean_run twin must never displace hitl_approved,
    which earns 3x replay at the trainer)."""
    store = await _seeded_store()
    # clean_run copy FIRST
    await store.add_message(_msg("c1", "m1", MessageRole.USER, "same ask"))
    await store.add_message(
        _msg("c1", "m2", MessageRole.ASSISTANT, "same answer", run_id="r1")
    )
    await _clean_run(store, "r1")
    # hitl-approved identical twin SECOND, in another conversation
    await store.create_conversation(Conversation(id="c2", tenant_id=T, user_id="u1"))
    await store.create_hitl_request(
        HITLRequest(
            id="h1", tenant_id=T, run_id="r2", type=HITLType.APPROVAL,
            urgency=Urgency.BLOCKING, context="", question="ok?",
        )
    )
    await store.answer_hitl(
        HITLResponse(
            id="hr1", request_id="h1", tenant_id=T, decision="approve",
            respondent="u1", responded_at=utcnow(),
        )
    )
    await store.add_message(_msg("c2", "n1", MessageRole.USER, "same ask"))
    await store.add_message(
        _msg("c2", "n2", MessageRole.ASSISTANT, "same answer",
             run_id="r2", hitl_request_id="h1")
    )
    corpus = await build_corpus(
        store, T, base_pin=BASE, target_tenant_id=T, target_data_class="sensitive"
    )
    assert len(corpus.records) == 1
    assert corpus.deduped == 1
    assert corpus.records[0].signal == "hitl_approved"


async def test_small_corpus_always_holds_out_at_least_one_record():
    """The ~10% hash split can select nothing from a small corpus; the
    register gate then has an empty scoring set. One record is guaranteed."""
    store = await _seeded_store()
    await store.add_message(_msg("c1", "m1", MessageRole.USER, "q"))
    await store.add_message(
        _msg("c1", "m2", MessageRole.ASSISTANT, "a", run_id="r1")
    )
    await _clean_run(store, "r1")
    corpus = await build_corpus(
        store, T, base_pin=BASE, target_tenant_id=T, target_data_class="sensitive"
    )
    assert len(corpus.records) == 1
    assert len(corpus.held_out) == 1  # guaranteed even when the hash says 0
