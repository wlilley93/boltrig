# Sleep distillation - build plan

Status: proposal, 2026-08-09. Ruling: `docs/decisions/0023-sleep-distillation-and-the-adapter-seam.md`.

The nightly loop, and the order to build it in. Phase 0 is the only phase that is
not speculative: it is a read-side derivation over tables that already exist,
changes no core code, and is worth landing whether or not a single adapter is
ever trained.

```
   the day                     the night                      the morning
   -------                     ---------                      -----------
 conversations ─┐
 audit verbs ───┼─→ corpus (derived, ─→ train from BASE ─→ eval gate ─→ promote
 HITL decisions ┤    tenant-fenced,      over the whole      (mechanical)  or hold
 superseded ────┤    erasure-filtered)   replay corpus            │        + audit
 eval runs ─────┘            │                                    │           row
                             └── digest ─────────────────────────→┘
```

## Phase 0 - the corpus (land this first, independently useful)

`boltrig/distill/corpus.py`: pure functions over store reads. No trainer, no
network, no new dependency, offline-safe. Produces a deterministic corpus plus
its digest.

Reads: `list_conversations_page` / `list_messages`
(`store/conversation_contract.py`), `audit_query` (`store/base.py:267`),
`list_eval_runs` (`store/eval_cases.py:23`), HITL requests and responses.

Emits two record kinds. Both carry `run_id` so a record is traceable back to the
hash-chained audit that justified it.

```jsonc
// supervised - an accepted trace
{"kind":"sft","tenant_id":"…","run_id":"…","conversation_id":"…",
 "prompt":[…],"completion":"…","verbs":["ticket.create"],
 "signal":"hitl_approved|eval_pass|clean_run","eval_score":0.83}

// preference - free, from a regeneration
{"kind":"pref","tenant_id":"…","run_id":"…",
 "prompt":[…],"rejected":"…superseded content…","chosen":"…successor…",
 "signal":"superseded"}
```

The preference records are the higher-value asset and cost nothing to collect:
`ConversationMessage.superseded_by` already marks a reply the user regenerated,
and the successor is what they kept. That is a labelled preference pair produced
by the ordinary act of pressing regenerate.

Exclusions, applied here rather than at training time so the digest is honest:

- any conversation touched by an open or completed `MemoryErasure` (decision
  0023: rebuild-and-supersede is the only delete an adapter has);
- any run whose `InvocationContext.extra.data_class` was `sensitive`, unless the
  target endpoint is itself `sensitive`-classed;
- secure HITL answers (`HITLRequest.secure`) - the agent never saw the value and
  neither does the corpus;
- anything failing the `kernel/pii.py` pass. Note this is a real gap:
  `privacy.pii_redaction` is parsed but has **no production caller**
  (`docs/proposals/policy-as-data-wiring-gates.md`), so the corpus builder must
  call `redact()` itself rather than assume upstream scrubbing.

`corpus_digest` = SHA-256 over the canonical sorted record ids + base model pin +
the erasure watermark (max `MemoryErasure.created_at` applied). This is the value
that makes promotion state derivable instead of stored.

Deliverable: the module, `distill.corpus.build` as a governed read verb, and a
CLI in `scripts/` that writes JSONL for inspection. Tests bind DIS-1..DIS-3.

## Phase 1 - the serving seam (data only)

No code. A `ModelEndpoint` per adapter, id encoding the owning tenant:

```yaml
models:
  endpoints:
    - id: craft-<tenant>-<yyyymmdd>
      kind: openai            # llama.cpp / mlx-lm on the M4; vllm on a CUDA box
      base_url: http://host.orb.internal:8091/v1
      model: craft-<tenant>-<yyyymmdd>   # the adapter id the server registered
      data_class: sensitive
      is_active: false        # stays false until the gate passes
  prices:
    craft-<tenant>-<yyyymmdd>: 0.0       # or the true amortised rate
```

Two live traps, both already established in this repo:

- **vLLM has no Metal backend.** On the M4 the server is llama.cpp
  (`--lora` / per-request `lora` list) or mlx-lm. Both are OpenAI-shaped, so
  `kind: openai` needs no code change, and the keyless local-endpoint path is
  already bound (`tests/invariants.yaml:787`).
- **The route.** A native model server is not a permitted runtime override.
  Candidate evaluation must eventually enter through a governed Bifrost model
  endpoint and the same Codex admission used by production execution.

## Phase 2 - the gate

`boltrig/distill/gate.py`. Two mechanical gates, no judge.

- **craft verdict**: compare the tenant's active cases and promote iff mean
  score >= incumbent **and** `{cases passing on incumbent} ⊆ {cases passing on
  candidate}`. The verdict function remains tested, but the adapter lane is
  fail-closed until inactive candidates have a governed Codex/Bifrost
  admission contract. It must not inject a provider URL into runtime context.
- **register**: mean token log-likelihood of a held-out 10% of that tenant's
  accepted assistant turns, candidate vs incumbent. Held-out at corpus-build
  time and pinned by digest, so it cannot be trained on.

Output is an `AuditEvent` either way, carrying `corpus_digest`, `base_pin`,
`incumbent_score`, `candidate_score`, `decision`. On pass, the same act flips
`is_active` and writes the price row - decision 0023 makes pricing part of
promotion, not a follow-up.

## Phase 3 - the night

A `WorkflowSchedule` (`boltrig/workflows/scheduler.py`) on a nightly cron, not a
new scheduler. Steps: `distill.corpus.build` → `distill.train` → `distill.gate` →
`distill.promote`. Each is a governed verb through the one chokepoint, under the
schedule's caller-bound re-authorized grants, with the scheduler's existing
occurrence/lease/catch-up semantics.

`distill.train` binds to a sidecar adapter. The kernel and `fleet-worker` never
link a trainer - same posture as whisper. The trainer is `mlx_lm.lora` on the M4
or a rented GPU; either way it is a verb, and an unavailable trainer returns a
typed unavailable result rather than failing the night.

Cadence: craft nightly; register weekly at a lower learning rate, and only after
its gate has a track record. Every train is **from the pinned base over the whole
replay corpus** with recency weighting - never from last night's adapter.

## Invariants to declare

| ID | Claim |
|---|---|
| DIS-1 | A corpus record's `tenant_id` equals its endpoint's tenant; a cross-tenant record is refused, not filtered. |
| DIS-2 | `sensitive`-classed content only ever enters a corpus whose target endpoint is `sensitive`-classed. |
| DIS-3 | A conversation covered by a `MemoryErasure` is absent from every corpus built after it, and the erasure watermark is in the digest. |
| DIS-4 | Training input is the pinned base, never a prior adapter; a candidate naming an adapter base is refused. |
| DIS-5 | A candidate endpoint is created `is_active=False` and only a passing gate flips it. |
| DIS-6 | Craft evaluation refuses until inactive candidates use governed Codex/Bifrost admission; no direct-provider bypass. |
| DIS-7 | Every consolidation writes an audit row - promote and hold alike - carrying corpus digest and both scores. |
| DIS-8 | A promoted adapter id is present in the price table at promotion time (else `cost.py` charges it at the tier default). |

## Implemented vs scaffolded (updated 2026-08-09, at build time)

**Implemented and tested (offline suite + invariant gate green):**

- `boltrig/distill/` - corpus builder (`corpus.py` + `corpus_io.py`), pure
  gate verdicts (`gate.py`), gate legs (`adapter_gates.py`), the adapter with
  five verbs incl. `distill.night` (`adapter.py`, `adapter_night.py`,
  `adapter_specs.py`), manifest-section composition (`bootstrap.py`).
- DIS-1..8 declared and bound (28 distill tests across
  `tests/unit/test_distill_corpus.py` / `test_distill_adapter.py`).
- `services/distill_sidecar/` - stdlib HTTP trainer/scorer, **exercised for
  real on the M4 (2026-08-09)**: a 20-record corpus derived by the builder was
  shipped, trained with `mlx_lm.lora` against
  `mlx-community/Qwen2.5-0.5B-Instruct-4bit` (mlx venv at
  `~/opbox-dev/mlx-venv`), and scored: held-out mean loglik candidate
  -0.0008 vs bare base -3.198 -> register verdict promotes. Toy corpus, real
  pipeline.
- Promotion pricing (`CostAccountant.set_price`) and the audit-receipt-gated
  `distill.promote`.

**Still a seam:**

- A production-scale corpus (needs real tenant history in Postgres).
- The 7B production base + `mlx_lm.server` serving of a promoted adapter, and
  the Codex-composition sensitive-role consumption of that endpoint.
- A governed inactive-candidate admission contract for the craft gate. The
  verdict itself remains tested; direct provider routing was retired.
- The schedule itself (a runbook act, below), and DPO over pref pairs (the
  sidecar trains pref records' CHOSEN side only, stated in `app.py`).

## Runbook: turning the night on

1. **Sidecar**: `services/distill_sidecar/README.md` - mlx venv, launchd
   plist, `curl :8930/health` must say `"mlx": true`.
2. **Manifest**: set the `distill:` section (`enabled: true`, `base_pin`, and
   `sidecar_url`) - see `manifest.example.yaml`; add `distill.*` to the
   operating role's scope if the tenant ceiling is not `*`. Only the register
   gate is operational; the craft gate refuses typed.
3. **Candidate endpoint**: `control.model_endpoint.upsert` then immediately
   `control.model_endpoint.retire` (upsert re-defaults to active) for
   `craft-candidate`, `kind: openai`, `data_class: sensitive`, `base_url`
   pointing at the mlx server.
4. **One manual night**: invoke `distill.night` by hand and read the gate
   receipt in the audit.
5. **Schedule**: `control.workflow.upsert` the definition in
   `libraries/workflows/sleep-distillation-craft.yaml`, then
   `control.workflow.schedule {workflow_id, cron: "0 3 * * *", timezone}` -
   **as a real user holding `control.workflow.trigger`**; a service-principal
   schedule persists as `needs_action` and never runs. Register lane: same
   shape, `adapter_kind: register`, weekly cron.
6. **Promotion** stays manual (`distill.promote`, high-consequence) until the
   loop has earned `auto_promote: true` - that flip is a deliberate act.

## The resolved question

Register-from-day-one was the open question; the owner decided it ships in the
first cut (decision 0023, amendments). The held-out-likelihood gate is
therefore load-bearing immediately - watch its receipts with particular
suspicion for the first few weeks, and fall back to harness text if tone
drifts in a way the gate does not catch.
