# Nankle Pi runtime spec (Round Six)

Session continuity, model gateway, and execution isolation for the foundational
agent piece.

- **Status:** Draft, grounded against wlilley93/Nankle (main) as provided.
- **Scope:** the standalone Nankle repo, the **pi runtime lane only**. The
  `hermes` and `claude-api` lanes are single-shot, non-agentic calls and are
  unaffected.
- **Supersedes:** the Hermes-Agent-based assumptions in the prior Opbox full
  architecture spec do not apply to Nankle and are not carried forward.

## 1. Summary

Three real gaps between what the kernel/fleet already do and what a
session-continuous, cost-controlled, agentic runtime needs. The kernel is mature
and needs no rework (ten-step dispatch chokepoint, capability-scoped grants,
hash-chained audit, un-bypassable HITL gate). The gaps are entirely in the fleet
layer, in how the **pi** runtime lane (the only agentic, multi-step, tool-using
lane) handles conversations across turns and reaches model providers.

### 1.1 Correcting the prior framing

- The fleet already has a runtime named `hermes` (`nankle/fleet/runtime.py`,
  `HermesRuntime`); it is NOT Nous Research's product, just a single-shot
  OpenAI-compatible chat-completions call, no tool loop, no MCP. Naming is an
  open question, not a settled fact (Section 7).
- **Pi** is the only agentic runtime (of script, hermes, claude-api, pi):
  multi-step, tool-calling, MCP-mediated, run in a severed process. It is the
  only one with anything to isolate, so the only one this spec concerns.
- `services/pi_sidecar` is explicit it is not yet running a real third-party Pi
  product: its README says it is "the integration point for the Pi open-source
  agent toolkit," the current loop a hand-built stand-in, designed to be replaced
  without changing inputs or event stream.

## 2. What is already real and working (no change needed)

- **2.1 The kernel** - `nankle/kernel/dispatch.py` runs every verb through the
  same fixed ten-step order, one audit row in a `finally` regardless of outcome:
  resolve verb+binding, validate input schema, check grants vs tenant ceiling,
  consequence/HITL gate (un-bypassable for high/blocking), rate limit,
  idempotency replay, credential resolution (kernel-only, last), execute,
  validate output schema, audit. Order is load-bearing.
- **2.2 The doctrine source** - the chokepoint/capability/audit discipline is
  owned by a separate `agent-kernel-doctrine` repo (the invariants' single
  source); Nankle conforms, does not author. `scripts/check_invariants.py` +
  `tests/invariants.yaml` are the real enforcement mechanism.
- **2.3 Pi's existing isolation** - `services/pi_sidecar` is a severed process
  (SEC-28: kernel/models import nothing from it; only coupling is the wire
  protocol) that was simply never given any filesystem/process/credential/network
  tool. Its only capability is calling a kernel verb over an MCP connection
  scoped to one run's grants. Egress restricted at the container level to the
  kernel MCP endpoint + the model endpoint. Never receives a tool credential,
  only a model key + run-scoped MCP token, per request, neither logged.

## 3. The three real gaps

- **3.1 No cross-turn conversation continuity (FOUNDATIONAL, fix first).**
  `nankle/fleet/chat.py` `handle_turn` mints a brand new `run_id` and `WorkItem`
  on every message, whether or not a `conversation_id` is supplied. Each turn
  calls `spawner.spawn()` fresh. `ConversationMessage`/`list_messages` exist but
  only persist messages + serve the UI history view, never reconstruct context
  for the next turn. History is not composed into the prompt that reaches the
  runtime. (Idle hibernation + realtime streaming are real but secondary; this is
  upstream of them.)
- **3.2 No model-cost routing or caching.** `nankle/fleet/model_router.py` is a
  COMPLIANCE gate (sensitive data may only reach a local sensitive-classed
  endpoint, SEC-12/US-PRIV-01), not a cost/cache layer. No caching, no provider
  failover, no cost-based selection. `PiRuntime.build_request` resolves
  `self.endpoint` once at construction and reuses it for the full run, so model
  selection is pinned per run. The binding unit a cost-aware gateway needs is the
  **conversation**, not the run; today's `run_id` is minted fresh each turn and
  is the wrong key.
- **3.3 Execution isolation is protocol-level, not a sandboxed boundary.** 2.3
  works and satisfies the invariant, but relies on the sidecar never having been
  given dangerous tools, which stops being automatically true once a larger,
  less-audited third-party "real Pi loop" is substituted in.

## 4. Proposed additions

- **4.1 Session continuity (addresses 3.1).** Two paths: (a) **native Python,
  Store-backed** - compose prior `ConversationMessage`s into the prompt before
  `spawn()`, hold optional in-memory state behind the existing Store seam
  (`nankle/store/base.py`), consistent with P1/P7; no new runtime. (b) Rivet
  Actors (rivetkit, JS/TS-native) - introduces a new language runtime for a
  problem the Store seam can likely solve.
  **Recommendation: build native first**, scoped narrowly to composing
  conversation history into the prompt before spawn. Smallest change that closes
  3.1, stays in conventions. Revisit Rivet only on a concrete need it cannot meet
  (genuine cross-process realtime fan-out beyond chat.py's relay/SSE).
- **4.2 Model gateway (addresses 3.2), sequenced AFTER 4.1.** Bifrost (or
  equivalent OSS AI gateway) attaches at one point: where
  `PiRuntime.build_request` constructs the model object handed to the sidecar.
  - Point the resolved `ModelEndpoint.base_url` at the gateway, so every Pi-lane
    call routes through it without changing the sidecar protocol.
  - Add a binding store keyed on **conversation_id** (not run_id), mapping to a
    bound model + last-touched timestamp, consulted before `select_model_endpoint`
    resolves an endpoint for a turn.
  - Synchronize the binding TTL to the gateway's cache TTL.
  - Verify, once 4.1 composes history, that composition is deterministic +
    append-only (prefix stability).
- **4.3 Execution isolation (addresses 3.3) - NOT an immediate addition.**
  Current approach already satisfies the invariant. Evaluate agentOS v0.2 only at
  the moment the stand-in loop is replaced with a real third-party Pi toolkit
  (the point "we wrote every line" stops being true). Until then, the lower-cost
  action is hardening what exists: **confirm the network-egress restriction is
  actually enforced in the deploy manifests** (`deploy/compose.secure.yml`,
  `deploy/fleet.Dockerfile`, `deploy/kernel.Dockerfile`), not just documented.

## 5. The invariant, restated in Nankle's terms

The pi lane's only path to a side effect is a kernel verb call over its
run-scoped MCP connection, through the full ten-step chokepoint, recorded in the
hash-chained audit log. Holds today; nothing in S4 weakens it.

- P2 (one chokepoint) + P8 (least privilege, deny-dominant, fail-closed) are
  kernel-side; nothing here touches `kernel/dispatch.py` or `kernel/grants.py`.
- SEC-27 (no secrets to Pi) + SEC-28 (sidecar severability) are sidecar-side; 4.1
  composes prompts before they reach the sidecar and must introduce NO credential
  or tool access into the composition step.
- 4.2 sits entirely on the read side of the boundary; it governs which provider a
  call reaches + cost, no authorization role; must not become a second place
  capability/credential logic lives (P1).

## 6. Sequencing

1. Build session continuity (4.1) in fleet/Store conventions: compose prior
   `ConversationMessage`s into the prompt before `spawn()`, pi lane only.
2. Verify prefix stability once 4.1 ships (deterministic + append-only).
3. Stand up the model-gateway binding store (4.2), keyed on conversation_id,
   synced to the gateway cache TTL.
4. Point PiRuntime's endpoint at the gateway + confirm cache-hit-rate
   observability before declaring complete.
5. Defer 4.3 until a real third-party Pi toolkit is adopted; meantime confirm
   egress restriction is enforced in deploy manifests.

## 7. Open items (to verify against code before relying on)

- Whether "the Pi open-source agent toolkit" (sidecar README) is the same toolkit
  as agentOS's built-in `pi` session type. If so, agentOS native pi may be a more
  direct path to a real loop, reopening 4.3 timing.
- Whether `HermesRuntime`'s name reflects intent to call Nous Research Hermes
  models (does not affect scope; hermes lane is non-agentic).
- Whether `nankle/identity` (auth/rbac/delegation/provisioning/tokens) maps
  cleanly onto SYSTEM-seat / autonomy-level language used earlier.
- Whether `tests/invariants.yaml` enforces "binding-debt 0" + the cited doctrine
  source exactly as described vs aspirationally.
- Whether richer Hatchet workflow defs (retry/idempotency beyond the step-boundary
  seam in `nankle/fleet/workers.py`) exist at the deployment layer or need
  authoring (workers.py says these are wired by the deployment).
