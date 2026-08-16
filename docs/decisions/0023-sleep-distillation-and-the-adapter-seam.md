# 0023 - Sleep distillation: the adapter seam and the nightly consolidation

- Status: accepted (2026-08-09); DIS-1..DIS-8 bound and green
- Date: 2026-08-09
- Bound by: DIS-1..DIS-8 (`tests/invariants.yaml`)
- Companion: `docs/proposals/sleep-distillation.md` (the build plan + runbook)

## 2026-08-14 runtime-retirement amendment

The craft gate is fail-closed. Its former model-profile context override was a
second provider-routing authority and is no longer consumed by the Codex-only
runtime. Leaving it in place could score the composed default twice while
claiming to compare incumbent and candidate. The register/log-likelihood gate
remains available. Craft evaluation may return only after inactive candidates
have a typed, governed Codex/Bifrost admission contract; arbitrary provider
URLs are not an acceptable replacement.

## Amendments at acceptance (2026-08-09)

- **Register trains from day one** (owner's decision, reversing the
  gate-first recommendation below): weekly cadence, gated by held-out
  likelihood from the first cut. The harness-text fallback remains available
  if the gate proves too weak in practice.
- **The night is ONE verb.** The workflow loop contract binds whole JSON
  values and never interpolates (`workflows/loop_contract.py`), so a corpus
  digest cannot thread between workflow steps declaratively. `distill.night`
  runs build -> ship -> train -> gate inside the adapter; promotion stays a
  separate high-consequence verb reading the gate receipt (DIS-5).
- **Composed like memory, not module_ref'd.** The adapter needs the store,
  audit writer and cost accountant, so it registers via
  `boltrig/distill/bootstrap.py` from the manifest's `distill:` section - the
  `memory`/`knowledge` composition pattern - rather than the `adapters:` list.
- **Superseded by the 2026-08-14 amendment:** candidate evaluation originally
  routed via the model-profile context seam
  (`fleet/model_profiles.py`), which deliberately bypasses the store
  `is_active` check - correct, because the candidate is inactive BY DESIGN
  until promoted; production serving still resolves through the store, which
  enforces retirement (`fleet/model_router.py`).

## Second pass (2026-08-09): collapse guards and corrected claims

External grounding: the Karpathy/Dwarkesh conversation (2025-10) - model
outputs are low-entropy, self-training silently collapses, dreaming is
entropy injection, and the end-state he sketches is exactly a personal LoRA
consolidated from use - and arXiv:2606.03979 ("Language Models Need Sleep",
2026-06), whose consolidate-from-fragile-memory-with-replay-then-reset shape
independently matches this design's rebuild-from-base ruling.

Corrections:
- **The corpus digest now hashes record CONTENT, not record ids.** Ids alone
  made the "pins exactly what the adapter saw" claim false the moment the PII
  scrubber evolved (same ids, different text, same digest).
- **Superseded by the 2026-08-14 amendment:** the intermediate implementation
  required `distill.serve_url`; that provider-native routing seam is now
  removed and the craft gate always refuses typed.
- **The sidecar binds loopback by default** (`BOLTRIG_DISTILL_BIND` to widen):
  an unauthenticated trainer must not face the LAN.
- **An empty day is a quiet night**: `distill.night` returns `empty_corpus`
  instead of failing three steps later.

Collapse guards (the corpus is mostly the model's own text; uniform replay of
your own output is the collapse recipe):
- **Exact dedup at build** - templated flows repeat near-identical turns by
  the hundred; the flood over-weights the template. Reported as `deduped`.
- **Weighted replay at the trainer** - human-anchored signals dominate:
  hitl_approved x3, pref-chosen x2, eval_pass x2, clean_run x1; records from
  the last 7 days replay x2 (consolidation replays the recent past harder).
- **Composition receipt** - `distill.corpus.build` returns the signal
  histogram + dedup count, so a night trained mostly on merely-clean
  synthetic turns is visible in its receipt, not discovered in behaviour.

## Next lanes (status at 2026-08-09, third pass)

- **A diversity metric in the gate** - IMPLEMENTED (DIS-9): the register gate
  measures distinct-2 over seeded sampled generations for candidate and
  incumbent (`/diversity`, `mlx_diversity.py`); a candidate under 0.8x the
  incumbent's diversity is held with `entropy_collapse` regardless of
  likelihood, and both measurements ride on the gate receipt. First live
  measurement caught real collapse: the toy template-corpus adapter scored
  0.625 vs base 0.9375 (ratio 0.67) and would be held - correctly.
- **System-prompt-learning lane** - proposal written
  (`docs/proposals/notes-before-weights.md`). Not implemented here: the notes'
  natural container is the addon harness, which is compiled into the ATTESTED
  birth profile - a nightly self-edit changes what the attestation claims and
  needs its own ruling.
- **DPO over pref pairs** - checked and blocked on the toolchain: mlx-lm
  0.31.3 has no preference loss (no `--train-type`; `tuner.losses` carries
  only kl/js distillation losses). Wiring it means adopting the third-party
  `mlx-lm-lora` trainer - a new dependency, surfaced here rather than added
  silently. The pref data is already collected and shipped in every corpus.

## Context

Historical context at decision time (superseded by the Codex-only runtime):
`boltrig/fleet/runtime.py:46`
maps the `vllm` and `ollama` endpoint kinds onto the OpenAI runtime, and
`runtime.py:249` / `runtime.py:314` pass `self.endpoint.model` **verbatim** as the
request's `model` field. Every OpenAI-shaped server that serves a LoRA does so by
registering it as a model id. So *serving* an adapter is already a pure-data
change - a `ModelEndpoint` row plus, if it should be pinned to one department,
`AgentCapability.model_endpoint` (`boltrig/models/libraries.py:86`). No core edit.

What is missing is not serving. It is three questions serving does not answer:

1. where a training corpus comes from;
2. what is allowed to promote a candidate adapter over the incumbent;
3. what an adapter is permitted to contain.

Boltrig is unusually placed to answer (1) and (2), because it already collects
supervision as a **byproduct of governance** rather than as a labelling exercise:

| Signal | Where | What it is |
|---|---|---|
| `ConversationMessage` | `models/conversation.py:42` | the text - role, content, tool `events`, `run_id` |
| `AuditEvent` | `models/audit.py:57` | what the agent actually did - verb, adapter, status, tokens, per `run_id` |
| `HITLResponse.decision` | `models/hitl.py:86` | a human's explicit endorsement or refusal |
| `superseded_by` | `models/conversation.py` | a regenerated reply - a (rejected, chosen) pair, free |
| `EvalRun.passed/score` | `models/platform.py:49` | machine-computed from the audit (`fleet/eval.py:116`) |

That last row is the load-bearing one. `EvalRunner._checks` scores a run by
querying the audit for the verbs it called and testing `must_call` /
`must_not_call` / `forbidden_grants` / `expect_output`; `_verdict` returns the
fraction passed. It is a deterministic, replayable behavioural reward signal with
**no LLM judge in it**. Nightly self-training without a gate like that is
unfalsifiable drift. With it, "the model got worse overnight" is a blocking,
attributable event.

Against that, the ruling below is mostly a set of refusals, because the naive
shape of this feature - take today's conversations, train, serve tomorrow, repeat -
has three failure modes the doctrine already forbids in other clothes: model
collapse from training on one's own output, recency tyranny where one bad day
rewrites the system, and an unerasable copy of tenant data.

## Decision

- **An adapter is a memory projection with no delete operation.** This is the
  ruling everything else follows from. Decision 0011 §6 says erasure fans out to
  every projection and reports any backend that failed; `MemoryErasure`
  (`models/memory.py:54`) even carries `transcript_handled` for exactly this.
  Cognee can honour a delete. **Weights cannot.** Therefore an adapter is
  ALWAYS trained from the pinned base model over a rebuildable corpus, and NEVER
  incrementally from last night's adapter. Erasure is satisfied by exclusion at
  the next rebuild; every adapter records its corpus digest and the erasure
  watermark it was built after, so "does this adapter predate that erasure" is a
  question with an answer. The same rule independently kills autophagic collapse
  and recency tyranny - one architecture, three problems. Adapter-on-adapter
  training is refused, not deferred.

- **Facts never enter the weights. Only behaviour and register do.** Knowledge
  (immutable revisions + segment citations) carries *what*; `MemoryFact` carries
  *what was learned*; the adapter carries *how*. A fact baked into weights cannot
  be cited, cannot be corrected without a retrain, and cannot be erased at all.
  The day's events shift the adapter's *distribution*; they are not stored in it.

- **Two adapters, two gates, two cadences.** They are split because they cannot be
  scored the same way, and a shared artifact means a regression in one blocks an
  improvement in the other.

  - **craft** - verb selection, argument shape, when to escalate to HITL, when to
    stop, output structure. Gated by the existing `EvalRunner` over the tenant's
    case set. Promotion requires score >= incumbent across the set **and** no
    individually-passing case regressing to fail. Nightly.
  - **register** - tone, address, house idiom: the thing a user means by
    "personality". It has no `must_call` assertion to score against, so it is
    gated on **held-out likelihood**: the candidate must assign higher likelihood
    to a held-out sample of that tenant's *accepted* assistant turns than the
    incumbent does. Objective, cheap, needs no judge, and held-out so a night of
    noise cannot pass by memorising itself. Weekly, at a lower learning rate.

  Register is the lower-confidence half. Until its gate has a track record, the
  honest default is that register stays carried by the addon `harness` text
  (`docs/addons.md`), which is bounded, attested and hashed into the birth
  profile, and only the craft adapter is trained. Shipping the register gate
  before shipping register training is deliberate.

- **A promotion is an action and appears in the hash-chained audit.** A night
  writes an `AuditEvent` whether it promotes or holds, carrying the corpus digest,
  the base pin, the incumbent and candidate scores, and the reason. The candidate
  endpoint is registered with `is_active=False` and only flips on a passing gate,
  so the switch is a stored, reversible, attributable act rather than a file
  appearing on a box.

- **The night is a scheduled workflow, not a new scheduler.**
  `boltrig/workflows/scheduler.py` is already durable, cron-driven, re-authorized
  per occurrence and caller-bound, with catch-up and lease handling. The
  consolidation runs through it, under the initiator's grants, through the one
  chokepoint. Adding a cron beside it would be a side door.

- **Training is a sidecar; the kernel and the fleet worker never link a trainer.**
  Same posture as whisper, which runs native on macOS because Metal does not exist
  inside the OrbStack Linux VM. The kernel's only surface is a `distill.*` verb
  namespace resolved to an adapter, exactly like any other integration. On the M4
  specifically the serving side is llama.cpp or mlx-lm, not vLLM (which has no
  Metal backend); both are OpenAI-shaped, so `kind: openai` with a `base_url`
  works today with no code change, and the keyless-local-endpoint behaviour is
  already bound by an invariant (`tests/invariants.yaml:787`).

- **An adapter is tenant-bound, and the kernel cannot see that it is.** Grants,
  RLS and the audit chain all sit strictly upstream of the weights; to the
  dispatcher a promoted adapter is an opaque string in `endpoint.model`. So the
  binding must be structural rather than enforced at dispatch: the endpoint id
  encodes the owning tenant, and a gate refuses to promote an adapter whose corpus
  tenant differs from its endpoint's tenant. Further, **content classified
  `sensitive` may only ever train an adapter served on a `sensitive` endpoint** -
  otherwise the model router's local-only guarantee is defeated by laundering the
  data through weights that then get served on a standard endpoint. This is the
  one place where the feature could weaken an existing guarantee, which is why the
  ruling is explicit rather than left to the implementer.

- **A promoted adapter is priced in the same act as its promotion.**
  `boltrig/kernel/cost.py:190` falls back to the `cost_tier` default when a model
  is absent from the price table - 5 micros/token, i.e. $5/M, for an adapter whose
  marginal cost is electricity. Budget reservations would over-reserve by orders
  of magnitude and any `hard_stop` budget would trip early on the cheapest model
  in the fleet. Promotion writes the price-table entry or it is not a promotion.

## Refused

- **Adapter-on-adapter nightly increments.** Collapse, and unerasable.
- **Facts in the weights.** Uncitable, uncorrectable, unerasable.
- **A LoRA on the Codex runtime.** Hosted and closed; not an extension target
  under 0012. The adapter seam is the local endpoint, and nowhere else.
- **A promotion/ranking table.** Promotion state is DERIVED from eval runs pinned
  by corpus digest and base pin. This is the identical ruling the deleted
  `WorkflowPromotion` record already carries in `models/libraries.py:145` - "no
  table, no writer, no trigger (that order)".
- **An LLM judge in the promotion gate.** Both gates are mechanical on purpose. A
  judge would make the ratchet a matter of opinion, and the opinion would come
  from the model being judged.

## Deferred

- Cross-tenant or shared-base adapters, and any adapter marketplace.
- T2L-style hypernetwork bootstrap (generate an adapter from a task description).
  It solves the opposite problem - a department with no history. Boltrig's whole
  advantage here is warm, governed, adjudicated traces; a description-generated
  adapter is a cold-start guess. Worth revisiting only for a genuinely new
  department.
- Per-user register adapters. Per-tenant first; per-user multiplies the erasure
  surface by the user count.

## Consequences

- The eval suite stops being a CI nicety and becomes the ratchet that makes
  self-improvement safe. Thin case coverage in a department means that department
  cannot be distilled - which is the correct incentive.
- `EvalCase` authoring becomes the highest-leverage work in the repo.
- Erasure gains a third projection to reason about, and it is the only one that
  cannot be deleted from - handled by rebuild-and-supersede rather than by delete.
- The cheap tier can move on-box and become free once a craft adapter clears the
  gate against it, which is the first genuinely load-bearing use.
