# The companion's runtime, the tiers, and agent-to-agent comms

A programme document, 2026-08-19. It answers five questions the Principal asked
- what runs a companion turn, whether Codex should be the primary, whether the
tier model is real, why "hello" once launched a subagent, and how tier-2 agents
should talk to each other - and it separates what was MEASURED today from what
is proposed. Anything measured names the file it was read from; anything
proposed says so.

## 1. What runs a companion turn - measured

The chat companion is NOT a bespoke in-kernel loop, and it is not "a Codex CLI
you are chatting to" either. It is a **fresh spawned agent per turn**, and on
the current dev deployment that agent runs in the **Codex runtime**.

The path, end to end:

- `POST /v1/chat` (`boltrig/kernel/app.py`) calls
  `ChatService.handle_turn` (`boltrig/fleet/chat.py`), which streams
  `stream_turn` -> `drive_turn_events` (`boltrig/fleet/chat_stream_drive.py`).
- The injected executor (`build_turn_executor` in
  `boltrig/fleet/chat_turn_execution.py`) builds a WorkItem
  (`source="chat"`, `owner_member="chief-of-staff"`) and calls
  `spawner.spawn(...)` with `announce_child=False` - **the turn itself IS a
  spawn**, deliberately unannounced so the companion does not render as its own
  subagent.
- `Spawner` (`boltrig/fleet/spawn.py`) resolves the runtime through
  `RuntimeResolver` (`boltrig/fleet/runtime_resolver.py`). The runtime is a
  property of the **capability**, not of chat: `AgentCapability.runtime` is
  `'codex' | 'script'` (decision 0012, `boltrig/models/libraries.py`).
- The chat knob names the capability. On the dev deployment the manifest says
  `chat.default_capability: worker-cheap`, and `worker-cheap` is declared
  `runtime: codex`. So every companion turn admits a Codex cell
  (`boltrig/fleet/codex_runtime.py`), with sensitive-data routing as the
  override that forces the local endpoint.

Two corollaries worth stating because they are easy to get wrong:

- The fleet-worker being stopped does not disprove any of this: the spawn runs
  in-process; the pump is a SECOND lane (see 3).
- "Which runtime is the companion" is a **manifest edit, not a code question**:
  point `chat.default_capability` at a `runtime: script` capability and the
  companion is the script loop, same seam, same governance.

## 2. Should the primary agent be Codex - decision open, now decidable

The trade, honestly stated now that 1 is measured:

- **Codex as the turn runtime** (today's configuration) buys a mature agent
  loop, a sandbox, per-cell tmpfs isolation, and the trusted lane - and costs
  cell admission per conversational turn, the 128-tool attestation ceiling, and
  a model set constrained to what the Codex path can bind.
- **The script runtime** buys direct model routing (any Bifrost-bindable
  provider - 196 of them as of PR #309) and lower per-turn overhead - and
  costs re-owning the loop quality Codex gives for free.

Recommendation, for the Principal to accept or refuse: **tier-split the
runtimes.** Conversation (tier 1) wants latency, breadth of model choice and
persona fidelity - the script runtime. Delegated work (tiers 2/3) wants
sandboxing, tools and durability - Codex. The seam already supports this
without new code: it is two capability entries and the chat knob. What it needs
first is the latency/quality measurement on a working endpoint, which today's
deployment cannot produce (see 4).

## 3. The tier model - real in code, but chat bypasses it

The tiers exist and are not decorative:

- **Tier 1**: `ChiefOfStaff` (`boltrig/fleet/chief_of_staff.py`) - permanent,
  routes normalised WorkItems to departments, never executes, deterministic
  fallback when no runtime is available.
- **Tier 2**: `DepartmentHead` (`boltrig/fleet/department_head.py`) -
  decomposes a routed item, spawns one ephemeral child per sub-task, enforces
  fan-out caps and the store-backed tree budget, escalates to HITL rather than
  running away.
- **Tier 3**: the ephemeral children those spawns create.

But the INTERACTIVE path does not pass through them. Chat has a deliberate
direct-spawn fast lane (`boltrig/fleet/pump.py` states the two-lane policy:
"chat keeps its DIRECT-SPAWN fast lane so an interactive turn never waits on a
queue; delegated work ... flows through the pump"). The chief of staff is the
router for the PUMP lane - channel intake, filed items, and a chat turn's
follow-ons - not for the turn you type.

So "is tier 1/2/3 set up to run properly?" divides: the machinery is built and
bounded; what is NOT yet true is that the companion you talk to is itself the
tier-1 orchestrator. Today the companion is a per-turn worker, and the
chief-of-staff is a back-office router the conversation never meets. Whether
that is the intended shape is a product decision this document flags rather
than makes.

## 4. The "hello spawned a subagent" bug - constrained, not yet reproduced

What is measured:

- A "subagent" card in the UI comes from exactly one event
  (`publish_subagent_event`, `boltrig/fleet/spawn_policy.py`), which fires only
  when a spawn runs with `announce_child=True`. The chat turn's own spawn
  passes `announce_child=False`, so the companion turn itself can never be the
  card. A card after "hello" means a SECOND, nested spawn happened.
- The candidate paths for that nested spawn, enumerated from the callers of
  `spawner.spawn`: the spawn route in `boltrig/kernel/app.py`; and the pump
  lane - `persist_new_work_items` (`boltrig/fleet/work_follow_ons.py`) persists
  any `new_work_items` the turn's result carries with `source="chat"`, the
  pump claims them, and `DepartmentHead` spawns announced children. **The
  likeliest mechanism is the second**: a model that returns a spurious
  work-item for a greeting produces an immediate, visible subagent.
- Reproduction was attempted today and is BLOCKED, and the blocker is itself a
  finding: on both the beelink stack and the dev deployment, `POST /v1/chat`
  "hello" answers `(model_endpoint_unavailable)` - the spawn happens, then
  runtime resolution fails because no BYO key has ever been stored (onboarding
  was broken for every provider until today's PR #309 and the
  `BOLTRIG_MODEL_GATEWAY_URL` fix on the box). The chain was: broken
  onboarding -> no key -> no endpoint -> every turn dies before the model.

Next concrete step, written here so it survives: store one real provider key
through the repaired onboarding, say "hello", and read the event stream for a
`subagent` event and the store for `new_work_items` rows with `source="chat"`.
If the greeting produces a follow-on work item, the fix belongs in the turn
task contract (what the model is told about `new_work_items`), not in the UI.

## 5. Tier-2 agent-to-agent comms - proposed design

Boltrig has no agent-to-agent channel. Three working references inform the
shape: the Grok bot, Claude Code's cross-session messaging (used productively
on this box today, including for peers correcting each other's measurements),
and Hermes.

**The driving case, which should shape the design rather than follow it - the
mail manager**: Chatwoot mails every OPTED-IN agent about every message; a
receiving agent can forward the mail to the right agent inside that agent's
run. Fan-out plus in-run routing exercises every property a generic channel
needs.

Proposed mechanism, deliberately built from seams that already exist:

- **An address is a permanent agent.** `boltrig/fleet/permanent_runtime.py`
  agents are the only things alive long enough to receive; ephemerals get
  replies through their parent, never their own inbox.
- **Delivery is a WorkItem, not a socket.** A message from agent A to agent B
  is a WorkItem with `source="agent"`, `source_id=A`, routed by the existing
  pump/ChiefOfStaff lane to B. This inherits at zero cost everything the estate
  already trusts: durability, the tree budget, fan-out caps, HITL escalation,
  and the audit trail (who forwarded what to whom is the WorkItem lineage).
- **Opt-in is a registry row, not a convention.** A `subscriptions` relation
  (agent, topic, source filter) that the Chatwoot channel adapter fans out
  against; an agent not subscribed receives nothing, and the fan-out is capped
  by the same per-step bounds DepartmentHead already enforces.
- **In-run forwarding is a verb.** `agent.forward(work_item_id, to_agent)` -
  governed like any verb, consequence-classified, so a forward is auditable and
  HITL-gateable exactly like any other side effect.
- **A message that cannot be delivered fails VISIBLY**: undeliverable ->
  `WorkStatus.FAILED` with a failed-child record, never a silent drop - the
  property the mail case makes non-negotiable.

What this deliberately does not build: a live socket between agents (the pump
IS the transport), a broadcast primitive (fan-out only through subscriptions),
or cross-tenant delivery (the WorkItem carries tenant_id and RLS already fences
it).

## Standing risks this programme inherits

- The masking-gate chain: `make python-quality` stops at its first failure;
  run the whole local chain before any push (it cost five CI round trips on one
  branch today, and one more on PR #309).
- The React 18/19 node_modules trap: never borrow a worktree's install.
- Evidence discipline: stage, capture, then stage nothing else before commit.
