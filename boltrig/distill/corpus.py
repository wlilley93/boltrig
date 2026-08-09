"""Sleep-distillation corpus builder (decision 0023, DIS-1..3).

A corpus is a DERIVED, rebuildable view over the governed record - never a new
authority. Every record traces back through ``run_id`` to the hash-chained
audit that justified its inclusion, and the corpus digest pins exactly what a
trained adapter saw, so promotion state can be derived rather than stored
(the ``WorkflowPromotion`` ruling, ``models/libraries.py``).

Supervision comes free from governance, never from labelling:

* ``sft``  - an assistant turn a human approved (HITL), an eval scored as
  passing, or a run whose audit shows a clean verb trail;
* ``pref`` - a (rejected, chosen) pair derived from a regenerated reply
  (``ConversationMessage.superseded_by`` marks the rejected turn; its
  superseder is the one the user kept).

Exclusions are applied HERE, at build time, so the digest is honest:

* conversations touched by any ``MemoryErasure`` (an adapter is a projection
  with no delete - erasure is satisfied by exclusion at the next rebuild, and
  the erasure watermark is folded into the digest so "does this adapter
  predate that erasure" is answerable);
* secure HITL answers (the agent never saw the value; neither does a corpus);
* records carrying a secret (``kernel.pii.contains_secret`` - refusal, not
  redaction, per the CP3 variation ratio in ``kernel/pii.py``); other PII is
  span-redacted with ``kernel.pii.redact``.

DIS-2 is enforced conservatively: run-level sensitivity
(``InvocationContext.extra["data_class"]``) is not durably recorded per run,
so a corpus may only target a ``sensitive``-classed endpoint. Training a
standard-classed endpoint would require proving the absence of sensitive runs
from records that do not exist - refused rather than guessed.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Any

# The approving decision vocabulary is the HITL manager's; import it rather
# than drifting a copy (precedent: api/bootstrap.py).
from boltrig.kernel.hitl import _APPROVING
from boltrig.distill.corpus_identity import corpus_digest, dedupe
from boltrig.kernel.pii import contains_secret, redact
from boltrig.models import ConversationMessage, MessageRole

_HELD_OUT_PERCENT = 10  # register gate held-out share, deterministic by id
_ERASURE_SCAN_LIMIT = 10_000
_AUDIT_SCAN_LIMIT = 500
_BAD_RUN_STATUSES = frozenset({"denied", "error"})


class CorpusTenantMismatch(ValueError):
    """DIS-1: a record outside the target endpoint's tenant is refused."""


class CorpusDataClassRefused(ValueError):
    """DIS-2: a corpus may only target a sensitive-classed endpoint."""


@dataclass(frozen=True)
class SftRecord:
    record_id: str
    tenant_id: str
    conversation_id: str
    run_id: str | None
    prompt: tuple[tuple[str, str], ...]  # (role, content) pairs, in order
    completion: str
    signal: str  # hitl_approved | eval_pass | clean_run
    eval_score: float | None = None
    created_at: datetime | None = None  # the message's timestamp (recency replay)
    kind: str = "sft"


@dataclass(frozen=True)
class PrefRecord:
    record_id: str
    tenant_id: str
    conversation_id: str
    run_id: str | None
    prompt: tuple[tuple[str, str], ...]
    rejected: str
    chosen: str
    signal: str = "superseded"
    created_at: datetime | None = None
    kind: str = "pref"


@dataclass(frozen=True)
class Corpus:
    tenant_id: str
    base_pin: str  # exact base-model repo+revision the adapter trains FROM
    records: tuple[SftRecord | PrefRecord, ...]
    held_out: tuple[str, ...]  # sft record ids reserved for the register gate
    erasure_watermark: datetime | None
    digest: str
    deduped: int = 0  # exact (prompt, completion) duplicates collapsed at build

    @property
    def training_records(self) -> tuple[SftRecord | PrefRecord, ...]:
        held = set(self.held_out)
        return tuple(r for r in self.records if r.record_id not in held)

    @property
    def signal_counts(self) -> dict[str, int]:
        """The corpus composition at a glance ("look at your data"): how much
        of the training signal is human-anchored vs merely-clean."""
        counts: dict[str, int] = {}
        for r in self.records:
            counts[r.signal] = counts.get(r.signal, 0) + 1
        return counts


def _held_out(record_id: str) -> bool:
    """Deterministic ~10% split, pinned by record id (no randomness: the same
    corpus always splits the same way, so the digest also pins the split)."""
    h = hashlib.sha256(record_id.encode()).hexdigest()
    return int(h[:8], 16) % 100 < _HELD_OUT_PERCENT


def _scrub(text: str) -> str | None:
    """Redact PII spans first, then refuse the record if a true secret remains.

    Order matters: ``contains_secret`` deliberately includes ``email`` (the CP3
    variation keeps the refusal predicate wide), but an email is PII that
    ``redact`` removes - so redact first, and let the refusal fire only on
    secret material (keys, tokens, PEM blocks) that redaction never touches.
    """
    redacted = redact(text).redacted
    if contains_secret(redacted):
        return None
    return redacted


def _role(message: ConversationMessage) -> str:
    role = message.role
    return role.value if isinstance(role, MessageRole) else str(role)


async def _run_is_clean(store: Any, tenant_id: str, run_id: str) -> bool:
    events = await store.audit_query(tenant_id, run_id=run_id, limit=_AUDIT_SCAN_LIMIT)
    if not events:
        return False  # no evidence is not a signal
    return all(e.status not in _BAD_RUN_STATUSES for e in events)


async def _hitl_signal(
    store: Any, tenant_id: str, request_id: str
) -> tuple[bool, bool]:
    """Return (approved, secure). A secure request excludes the record."""
    request = await store.get_hitl_request(tenant_id, request_id)
    if request is not None and request.secure:
        return False, True
    response = await store.get_hitl_response(tenant_id, request_id)
    approved = bool(
        response is not None and str(response.decision).lower() in _APPROVING
    )
    return approved, False


def _erased_conversations(
    conversations: list[Any],
    messages_by_conv: dict[str, list[ConversationMessage]],
    erasure_targets: set[str],
) -> set[str]:
    """A conversation is covered when an erasure target names the conversation,
    one of its messages, or a run one of its messages carries."""
    erased: set[str] = set()
    for conv in conversations:
        if conv.id in erasure_targets:
            erased.add(conv.id)
            continue
        for m in messages_by_conv.get(conv.id, []):
            if m.id in erasure_targets or (m.run_id and m.run_id in erasure_targets):
                erased.add(conv.id)
                break
    return erased


async def build_corpus(
    store: Any,
    tenant_id: str,
    *,
    base_pin: str,
    target_tenant_id: str,
    target_data_class: str,
) -> Corpus:
    """Derive the tenant's training corpus from the governed record.

    ``target_tenant_id`` / ``target_data_class`` describe the endpoint the
    resulting adapter will be served on; both fences are refusals (DIS-1/2),
    not filters - a mismatch is a configuration error, never silently thinned.
    """
    if target_tenant_id != tenant_id:
        raise CorpusTenantMismatch(
            f"corpus tenant '{tenant_id}' does not own target endpoint tenant "
            f"'{target_tenant_id}'"
        )
    if target_data_class != "sensitive":
        raise CorpusDataClassRefused(
            "run-level sensitivity is not durably recorded, so a corpus may "
            "only target a sensitive-classed (local) endpoint"
        )

    erasures = await store.list_memory_erasures(tenant_id, limit=_ERASURE_SCAN_LIMIT)
    erasure_targets = {er.target for er in erasures}
    watermark = max((er.created_at for er in erasures), default=None)

    eval_pass_runs: dict[str, float] = {}
    for run in await store.list_eval_runs(tenant_id):
        if run.passed and run.run_id:
            eval_pass_runs[run.run_id] = run.score

    conversations: list[Any] = []
    for user in await store.list_users(tenant_id):
        conversations.extend(await store.list_conversations(tenant_id, user.id))

    messages_by_conv: dict[str, list[ConversationMessage]] = {}
    for conv in conversations:
        if conv.tenant_id != tenant_id:
            raise CorpusTenantMismatch(
                f"conversation '{conv.id}' belongs to tenant '{conv.tenant_id}'"
            )
        messages_by_conv[conv.id] = await store.list_messages(tenant_id, conv.id)

    erased = _erased_conversations(conversations, messages_by_conv, erasure_targets)

    records: list[SftRecord | PrefRecord] = []
    for conv in conversations:
        if conv.id not in erased:
            records.extend(
                await _conversation_records(
                    store, tenant_id, conv.id, messages_by_conv[conv.id],
                    eval_pass_runs,
                )
            )

    records, deduped = dedupe(records)
    held_out = tuple(
        sorted(
            r.record_id
            for r in records
            if isinstance(r, SftRecord) and _held_out(r.record_id)
        )
    )
    digest = corpus_digest(records, base_pin, watermark)
    return Corpus(
        tenant_id=tenant_id,
        base_pin=base_pin,
        records=tuple(records),
        held_out=held_out,
        erasure_watermark=watermark,
        digest=digest,
        deduped=deduped,
    )


async def _conversation_records(
    store: Any,
    tenant_id: str,
    conversation_id: str,
    messages: list[ConversationMessage],
    eval_pass_runs: dict[str, float],
) -> list[SftRecord | PrefRecord]:
    """Walk one conversation in order, deriving sft and pref records against
    the live (non-superseded) continuity."""
    records: list[SftRecord | PrefRecord] = []
    by_id = {m.id: m for m in messages}
    context: list[tuple[str, str]] = []
    for m in messages:
        if m.tenant_id != tenant_id:
            raise CorpusTenantMismatch(
                f"message '{m.id}' belongs to tenant '{m.tenant_id}'"
            )
        text = m.content or ""
        if m.role == MessageRole.ASSISTANT and text:
            if m.superseded_by is not None:
                successor = by_id.get(m.superseded_by)
                record = _pref_record(tenant_id, conversation_id, m, successor, context)
                if record is not None:
                    records.append(record)
                continue  # a superseded turn never enters continuity
            sft = await _sft_record(
                store, tenant_id, conversation_id, m, context, eval_pass_runs
            )
            if sft is not None:
                records.append(sft)
        if m.superseded_by is None and text:
            context.append((_role(m), text))
    return records


async def _sft_record(
    store: Any,
    tenant_id: str,
    conversation_id: str,
    message: ConversationMessage,
    context: list[tuple[str, str]],
    eval_pass_runs: dict[str, float],
) -> SftRecord | None:
    signal: str | None = None
    eval_score: float | None = None
    if message.hitl_request_id:
        approved, secure = await _hitl_signal(store, tenant_id, message.hitl_request_id)
        if secure:
            return None
        if approved:
            signal = "hitl_approved"
    if signal is None and message.run_id and message.run_id in eval_pass_runs:
        signal = "eval_pass"
        eval_score = eval_pass_runs[message.run_id]
    if signal is None and message.run_id:
        if await _run_is_clean(store, tenant_id, message.run_id):
            signal = "clean_run"
    if signal is None:
        return None  # an unlabelled turn does not train

    completion = _scrub(message.content or "")
    prompt = _scrub_prompt(context)
    if completion is None or prompt is None:
        return None
    return SftRecord(
        record_id=f"sft:{conversation_id}:{message.id}",
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        run_id=message.run_id,
        prompt=prompt,
        completion=completion,
        signal=signal,
        eval_score=eval_score,
        created_at=message.created_at,
    )


def _pref_record(
    tenant_id: str,
    conversation_id: str,
    rejected_message: ConversationMessage,
    successor: ConversationMessage | None,
    context: list[tuple[str, str]],
) -> PrefRecord | None:
    if successor is None or not (rejected_message.content and successor.content):
        return None
    rejected = _scrub(rejected_message.content)
    chosen = _scrub(successor.content)
    prompt = _scrub_prompt(context)
    if rejected is None or chosen is None or prompt is None:
        return None
    return PrefRecord(
        record_id=f"pref:{conversation_id}:{rejected_message.id}",
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        run_id=successor.run_id or rejected_message.run_id,
        prompt=prompt,
        rejected=rejected,
        chosen=chosen,
        created_at=(successor.created_at or rejected_message.created_at),
    )


def _scrub_prompt(
    context: list[tuple[str, str]],
) -> tuple[tuple[str, str], ...] | None:
    scrubbed: list[tuple[str, str]] = []
    for role, text in context:
        clean = _scrub(text)
        if clean is None:
            return None  # one secret poisons the whole record - refuse it
        scrubbed.append((role, clean))
    return tuple(scrubbed)
