---
area: "03 The permanent fleet: hierarchy, spawn, budget"
id-block: BT-REQ-0300..BT-REQ-0399
referent commit: 19bcae7fa81663fe8998377c86451ba08fb16e48 (origin/main)
author-agent: area-03-fleet-core
date: 2026-08-24
---

## Bound of this reading

`boltrig/fleet/` holds 225 files. This spec reads exhaustively, line by line, the
modules that carry the durable hierarchy and the spawn economics:
`spawn.py`, `spawn_policy.py`, `spawn_skills.py`, `spawn_budget.py`,
`spawn_reservation.py`, `spawn_completion.py`, `spawn_entrypoints.py`,
`pump.py`, `pump_policy.py`, `pump_progress.py`, `named_work_routing.py`,
`org_builder.py`, `chief_of_staff.py`, `department_head.py`, `named_agent.py`,
`permanent_runtime.py`, `permanent_runtime_factories.py`, `runtime_resolver.py`,
`authority.py`, `work_follow_ons.py`, `lease_token.py`, `result.py`,
`reflection.py`, `workers.py`, `hatchet_app.py`, `hatchet_bootstrap.py`,
`hatchet_contract.py`, `agent_turns.py`, plus the collaborating non-fleet files
`boltrig/kernel/cost.py`, `boltrig/config/spawn_rules.py`,
`boltrig/config/manifest_agents.py`, `boltrig/config/manifest_apply.py`,
`boltrig/work/store.py`, `boltrig/work/normalise.py`,
`boltrig/store/work_mutations.py`, `boltrig/api/worker.py`.

Read at the level of top-level definitions and call sites only (not line by
line): `boltrig/fleet/agent_mailbox.py`, `boltrig/fleet/chat_turn_execution.py`,
`boltrig/fleet/eval.py`, `boltrig/fleet/ultracode.py`, `boltrig/fleet/retention.py`.

NOT read, and deliberately out of scope (area 04 owns them): the 60-odd
`boltrig/fleet/infrastructure/codex_*` modules, `codex_runtime*.py`,
`boltrig/fleet/domain/*`, `boltrig/fleet/application/*`, `browser_*`,
`chat_*` beyond the spawn call site, `model_proxy_*`, `ultracode_*` internals.
Where this spec touches those it says so and stops at the seam.

---

## 2. Purpose

The fleet core turns a normalised unit of work into a governed, metered,
audited agent run. It owns two things: a durable, addressable roster of
long-lived agents that receive work, and the ephemeral spawn path that composes
skills, picks a runtime, reserves spend before anything runs, and settles the
result. Everything above it (channels, chat, Hatchet) is intake; everything
below it (the runtime protocol, Codex cells) is area 04.

---

## 3. Boundaries

**Owns.** `Spawner` and its intake/reservation/completion helpers; the
`WorkPump` serving loop and the work-item state walk; `NamedAgent` /
`DepartmentHead` fan-out, caps and escalation; `PermanentAgentRuntime` (the
durable profile's metered reasoning phase); `RuntimeResolver`'s routing decision
(but not what it builds); the claim-time lease fence; the work-item authority
resolution.

**Must not touch.** The fleet imports the kernel only through the composed
`Kernel` object handed to it; `chief_of_staff.py` and `department_head.py` guard
their kernel and runtime imports behind `TYPE_CHECKING` explicitly so the fleet
carries no runtime import of the kernel package
([`boltrig/fleet/department_head.py:26`](../../../boltrig/fleet/department_head.py)
`"if TYPE_CHECKING:  # type-only seams"`). The architecture gate
`make architecture` enforces inward-only thin-orchestration dependencies
([`Makefile:115`](../../../Makefile) `"architecture: ## Enforce inward-only"`).

**Forbidden by rule.** Policy is data, never code: adding a department, an
agent, a spawn rule or a price is a manifest edit, never a core change
([`manifest.example.yaml:9`](../../../manifest.example.yaml)
`"never a core code change"`, P1/P7). The spawn path never widens authority: a
child's grants are always an intersection
([`boltrig/fleet/spawn.py:169`](../../../boltrig/fleet/spawn.py)
`"child_grants = GrantSet.of(allow=list(intake.tool_grants)).intersect("`).

**Seams named.** Hatchet (durable engine, external), the Codex binary and its
supervised cell (area 04), an on-box model endpoint, the IdP behind
`effective_grants_for_request`.

---

## 4. Objects and contracts

### 4.1 The four README claims, answered

The README states the fleet is "a durable hierarchy (a tier1 chief-of-staff over
tier2 department heads) [that] takes in work and spawns short-lived child agents
to do it, picking the cheapest capable runtime, reserving budget first, and
enforcing recursion depth"
([`README.md:34`](../../../README.md) `"A permanent fleet that spawns ephemerals."`).

| Claim | Verdict | Where it is settled |
| --- | --- | --- |
| tier1 chief-of-staff over tier2 department heads | **FALSE as serving topology.** The live composition is a FLAT roster of tier-1 peers. `build_org` passes `None` where the Chief of Staff would go and marks every named agent tier-1. | [`boltrig/fleet/org_builder.py:60`](../../../boltrig/fleet/org_builder.py) `"None,"` (the `chief_of_staff` positional); [`boltrig/fleet/pump.py:191`](../../../boltrig/fleet/pump.py) `"build_org no longer composes that hierarchy."` |
| spawns short-lived child agents | **TRUE.** Every peer delegates through `Spawner.spawn`, which mints a fresh `run_id` per child and retires its credentials at the child's terminal. | [`boltrig/fleet/department_head.py:184`](../../../boltrig/fleet/department_head.py) `"result = await self._spawner.spawn("`; [`boltrig/fleet/spawn.py:104`](../../../boltrig/fleet/spawn.py) `"run_id = uuid.uuid4().hex"` |
| picking the cheapest capable runtime | **TRUE BUT DEFAULT-ONLY.** Cheapest-by-cost-tier is the tie-break after every pin (`prefer.capability`, `prefer.runtime`, `prefer.cost_tier`, and any matched spawn rule) has been applied. | [`boltrig/fleet/spawn_skills.py:193`](../../../boltrig/fleet/spawn_skills.py) `"return min(capable, key=lambda cap:"`; [`boltrig/config/spawn_rules.py:376`](../../../boltrig/config/spawn_rules.py) `"effective_prefer[\"capability\"] = rule.capability"` |
| reserving budget first | **TRUE.** `reserve_spawn` runs before the runtime is resolved or invoked, and a raise after reservation refunds the whole estimate. | [`boltrig/fleet/spawn.py:106`](../../../boltrig/fleet/spawn.py) `"reservation = await reserve_spawn("` ahead of line 126 `"result, model_route, latency_ms = await self._invoke_runtime("` |
| enforcing recursion depth | **TRUE ON TWO LANES, INERT ON THE PUMP AND CHAT LANES.** The check exists and raises, but the pump and chat both build their context with the default `depth=0`, so a delegated child is always depth 1 and can never exceed a `max_depth` of 2 or more. | check at [`boltrig/fleet/spawn_policy.py:124`](../../../boltrig/fleet/spawn_policy.py) `"if child_depth > max_depth:"`; pump context has no depth at [`boltrig/fleet/authority.py:74`](../../../boltrig/fleet/authority.py) `"return InvocationContext("`; default at [`boltrig/models/context.py:22`](../../../boltrig/models/context.py) `"depth: int = 0"` |

The topology supersession is stated in-tree as a programme decision:
"There is no live tier 2 or tier 3. `HierarchyConfig`, `ChiefOfStaff`, and
`DepartmentHead` remain only where required to read an old manifest"
([`docs/PROGRAM-2026-08-19-companion-runtime-and-agent-comms.md:19`](../../../docs/PROGRAM-2026-08-19-companion-runtime-and-agent-comms.md)
`"There is no live tier 2 or tier 3."`). The invariant catalogue binds the flat
shape, not the README's
([`tests/invariants.yaml:2740`](../../../tests/invariants.yaml) `"FLT-PEER-01:"`).

### 4.2 The nouns

**`WorkItem`** is the fleet's only unit of work and the durable state carrier
([`boltrig/models/work.py:32`](../../../boltrig/models/work.py) `"class WorkItem:"`).
Load-bearing fields: `status` (the state machine), `attempts` (incremented by
the claim, not by the body), `lease_owner`/`lease_expires_at` (the claim tuple),
`parent_id` and `depth` (the delegation tree), `owner_member` (the routed
agent, which the run's context also claims as its `principal_scope`),
`on_behalf_of` + `workspace_id` (the authority the run executes at), `target`
(routing data, never authority), `convergent` (whether a degraded aggregate may
still be DONE), `degraded`, `result`, `constraints` (which carries the
server-stamped creator and thread grant ceilings), `reply_route`.

**`WorkStatus`** has seven members: `pending`, `in_flight`, `blocked`,
`awaiting_human`, `done`, `failed`, `cancelled`
([`boltrig/models/work.py:17`](../../../boltrig/models/work.py) `"class WorkStatus(str, Enum):"`).

**`AgentCapability`** is a runtime profile: `runtime` (`codex` | `script` |
`python-script` | `go-binary` | anything else, which becomes a typed-unavailable
runtime), `supported_skills` patterns, `max_depth`, `is_ephemeral`, `cost_tier`
in the closed vocabulary `cheap|standard|expensive`, `model_endpoint`,
`workspace_id` (NULL = org-wide), `source` (`manifest` | `control-plane`),
`is_active` ([`boltrig/models/libraries.py:83`](../../../boltrig/models/libraries.py)
`"class AgentCapability:"`;
[`boltrig/models/libraries.py:25`](../../../boltrig/models/libraries.py)
`"COST_TIERS: tuple[str, ...] = (\"cheap\", \"standard\", \"expensive\")"`).

**`NamedAgentConfig`** is one durable, addressable tier-1 peer as authored:
`name`, `address` (a lowercase slug, the routing key), `runtime` restricted to
`{codex, script, python-script}`, `model_endpoint`, `max_depth` bounded 1..5,
`supported_skills` 1..64 bounded strings, `cost_tier`, `scope_id` (the budget
scope), `budget`, `purpose` (<=500 chars), `brief` (<=8000 chars)
([`boltrig/config/manifest.py:138`](../../../boltrig/config/manifest.py)
`"class NamedAgentConfig:"`;
[`boltrig/config/manifest_agents.py:58`](../../../boltrig/config/manifest_agents.py)
`"named agent address must be a lowercase address slug"`).

**`NamedAgentsConfig`** enforces uniqueness of names and addresses and that
`agents.default` names a declared address
([`boltrig/config/manifest.py:167`](../../../boltrig/config/manifest.py) `"agents.default must name a declared agent address"`).

**`HierarchyTier` / `HierarchyConfig`** survive only as an input bridge:
"Deprecated Chief/Department manifest record accepted for migration"
([`boltrig/config/manifest.py:104`](../../../boltrig/config/manifest.py)
`"Deprecated Chief/Department manifest record accepted"`). `resolve_named_agents`
converts a legacy hierarchy into the flat roster: tier1 becomes the address
`cos` and the default; each tier2 becomes an address from its `department` or
name ([`boltrig/config/manifest_agents.py:107`](../../../boltrig/config/manifest_agents.py) `"address=\"cos\","`).

**`SpawnIntake`** is the frozen record of everything resolved before spend:
effective skills, effective prefer, merged prompt, tool grants, capability,
child depth, spawn-rule selection
([`boltrig/fleet/spawn_policy.py:42`](../../../boltrig/fleet/spawn_policy.py)
`"class SpawnIntake:"`).

**`SpawnRule` / `SpawnRuleSelection`** are closed policy data: name, priority
0..1000, an all-of `intent_tags` predicate, a capability, added skills, and an
optional `max_depth` that may only tighten
([`boltrig/config/spawn_rules.py:39`](../../../boltrig/config/spawn_rules.py)
`"class SpawnRule:"`). The selection's `receipt()` is the bounded object copied
into the child context, the audit row, the subagent event and the public result.

**`AgentResult`** is the one shape every runtime returns: `ok`, `output`,
`summary`, `tokens_used`, `cost_micros`, `new_work_items`, `degraded`,
`input_tokens`, `output_tokens`
([`boltrig/fleet/result.py:16`](../../../boltrig/fleet/result.py)
`"class AgentResult:"`). A degrade returns `ok=True` with `degraded=True` and
carries only the prompt's sha256 and byte length, never the prompt
([`boltrig/fleet/result.py:130`](../../../boltrig/fleet/result.py)
`"prompt_bytes = prompt.encode(\"utf-8\")"`).

**`BudgetReservation`** is the exact set of usage buckets selected atomically
for one estimated call
([`boltrig/kernel/cost.py:58`](../../../boltrig/kernel/cost.py) `"class BudgetReservation:"`).

**`LeaseToken`** is the `(owner, expires_at)` pair the claim handed out,
compared for exact equality by the conditional write
([`boltrig/fleet/lease_token.py:56`](../../../boltrig/fleet/lease_token.py)
`"class LeaseToken:"`).

### 4.3 Lifecycles

**Work item state machine** (the guard, not a full FSM), from
[`boltrig/work/store.py:23`](../../../boltrig/work/store.py) `"_TRANSITIONS: dict[WorkStatus, set[WorkStatus]]"`:

```
PENDING        -> IN_FLIGHT, BLOCKED, AWAITING_HUMAN, FAILED, CANCELLED
IN_FLIGHT      -> BLOCKED, AWAITING_HUMAN, DONE, FAILED, CANCELLED
BLOCKED        -> PENDING, IN_FLIGHT, FAILED, CANCELLED
AWAITING_HUMAN -> IN_FLIGHT, BLOCKED, DONE, FAILED, CANCELLED
DONE           -> (terminal, no outgoing edge)
FAILED         -> PENDING, IN_FLIGHT
CANCELLED      -> (terminal, no outgoing edge)
```

The pump does NOT route its writes through this guard; it writes the status
field directly under the lease fence
([`boltrig/fleet/lease_token.py:118`](../../../boltrig/fleet/lease_token.py)
`"async def write(store: Store, item: WorkItem, *, what: str)"`). The guard binds
the governed `control.work.*` path
([`boltrig/config/control_work.py:158`](../../../boltrig/config/control_work.py)
`"item = await governed_mutate_work("`). The pump's own settled set is a separate
constant: `{DONE, FAILED, CANCELLED, AWAITING_HUMAN}`
([`boltrig/fleet/pump.py:67`](../../../boltrig/fleet/pump.py) `"SETTLED_STATUSES = frozenset("`).

**Ephemeral agent lifecycle** (one `Spawner.spawn` call):

```
intake resolved  -> run_id minted -> estimate -> budget reserved
                 -> child grants intersected -> child context built
                 -> parent bearer re-sealed under the child run id
                 -> runtime resolved (PII classification decides the destination)
                 -> subagent OPEN frame published on the parent relay
                 -> runtime.run(...)
                 -> subagent_end SETTLE frame (ok | degraded | error)
                 -> child run credentials swept
                 -> cost trued up -> artifacts produced -> AGENT_SPAWN audit row
                 -> public envelope returned
```
Every step is cited in section 5.1. The child has no work item, no mailbox, no
peer address and no `agent.send` right
([`boltrig/fleet/named_agent.py:107`](../../../boltrig/fleet/named_agent.py)
`"list(context.grants.deny) + [\"agent.send\", \"chat.present\"]"`;
[`tests/invariants.yaml:2747`](../../../tests/invariants.yaml) `"FLT-PEER-02:"`).

**Durable named-agent turn lifecycle.** A named agent that has a registry row
takes its work-item turn inside a serialized, heartbeaten, cross-worker lease:
`acquire_agent_turn` (polled until granted) -> heartbeat every
`max(1, min(30, lease/3))` seconds -> the body -> `release_agent_turn` in a
`finally`; a lost heartbeat raises `AgentTurnLeaseLost`
([`boltrig/fleet/agent_turns.py:48`](../../../boltrig/fleet/agent_turns.py)
`"async def hold("`;
[`boltrig/fleet/named_agent.py:84`](../../../boltrig/fleet/named_agent.py)
`"async with coordinator.hold("`). Default turn lease 300s, waiter TTL 900s,
poll 0.1s ([`boltrig/fleet/agent_turns.py:20`](../../../boltrig/fleet/agent_turns.py)
`"DEFAULT_AGENT_TURN_LEASE_SECONDS = 300"`).

**Permanent profile phase lifecycle.** A `PermanentAgentRuntime` call is not a
resident process: preflight (tenant match, depth) -> derive a stable phase run
id as `sha256("permanent-runtime\0parent\0role\0capability")[:32]` -> compose the
authored profile prompt -> estimate -> reserve on tenant + department scopes ->
resolve the runtime under `pinned_policy=True` -> run -> true up -> one
`MODEL_CALL` audit row
([`boltrig/fleet/permanent_runtime.py:159`](../../../boltrig/fleet/permanent_runtime.py)
`"async def _run("`;
[`boltrig/fleet/permanent_runtime.py:49`](../../../boltrig/fleet/permanent_runtime.py) `"def _phase_run_id(parent_run_id: str, role: str"`).

---

## 5. Control flow

### 5.1 `Spawner.spawn`: one ephemeral child, end to end

1. **Resolve one policy snapshot and route.** `prepare_spawn_intake` reads the
   effective spawn rules once (the latest persisted revision, or the manifest
   base) and applies the all-of `prefer.intent_tags` predicate
   ([`boltrig/fleet/spawn.py:94`](../../../boltrig/fleet/spawn.py)
   `"intake = await prepare_spawn_intake("`;
   [`boltrig/fleet/spawn_policy.py:83`](../../../boltrig/fleet/spawn_policy.py)
   `"rules = await _effective_rules(store, tenant_id, base_rules)"`).
   *Failure branch:* an unreadable or invalid policy raises
   `SpawnRulePolicyInvalid`, never a silent empty rule set
   ([`boltrig/fleet/spawn_policy.py:67`](../../../boltrig/fleet/spawn_policy.py)
   `"current spawn-rule policy could not be read"`). Equal-priority ties raise
   `SpawnRuleMatchError`
   ([`boltrig/config/spawn_rules.py:275`](../../../boltrig/config/spawn_rules.py)
   `"spawn rules tie at priority"`). A caller pin that conflicts with the matched
   rule is refused, not ignored
   ([`boltrig/config/spawn_rules.py:363`](../../../boltrig/config/spawn_rules.py)
   `"conflicts with requested capability"`).
2. **Merge the skill chain.** Each requested skill is resolved parent-first
   through its `extends` chain, cycle-guarded by a `seen` set; prompt fragments
   concatenate, tool grants de-duplicate, `context_requirements` schemas merge
   ([`boltrig/fleet/spawn_skills.py:78`](../../../boltrig/fleet/spawn_skills.py)
   `"async def _resolve_skill_chain("`).
   *Failure branch:* an unknown skill or parent raises `SkillNotFound` (404).
3. **Validate the spawn context against the merged schema.** Only non-None
   context values are offered; missing required keys or Draft 2020-12 errors
   raise `ContextRequirementsUnmet`
   ([`boltrig/fleet/spawn_policy.py:100`](../../../boltrig/fleet/spawn_policy.py)
   `"raise ContextRequirementsUnmet("`).
4. **Select the capability.** The candidate set is the caller's workspace roster
   UNION the org-wide profiles, active rows only; then filter to those covering
   every requested skill; then apply `prefer.capability` (hard, raises if not
   capable), `prefer.runtime` (hard, with the `script` -> `python-script` alias),
   `prefer.cost_tier` (soft: applied only if it matches something); finally
   `min` by `(cost tier index, name)`
   ([`boltrig/fleet/spawn_skills.py:144`](../../../boltrig/fleet/spawn_skills.py) `"\"\"\"Select the cheapest capable runtime, honouring explicit pins."`;
   [`boltrig/fleet/spawn_skills.py:193`](../../../boltrig/fleet/spawn_skills.py)
   `"return min(capable, key=lambda cap:"`).
   *Failure branch:* `NoCapableRuntime` (404); if a spawn rule chose the
   capability the error is re-raised as `SpawnRulePolicyInvalid` naming the rule
   ([`boltrig/fleet/spawn_policy.py:116`](../../../boltrig/fleet/spawn_policy.py)
   `"spawn rule '{spawn_rule.rule_id}' targets an unavailable "`).
5. **Enforce recursion depth.** `child_depth = context.depth + 1`; the ceiling is
   `capability.max_depth`, tightened by `min(...)` with the rule's `max_depth`
   when a rule matched; exceeding it raises `DepthExceeded`
   ([`boltrig/fleet/spawn_policy.py:120`](../../../boltrig/fleet/spawn_policy.py)
   `"child_depth = context.depth + 1"`).
6. **Mint the run id and estimate.** `run_id = uuid4().hex`. The estimate is
   deterministic and character-based: `tokens = max(16, chars // 4)` over task +
   merged prompt + skill ids, priced at the tier
   ([`boltrig/fleet/spawn_budget.py:18`](../../../boltrig/fleet/spawn_budget.py)
   `"tokens = max(16, chars // 4)"`).
7. **Reserve budget, before anything runs.** Scopes are
   `[tenant_id] + ([prefer.department] if present)`
   ([`boltrig/fleet/spawn_budget.py:12`](../../../boltrig/fleet/spawn_budget.py)
   `"return [tenant_id, *([str(department)] if department else [])]"`), passed to
   `CostAccountant.reserve`
   ([`boltrig/fleet/spawn_reservation.py:29`](../../../boltrig/fleet/spawn_reservation.py)
   `"return await spawner._kernel.cost.reserve("`).
   *Failure branch:* `BudgetExceeded` writes an `AGENT_SPAWN` audit row with
   `status="budget_exceeded"` and then either re-raises (when
   `partial_on_budget=False`) or returns the standard partial envelope
   ([`boltrig/fleet/spawn_reservation.py:48`](../../../boltrig/fleet/spawn_reservation.py)
   `"if not partial_on_budget:"`).
8. **Compute the child's authority.** The merged skills' declared `tool_grants`
   are intersected with the parent context's grants unconditionally, and then
   with an optional `grant_ceiling` when the caller supplied one
   ([`boltrig/fleet/spawn.py:169`](../../../boltrig/fleet/spawn.py)
   `"child_grants = GrantSet.of(allow=list(intake.tool_grants)).intersect("`).
9. **Build the child context.** Least authority, `actor_tier="ephemeral"`,
   `parent_run_id` set, `depth = child_depth`, the parent's `extra` copied with
   any inherited spawn-rule key stripped and only the trusted receipt restamped;
   a Codex child with no workspace gets `workspace_id = run_id`
   ([`boltrig/fleet/spawn_policy.py:150`](../../../boltrig/fleet/spawn_policy.py)
   `"\"\"\"Build a least-authority child context and stamp only trusted rule data."`).
10. **Propagate the sealed adapter bearer.** The caller's clamped external bearer
    is re-sealed under the CHILD run id, best-effort, because
    `resolve_run_scoped_credential` is keyed by run id and the dispatch happens
    under the child
    ([`boltrig/fleet/spawn.py:231`](../../../boltrig/fleet/spawn.py)
    `"await self._inherit_adapter_bearer(tenant_id, context.run_id, run_id"`).
    *Failure branch:* a failure is a no-op and dispatch falls back to the
    adapter's static credential.
11. **Resolve the runtime with the composed prompt as the egress payload.** The
    PII scanner classifies the outbound text before the destination is decided,
    so a detection reroutes to the sensitive endpoint
    ([`boltrig/fleet/spawn.py:236`](../../../boltrig/fleet/spawn.py)
    `"runtime = await self._runtime_for("`).
12. **Publish the subagent OPEN frame** when the parent has a run id and
    `announce_child` is true; best-effort
    ([`boltrig/fleet/spawn_policy.py:188`](../../../boltrig/fleet/spawn_policy.py) `"\"\"\"Publish the bounded public delegation receipt without failing the spawn."`).
13. **Run.** `runtime.run(composed_prompt, child_ctx, tools=list(child_grants.allow))`
    ([`boltrig/fleet/spawn.py:247`](../../../boltrig/fleet/spawn.py)
    `"result = await runtime.run("`).
    *Failure branch:* on ANY exception the open frame is settled as `error`, the
    FULL estimate is refunded (`delta = -estimate`), child credentials are
    retired, and the exception re-raises
    ([`boltrig/fleet/spawn.py:255`](../../../boltrig/fleet/spawn.py)
    `"self._publish_subagent_end_event(context, run_id, \"error\")"`).
14. **Settle the frame and retire credentials** on the success return too, using
    `degraded -> ok -> error` in that order
    ([`boltrig/fleet/spawn.py:268`](../../../boltrig/fleet/spawn.py)
    `"status = \"degraded\" if result.degraded else \"ok\" if result.ok else \"error\""`).
15. **True up the cost and return the priced number.** Actual tokens are priced
    leg by leg when the runtime reported a split, at the tenant's per-model rate
    when one is configured, otherwise the tier default; the signed delta
    `(actual - estimate)` is reconciled across every reserved scope
    ([`boltrig/fleet/spawn.py:390`](../../../boltrig/fleet/spawn.py)
    `"actual_micros = self._kernel.cost.price("`).
16. **Produce artifacts, audit, project.** `status` is
    `degraded` if `result.degraded or artifacts.rejected`, else `ok` if
    `result.ok`, else `error`
    ([`boltrig/fleet/spawn_completion.py:68`](../../../boltrig/fleet/spawn_completion.py)
    `"status = \"degraded\" if result.degraded or artifacts.rejected else ("`). One
    `AGENT_SPAWN` audit row carries capability, runtime, spawn-rule receipt,
    public model route, degrade reason, latency, tokens, cost
    ([`boltrig/fleet/spawn.py:472`](../../../boltrig/fleet/spawn.py)
    `"event = AuditEvent("`). The observability sink runs AFTER the audit write and
    its failure is swallowed
    ([`boltrig/fleet/spawn.py:504`](../../../boltrig/fleet/spawn.py) `"except Exception:"`).
17. **Return the public envelope**: `run_id`, `agent_type`, `status`, `degraded`,
    `summary`, `output`, `tokens_used`, `cost_micros`, `new_work_items`,
    `effective_grants`, `artifacts` (ids and names only, never bytes),
    `artifact_rejected`, optional `spawn_rule`
    ([`boltrig/fleet/artifact_production.py:277`](../../../boltrig/fleet/artifact_production.py)
    `"envelope = {"`).

### 5.2 `WorkPump.run_once`: one serving cycle

1. **Alternate the two durable lanes.** When a mailbox is wired and
   `_prefer_mailbox` is set, one peer-message turn runs first; a claimed message
   flips the preference so filed work cannot be starved, and vice versa
   ([`boltrig/fleet/pump.py:214`](../../../boltrig/fleet/pump.py)
   `"if self._mailbox is not None and self._prefer_mailbox:"`).
2. **Claim one work item.** `claim_work_item` is a single atomic statement:
   `pending` OR (`in_flight` AND `lease_expires_at < now()`), `ORDER BY
   created_at LIMIT 1 FOR UPDATE SKIP LOCKED`, setting status, owner, a fresh
   lease and `attempts = attempts + 1`
   ([`boltrig/store/postgres.py:451`](../../../boltrig/store/postgres.py)
   `"UPDATE work_items"` ... `"FOR UPDATE SKIP LOCKED"`). The in-memory store
   mirrors it and hands back a COPY
   ([`boltrig/store/memory.py:409`](../../../boltrig/store/memory.py) `"# A copy: the claimer must not hold the stored object"`).
   *Failure branch:* `None` means idle; the loop sleeps.
   Note: a child created IN_FLIGHT with a NULL lease can never match either
   predicate, which is why department children and chat items are never claimed
   ([`boltrig/fleet/department_head.py:225`](../../../boltrig/fleet/department_head.py)
   `"status=WorkStatus.IN_FLIGHT,"`).
3. **Encode the claim-time lease token onto the payload.**
   `{"tenant_id", "item_id", "lease_owner", "lease_expires_at"}` where the expiry
   is `isoformat()` so it survives JSON
   ([`boltrig/fleet/pump.py:227`](../../../boltrig/fleet/pump.py)
   `"payload = {\"tenant_id\": tenant_id, \"item_id\": item.id, **lease_token.encode(item)}"`).
4. **Choose a carriage.** A durable executor gets `enqueue(WORK_ITEM_TASK,
   payload)`; otherwise the same body runs inline
   ([`boltrig/fleet/pump.py:228`](../../../boltrig/fleet/pump.py)
   `"if self._executor is not None and getattr(self._executor, \"durable\", False):"`).
5. **`_run_item_payload`** decodes and binds the token to the task's context var,
   re-reads the row, and stands down if the row already carries someone else's
   claim ("an early exit, NOT the fence")
   ([`boltrig/fleet/pump.py:500`](../../../boltrig/fleet/pump.py) `"log.warning(\"item %s was re-claimed before its body ran; standing down\""`).
   *Failure branch:* any exception from the body goes to `_record_failure`;
   `asyncio.CancelledError` is re-raised untouched.

### 5.3 `handle_claimed_item`: route, execute, settle

1. **Shadow root admission** (SEC-172): a root item (no `parent_id`) records one
   replay-safe, execution-neutral decision when the Codex ledger stack is
   composed; `None` means off
   ([`boltrig/fleet/pump.py:255`](../../../boltrig/fleet/pump.py) `"await self._codex_execution.shadow_admit(item.tenant_id"`). Area 04.
2. **BLOCKED work is a human's, not a retry's**: park immediately
   ([`boltrig/fleet/pump.py:257`](../../../boltrig/fleet/pump.py)
   `"if item.status == WorkStatus.BLOCKED:  # blocked work is a human's"`).
3. **Cancel boundary 0**, before any dispatch. The whole body sits in a
   `try/finally` whose `finally` calls `_cancel` when the marker is set
   ([`boltrig/fleet/pump.py:267`](../../../boltrig/fleet/pump.py)
   `"cancelled = await self._store.is_run_cancel_requested(tenant, run_id)"`).
4. **Build the execution context** at the requesting principal's authority
   (section 5.5), then seat the default peer for routing
   ([`boltrig/fleet/pump.py:272`](../../../boltrig/fleet/pump.py)
   `"ctx = await self._context_for(item, run_id)"`).
5. **Honour a `workflow:<id>` target before any agent routing.** The workflow
   runs through the library's durable path under the item's context, so every
   step is chokepoint-checked against the requesting principal. An unknown
   workflow parks with a HITL rather than falling through
   ([`boltrig/fleet/pump.py:354`](../../../boltrig/fleet/pump.py) `"\"\"\"Honor a ``workflow:<wf_id>`` target: trigger the named workflow (SEC-178)."`).
6. **Resolve the handler.** Flat lane: an explicit `target` (or the declared
   default when the target is empty or the legacy `"cos"`) is looked up in
   `named_agents`; `owner_member` is stamped and the route checkpoint written
   ([`boltrig/fleet/named_work_routing.py:40`](../../../boltrig/fleet/named_work_routing.py)
   `"address = self._default_agent if target in {\"\", \"cos\"} else target"`).
   Legacy lane: `route_to_head` honours an explicit target that resolves to a
   configured head, else asks the Chief of Staff
   ([`boltrig/fleet/authority.py:156`](../../../boltrig/fleet/authority.py)
   `"department = await cos.route(item, ctx)"`).
   *Failure branch (both lanes):* `None` parks the item AWAITING_HUMAN with a
   HITL escalation, reason `unroutable_agent` or `unroutable_department`
   ([`boltrig/fleet/pump.py:342`](../../../boltrig/fleet/pump.py)
   `"reason=(\"unroutable_agent\" if self._flat_agents else \"unroutable_department\")"`).
7. **Cancel boundary 1**, immediately before dispatch.
8. **Rebuild the context and seat the routed peer**, adding `agent.send` and
   stamping `named_agent_address`
   ([`boltrig/fleet/named_work_routing.py:24`](../../../boltrig/fleet/named_work_routing.py)
   `"list(context.grants.allow) + [\"agent.send\"],"`).
9. **Compute the tree root** by walking `parent_id` cycle-safely, and dispatch
   `head.handle(item, ctx, tree_id=...)`
   ([`boltrig/fleet/pump.py:295`](../../../boltrig/fleet/pump.py)
   `"tree_id = await tree_root_id(store, item)"`).
   The in-flight call is never interrupted: "FORBIDDEN: no mid-step hard kill".
10. **Join.** `item.result = outcome`; `item.degraded` is the outcome's own flag
    OR any child's
    ([`boltrig/fleet/pump.py:306`](../../../boltrig/fleet/pump.py)
    `"item.degraded = bool(outcome.get(\"degraded\")) or any("`).
11. **Cancel boundary 2**, after the step. A cancel seen here suppresses every
    downstream effect: no follow-on work items, no workflow learning
    ([`boltrig/fleet/pump.py:314`](../../../boltrig/fleet/pump.py)
    `"cancelled = await self._store.is_run_cancel_requested(tenant, run_id)"`).
12. **Persist follow-on work** as PENDING children with `source="internal"`
    (section 5.6).
13. **Settle** (`_settle`): an `escalated` outcome goes to `_await_human` using
    the HITL id the head already filed; a `convergent` item with a degraded
    aggregate parks rather than reaching DONE; otherwise DONE with the outcome
    score stamped, the optional workflow learn, the fenced write, the
    `execute/done` checkpoint, reflection and the terminal notify
    ([`boltrig/fleet/pump.py:425`](../../../boltrig/fleet/pump.py)
    `"async def _settle(self, item: WorkItem, run_id: str, outcome: dict)"`;
    [`boltrig/fleet/pump.py:431`](../../../boltrig/fleet/pump.py)
    `"if item.convergent and item.degraded:"`).

### 5.4 Delegation: `NamedAgent.handle` over `DepartmentHead.handle`

1. **Serialize the peer's turn** when the address has a registry row; a
   compatibility-constructed agent with no row skips straight to the body
   ([`boltrig/fleet/named_agent.py:77`](../../../boltrig/fleet/named_agent.py)
   `"if profile is None:"`).
2. **Narrow the children's authority.** The child context adds explicit DENIES
   for `agent.send` and `chat.present`, chosen because a deny dominates even a
   `*` allow
   ([`boltrig/fleet/named_agent.py:103`](../../../boltrig/fleet/named_agent.py)
   `"child_context = replace("`).
3. **Decompose.** With a runtime, ask it for sub-tasks and accept
   `output["subtasks"]`, `output["tasks"]`, or line-split `output["text"]`; the
   deterministic fallback is a single sub-task carrying the item's intent
   ([`boltrig/fleet/department_head.py:252`](../../../boltrig/fleet/department_head.py)
   `"# Deterministic fallback: a single sub-task carrying the item's intent."`).
   *Failure branch:* a decomposition exception is logged at debug and falls back
   (P9).
4. **Per-step fan-out cap.** `len(subtasks) > max_children_per_step` (default 8)
   escalates instead of spawning
   ([`boltrig/fleet/department_head.py:105`](../../../boltrig/fleet/department_head.py)
   `"if len(subtasks) > self.max_children_per_step:"`).
5. **Per-tree spawn budget, atomically.** The whole step is reserved in one
   capped conditional upsert keyed by the TREE ROOT id, so two pumps over one
   store can never jointly exceed it
   ([`boltrig/fleet/department_head.py:115`](../../../boltrig/fleet/department_head.py)
   `"if not await self._reserve_budget(work_item.tenant_id, tree, len(subtasks)):"`;
   [`boltrig/store/postgres.py:473`](../../../boltrig/store/postgres.py)
   `"INSERT INTO fanout_counters (tenant_id, tree_id, counter, value)"`).
   *Failure branch:* `spawn_budget_exhausted` escalation. With no store at all a
   per-process counter stands in
   ([`boltrig/fleet/department_head.py:164`](../../../boltrig/fleet/department_head.py)
   `"# storeless stub fallback: the old per-process counter (P9)"`).
6. **Run children bounded-parallel** under a semaphore of
   `max_children_per_step`; each child first gets a persisted IN_FLIGHT child
   `WorkItem` so the tree is visible, then the spawn
   ([`boltrig/fleet/department_head.py:128`](../../../boltrig/fleet/department_head.py)
   `"semaphore = asyncio.Semaphore(self.max_children_per_step)"`).
   *Failure branch:* an exception from `spawn` becomes a failed-child record
   with `degraded=True` and is never raised past the join
   ([`boltrig/fleet/department_head.py:191`](../../../boltrig/fleet/department_head.py)
   `"except Exception as exc:  # captured, never raised past the join (D8)"`). The
   child row is then FAILED only when `result["status"] == "error"`; every other
   status, including the budget `partial`, records DONE
   ([`boltrig/fleet/department_head.py:202`](../../../boltrig/fleet/department_head.py)
   `"child_item.status = ("`).
7. **Per-step discovery cap.** More than `max_new_items_per_step` (default 16)
   collected `new_work_items` escalates, carrying the children on the escalation
   ([`boltrig/fleet/department_head.py:138`](../../../boltrig/fleet/department_head.py)
   `"if len(new_items) > self.max_new_items_per_step:"`).
8. **Synthesis (NamedAgent only).** With a runtime, the peer runs one
   tool-enabled `run_agent_turn` over the children's evidence, wrapped in
   untrusted envelopes, and may call `agent.send` / `chat.present`; its text and
   summary overwrite the outcome's, its `new_work_items` append, and
   `degraded` becomes `result.degraded or not result.ok`
   ([`boltrig/fleet/named_agent.py:139`](../../../boltrig/fleet/named_agent.py)
   `"run_turn = getattr(self._runtime, \"run_agent_turn\", None)"`).
9. **Escalation shape.** `_escalate` files a `HITLType.ESCALATION` with
   `department_scope=[self.name]` and returns
   `{"status": "escalated", "reason", "detail", "hitl_request_id", "children": [],
   "new_work_items": []}`
   ([`boltrig/fleet/department_head.py:271`](../../../boltrig/fleet/department_head.py)
   `"\"\"\"Raise a HITL escalation for an over-cap step and return its record."`).

### 5.5 Whose authority a delegated run carries

1. `principal_grants_for_item` returns `EMPTY_GRANTS` when the item names no
   principal, the store cannot identify anyone, or the named principal has no
   user record; otherwise it mirrors the request path exactly through
   `effective_grants_for_request`
   ([`boltrig/fleet/authority.py:62`](../../../boltrig/fleet/authority.py)
   `"return EMPTY_GRANTS  # system-originated: no principal, so no authority"`).
2. The channel-thread ceiling and the creation-time creator ceiling are each
   intersected in, so a later promotion cannot widen already-queued work
   ([`boltrig/fleet/authority.py:113`](../../../boltrig/fleet/authority.py)
   `"grants = grants.intersect(ceiling)"`).
3. The TENANT ceiling is deliberately NOT folded in: it is a separate axis
   `GrantChecker` enforces on every dispatch, and folding it in would collapse a
   `{all: true}` principal under a narrow ceiling to no authority at all
   ([`boltrig/fleet/authority.py:98`](../../../boltrig/fleet/authority.py)
   `"The TENANT ceiling is deliberately not folded in here."`).
4. Post-run reflection does NOT ride the principal's authority. It carries a
   two-verb system seat, `memory.remember` and `memory.propose`, in the Chief of
   Staff's own memory scope
   ([`boltrig/fleet/authority.py:47`](../../../boltrig/fleet/authority.py)
   `"REFLECTION_GRANTS = GrantSet.of([\"memory.remember\", \"memory.propose\"])"`).

### 5.6 Follow-on work

`persist_new_work_items` reads the parent's existing children once, normalises
each payload, SKIPS one whose intent already exists among siblings, stamps
`parent_id`, `depth = parent.depth + 1`, `on_behalf_of`, `workspace_id` and the
inherited authority stamps, then creates it PENDING
([`boltrig/fleet/work_follow_ons.py:45`](../../../boltrig/fleet/work_follow_ons.py)
`"child.depth = parent.depth + 1"`). The module states its own limit: the
existing-intent check "is not a concurrency fence: closing the two-reader race
needs a database uniqueness constraint on `(parent_id, intent)`"
([`boltrig/fleet/work_follow_ons.py:21`](../../../boltrig/fleet/work_follow_ons.py)
`"not a concurrency fence: closing the two-reader race"`). A sibling-read failure is best-effort and never
blocks the follow-on.

### 5.7 How work enters

There are four distinct intake lanes and they do NOT converge before the
`Spawner`.

| Lane | Entry | Item status at creation | Reaches the pump? |
| --- | --- | --- | --- |
| **Channel intake** | `POST` inbound webhook -> `_terminal_or_work` normalises the body, stamps target, reply route, provenance, creator ceiling and thread ceiling, then `create_work_item`, returns `202` with the item id ([`boltrig/kernel/channel_inbound_routes.py:175`](../../../boltrig/kernel/channel_inbound_routes.py) `"item = normalise(body, source=channel.platform"`) | PENDING ([`boltrig/work/normalise.py:80`](../../../boltrig/work/normalise.py) `"status=WorkStatus.PENDING,"`) | YES |
| **Chat direct lane** | `_create_chat_item` creates the turn's own item, then `_spawn_turn` calls `Spawner.spawn` directly with `announce_child=False` ([`boltrig/fleet/chat_turn_execution.py:161`](../../../boltrig/fleet/chat_turn_execution.py) `"result = await spawner.spawn("`) | IN_FLIGHT, id == run id, NULL lease ([`boltrig/fleet/chat_turn_inputs.py:29`](../../../boltrig/fleet/chat_turn_inputs.py) `"status=WorkStatus.IN_FLIGHT,"`) | NO, by construction |
| **Chat / step follow-ons** | `persist_new_work_items` from a chat result (`source="chat"`) or a pump step (`source="internal"`) | PENDING | YES |
| **Direct HTTP spawn** | `POST /v1/spawn` -> `make_app_spawner` ([`boltrig/kernel/app.py:528`](../../../boltrig/kernel/app.py) `"@app.post(\"/v1/spawn\")"`) | no work item at all | NO |

Two further spawn doors exist that create no work item: the agent-bound verb
invoker used when a registry binding resolves a verb to an agent
([`boltrig/fleet/spawn_entrypoints.py:153`](../../../boltrig/fleet/spawn_entrypoints.py)
`"def make_agent_invoker("`), and the authoring/eval doors
(`skill.test_spawn`, `personal_agent.invoke`, the eval runner, Ultracode).
Complete inventory of `Spawner.spawn` callers in the tree: `chat_turn_execution`,
`department_head`, `eval`, `spawn_entrypoints`, `ultracode`,
`platform_routes/personal`, `platform_routes/skill_write_routes` (bounded:
`rg -n "\.spawn\(" --glob '!tests/**' --glob '!docs/**' .`, 2026-08-24, pinned tree).

### 5.8 The two carriages of the work-item body

`WorkPump.__init__` registers `_run_item_payload` under the name
`boltrig-work-item` on any executor exposing `register_task`
([`boltrig/fleet/pump.py:207`](../../../boltrig/fleet/pump.py)
`"register(WORK_ITEM_TASK, self._run_item_payload)"`). The Hatchet app registers
the same name as an engine task
([`boltrig/fleet/hatchet_app.py:333`](../../../boltrig/fleet/hatchet_app.py)
`"@hatchet.task(name=TASK_WORK_ITEM, input_validator=WorkItemInput)"`), whose body
forwards the payload to the same pump method
([`boltrig/fleet/hatchet_app.py:195`](../../../boltrig/fleet/hatchet_app.py)
`"await pump._run_item_payload(dict(payload))"`). Executor selection is honest and
optionally fail-closed
([`boltrig/fleet/workers.py:201`](../../../boltrig/fleet/workers.py)
`"def register_workers("`).

---

## 6. Data

### 6.1 Tables this subsystem owns or writes

**`work_items`** (PK `(tenant_id, id)`) carries every field of the `WorkItem`
dataclass plus `created_at`/`updated_at`
([`boltrig/store/schema.sql:392`](../../../boltrig/store/schema.sql)
`"CREATE TABLE IF NOT EXISTS work_items ("`). Indexes:
`(tenant_id, status)`, `(tenant_id, workspace_id)`, `(parent_id)`,
`(tenant_id, hatchet_run_id)`, and the claim index
`(tenant_id, status, lease_expires_at)`
([`boltrig/store/schema.sql:432`](../../../boltrig/store/schema.sql)
`"CREATE INDEX IF NOT EXISTS work_items_lease_idx"`). `constraints` and `raw` and
`result` are JSONB. No retention or purge job touches this table
(bounded: `rg -n "work_items" boltrig/fleet/retention.py boltrig/kernel/`, 2026-08-24,
pinned tree; `retention.py` erases conversations only,
[`boltrig/fleet/retention.py:1`](../../../boltrig/fleet/retention.py)
`"Retention purge: hard-erasure of closed conversations"`).

**`run_checkpoints`** (PK `(tenant_id, run_id, step)`) is the resume seam. The
pump writes exactly two step names: `route` and `execute`, with statuses
`started | done | awaiting_human | failed | cancelled`
([`boltrig/store/schema.sql:435`](../../../boltrig/store/schema.sql)
`"CREATE TABLE IF NOT EXISTS run_checkpoints ("`).

**`fanout_counters`** (PK `(tenant_id, tree_id, counter)`) holds the shared
per-tree spawn budget. The only counter name the fleet writes is `"spawned"`
([`boltrig/fleet/department_head.py:162`](../../../boltrig/fleet/department_head.py)
`"tenant_id, tree_id, \"spawned\", n, self.spawn_budget"`). The only operation is
the capped increment: there is no decrement, no reset and no purge (bounded:
`rg -n "fanout" boltrig/store/ boltrig/fleet/`, 2026-08-24, pinned tree).

**`run_cancel_requests`** (PK `(tenant_id, run_id)`) is the cooperative cancel
marker the pump consults at three boundaries
([`boltrig/store/schema.sql:462`](../../../boltrig/store/schema.sql)
`"CREATE TABLE IF NOT EXISTS run_cancel_requests ("`).

**`budgets`** + **`budget_usage`**. Policy lives on `budgets`
(`scope_type` in `tenant | department | workflow`, `token_limit`,
`cost_limit_micros`, `hard_stop`, `window` in `run | daily | monthly`); live
usage lives on `budget_usage`, keyed `(tenant_id, scope_id, window_key)` with a
`reset_generation` and CHECK constraints flooring both accumulators at zero
([`boltrig/store/schema.sql:688`](../../../boltrig/store/schema.sql)
`"CREATE TABLE IF NOT EXISTS budget_usage ("`). The `spent_tokens` /
`spent_micros` columns on `budgets` are marked legacy in the schema itself.

**`audit_events`** receives one `AGENT_SPAWN` row per spawn, one `MODEL_CALL`
row per permanent phase, one `TOOL_CALL` row per addressed-workflow trigger and
one per cancel transition.

RLS covers `run_checkpoints` and `fanout_counters`
([`boltrig/store/rls.sql:110`](../../../boltrig/store/rls.sql)
`"'run_checkpoints','fanout_counters',"`).

### 6.2 Migrations

`migrations/versions/0005_durable_delegation.py` creates `fanout_counters`
([`migrations/versions/0005_durable_delegation.py:41`](../../../migrations/versions/0005_durable_delegation.py)
`"CREATE TABLE IF NOT EXISTS fanout_counters ("`);
`0007_run_cancellation.py` adds the cancel marker and defers its RLS policy to
`rls.sql` ([`migrations/versions/0007_run_cancellation.py:39`](../../../migrations/versions/0007_run_cancellation.py)
`"(run_checkpoints, fanout_counters) get their policy"`). The `work_items` lease
columns are added idempotently in `schema.sql` for pre-Beat-3 databases
([`boltrig/store/schema.sql:426`](../../../boltrig/store/schema.sql)
`"ALTER TABLE work_items ADD COLUMN IF NOT EXISTS lease_owner TEXT;"`).

### 6.3 Encryption and redaction

Nothing in this subsystem is encrypted at rest by the fleet itself. Two
deliberate content bounds apply: a FAILED item's `result["detail"]` has URLs
redacted and is truncated to 200 characters, because transport errors embed
DSNs and internal hosts and a FAILED result is caller-visible
([`boltrig/fleet/pump.py:112`](../../../boltrig/fleet/pump.py) `"return _URL_RE.sub(\"[url]\", str(exc))[:_MAX_ERROR_DETAIL]"`); and the public
model route on an audit row and a spawn result is filtered to six keys, each
truncated to 160 characters
([`boltrig/fleet/spawn_completion.py:13`](../../../boltrig/fleet/spawn_completion.py)
`"_PUBLIC_ROUTE_KEYS = {"`).

---

## 7. Configuration surface

### 7.1 Manifest keys

| Key | Default | Effect | What breaks if wrong |
| --- | --- | --- | --- |
| `agents.named[]` | none; at least one required | The whole serving roster ([`boltrig/config/manifest_agents.py:34`](../../../boltrig/config/manifest_agents.py) `"agents.named must declare at least one named agent"`) | An empty list raises at parse; the worker logs "manifest load failed" and degrades to the ONE-agent default org named `general` ([`boltrig/fleet/org_builder.py:36`](../../../boltrig/fleet/org_builder.py) `"roster = (NamedAgentConfig(name=\"general\", address=\"general\", runtime=\"script\")"`) |
| `agents.default` | first declared address | Receives unaddressed intake ([`boltrig/config/manifest_agents.py:36`](../../../boltrig/config/manifest_agents.py) `"default=str(raw.get(\"default\") or members[0].address)"`) | A roster with no resolvable default parks every unaddressed item |
| `agents.named[].address` | the `name` | The routing key AND the ephemeral children's budget department scope | Must match `[a-z0-9][a-z0-9_-]{0,62}` or parse fails |
| `agents.named[].scope_id` | None | The permanent runtime's budget scope AND the seeded department budget id | A `scope_id` that differs from `address` splits the peer's own spend from its children's spend into two scopes (see RISKS) |
| `agents.named[].max_depth` | 3, bounded 1..5 | The peer's own phase depth ceiling | Out of range raises at parse |
| `agents.named[].runtime` | `codex` | Restricted to `{codex, script, python-script}` | Anything else raises at parse |
| `agents.named[].budget` | none | Seeded as a `tenant` scope when the agent IS the default and has no `scope_id`, otherwise as a `department` scope ([`boltrig/config/manifest_apply.py:58`](../../../boltrig/config/manifest_apply.py) `"tenant_budget = agent.address == roster.default and agent.scope_id is None"`) | No budget row means the scope is UNMETERED, not refused |
| `ephemeral_runtimes[]` | none | The `AgentCapability` rows `select_capability` chooses among; `max_depth` default 2, `cost_tier` default `cheap` ([`boltrig/config/manifest.py:180`](../../../boltrig/config/manifest.py) `"max_depth: int = 2"`) | No capable row raises `NoCapableRuntime` (404) on every spawn |
| `spawn_rules[]` | `()` | Closed policy: <=128 rules, priority 0..1000, <=32 tags, <=32 skills, depth 1..10 ([`boltrig/config/spawn_rules.py:23`](../../../boltrig/config/spawn_rules.py) `"_MAX_RULES = 128"`) | Any schema violation rejects the WHOLE policy; equal-priority ties fail closed at selection time |
| `models.sensitive_endpoint` | None | The local-only routing role handed to `RuntimeResolver` | `None` keeps the router fail-closed: sensitive work is refused rather than escaping ([`boltrig/fleet/spawn.py:545`](../../../boltrig/fleet/spawn.py) `"None keeps"`) |
| `models.prices` | `{}` | Per-model micros-per-token, scalar or `{input, output}` | Empty means every model falls back to its tier default: cheap 1, standard 5, expensive 25 ([`boltrig/kernel/cost.py:47`](../../../boltrig/kernel/cost.py) `"_TIER_MICROS_PER_TOKEN: dict[str, int] = {\"cheap\": 1, \"standard\": 5, \"expensive\": 25}"`) |
| `hierarchy.tier1` / `hierarchy.tier2[]` | none | MIGRATION INPUT ONLY; normalised into the flat roster | An old manifest keeps working; nothing reconstructs Chief/Department authority |

### 7.2 Environment variables

| Variable | Default | Effect | What breaks |
| --- | --- | --- | --- |
| `BOLTRIG_REQUIRE_DURABLE` | unset | Truthy turns any durable-engine failure into a boot refusal instead of a silent local fallback ([`boltrig/fleet/workers.py:198`](../../../boltrig/fleet/workers.py) `"return is_truthy(os.environ.get(\"BOLTRIG_REQUIRE_DURABLE\"))"`) | Unset in production means work runs on a NON-durable in-process executor that does not survive a restart |
| `BOLTRIG_REFLECT` | unset (OFF) | `=="1"` enables post-run reflection, the only automatic memory writer in the stack ([`boltrig/fleet/pump.py:165`](../../../boltrig/fleet/pump.py) `"reflect if reflect is not None else os.getenv(\"BOLTRIG_REFLECT\") == \"1\""`) | Off means terminal work items record no lesson and no episode; compose documents the measured consequence ([`docker-compose.yml:281`](../../../docker-compose.yml) `"BOLTRIG_REFLECT: ${BOLTRIG_REFLECT:-}"`) |
| `BOLTRIG_MODEL_GATEWAY_URL` | None | The conversation gateway base url used by `apply_conversation_gateway` ([`boltrig/fleet/model_gateway.py:108`](../../../boltrig/fleet/model_gateway.py) `"\"base_url\": os.environ.get(\"BOLTRIG_MODEL_GATEWAY_URL\") or None"`) | None disables gateway binding |
| `BOLTRIG_MODEL_GATEWAY_TTL` | `900` | Gateway binding cache TTL in seconds | A non-integer raises at import of `gateway_config()` |
| `BOLTRIG_CODEX_MCP_URL` / `BOLTRIG_MCP_URL` | `http://kernel:8000/v1/mcp` | Where a kernel-tools Codex cell reaches the MCP face ([`boltrig/fleet/runtime_resolver.py:374`](../../../boltrig/fleet/runtime_resolver.py) `"os.environ.get(\"BOLTRIG_CODEX_MCP_URL\")"`) | A wrong value silently gives the cell no working tools |
| `HOSTNAME` | `fleet-worker` | The worker identity recorded in the permanent-fleet startup observation | Cosmetic |

### 7.3 Constants that behave like configuration but are NOT settable

These are hard-coded and have no manifest key or env var
(bounded: `rg -n "os.environ|os.getenv" boltrig/fleet/pump*.py boltrig/fleet/department_head.py boltrig/fleet/named_agent.py boltrig/api/worker.py`,
2026-08-24, pinned tree).

| Constant | Value | Where |
| --- | --- | --- |
| `DEFAULT_MAX_ATTEMPTS` | 3 | [`boltrig/fleet/pump_policy.py:3`](../../../boltrig/fleet/pump_policy.py) `"DEFAULT_MAX_ATTEMPTS = 3"` |
| `DEFAULT_LEASE_SECONDS` | 300 | [`boltrig/fleet/pump_policy.py:4`](../../../boltrig/fleet/pump_policy.py) `"DEFAULT_LEASE_SECONDS = 300"` |
| `DEFAULT_SPAWN_BUDGET` | 32 per tree | [`boltrig/fleet/pump_policy.py:5`](../../../boltrig/fleet/pump_policy.py) `"DEFAULT_SPAWN_BUDGET = 32"` |
| `max_children_per_step` | 8 | [`boltrig/fleet/department_head.py:66`](../../../boltrig/fleet/department_head.py) `"max_children_per_step: int = 8,"` |
| `max_new_items_per_step` | 16 | [`boltrig/fleet/department_head.py:67`](../../../boltrig/fleet/department_head.py) `"max_new_items_per_step: int = 16,"` |
| worker poll interval | 5.0s | [`boltrig/api/worker.py:61`](../../../boltrig/api/worker.py) `"_POLL_SECONDS = 5.0"` |
| throughput window | `max(interval * 10, 60)` seconds | [`boltrig/fleet/pump_progress.py:45`](../../../boltrig/fleet/pump_progress.py) `"return max(float(interval) * CYCLES_PER_WINDOW, MIN_WINDOW_SECONDS)"` |
| budget alert fraction | 0.8 | [`boltrig/kernel/cost.py:41`](../../../boltrig/kernel/cost.py) `"_ALERT_FRACTION = 0.8  # pre-emptive alert threshold"` |
| estimate ratio | 4 chars per token, floor 16 | [`boltrig/fleet/spawn_budget.py:18`](../../../boltrig/fleet/spawn_budget.py) `"tokens = max(16, chars // 4)"` |

The pump's own module says so: "the manifest carries no pump policy section yet;
these are the documented defaults until one exists"
([`boltrig/fleet/pump.py:61`](../../../boltrig/fleet/pump.py)
`"the manifest carries no pump policy section yet"`).

---

## 8. PROCESS

### 8.1 Bringing the fleet up

1. The serving process is `python -m boltrig.api.worker`, run as the compose
   service `fleet-worker`
   ([`docker-compose.yml:230`](../../../docker-compose.yml)
   `"command: [\"python\", \"-m\", \"boltrig.api.worker\"]"`).
2. `_run` composes the process model runtime, builds the kernel, selects the
   executor, overlays the manifest with any governed desired state, builds the
   spawner and the org, publishes the birth profile, starts the janitors, and
   then enters `pump.run_forever(tenant, interval=5.0)`
   ([`boltrig/api/worker.py:429`](../../../boltrig/api/worker.py)
   `"await pump.run_forever(tenant, interval=_POLL_SECONDS)"`).
3. The boot log states the executor and its durability honestly
   ([`boltrig/api/worker.py:385`](../../../boltrig/api/worker.py) `"\"fleet worker started (%s, durable=%s)\","`) and then the live org
   ([`boltrig/api/worker.py:423`](../../../boltrig/api/worker.py)
   `"\"delegation pump live (tenant=%s, departments=%s)\","`).
4. Two container prerequisites are recorded in compose as prior incidents: the
   worker needs the same `codex-cells` tmpfs the kernel declares or it
   crash-loops on the sandbox probe, and it needs
   `BOLTRIG_KNOWLEDGE_VAULT` on a read-only rootfs
   ([`docker-compose.yml:245`](../../../docker-compose.yml)
   `"tmpfs:"` with the `codex-cells` line;
   [`docker-compose.yml:291`](../../../docker-compose.yml)
   `"BOLTRIG_KNOWLEDGE_VAULT: ${BOLTRIG_KNOWLEDGE_VAULT:-/var/lib/boltrig/knowledge}"`).
5. `manifest.yaml` and `libraries/` are bind-mounted read-only; a manifest edit
   requires a restart of this service to take effect on the roster, because
   `build_org` runs once at boot
   ([`docker-compose.yml:293`](../../../docker-compose.yml)
   `"- ./manifest.yaml:/app/manifest.yaml:ro"`).

### 8.2 Changing the org

- Editing `agents.named` is a manifest edit plus a restart of `fleet-worker`.
  The only live-reload seam in this subsystem is `ChiefOfStaff`'s
  `departments_provider`, which belongs to the legacy topology that
  `build_org` never composes
  ([`boltrig/fleet/chief_of_staff.py:65`](../../../boltrig/fleet/chief_of_staff.py)
  `"self._departments_provider = departments_provider"`).
- Spawn rules ARE live: `prepare_spawn_intake` re-reads the latest persisted
  revision on every spawn, so a governed `spawn_rules` update takes effect on
  the next call with no restart
  ([`boltrig/fleet/spawn_policy.py:83`](../../../boltrig/fleet/spawn_policy.py)
  `"rules = await _effective_rules(store, tenant_id, base_rules)"`). Operators
  can dry-run a policy before committing it via
  `POST /v1/spawn-rules/simulate`
  ([`boltrig/kernel/platform_routes/spawn_rules.py:92`](../../../boltrig/kernel/platform_routes/spawn_rules.py)
  `"@app.post(\"/v1/spawn-rules/simulate\")"`), and
  `spawn_rule_conflicts` enumerates every reachable top-priority tie with a
  deterministic example
  ([`boltrig/config/spawn_rules.py:280`](../../../boltrig/config/spawn_rules.py)
  `"def spawn_rule_conflicts("`).
- Capability rows can also be added out-of-band through
  `control.capability.upsert`; those rows carry `source="control-plane"` and a
  manifest apply never touches them
  ([`boltrig/models/libraries.py:115`](../../../boltrig/models/libraries.py)
  `"source: str = \"control-plane\"  # manifest | control-plane"`).

### 8.3 Recovering a stuck item

1. **Diagnose the state.** `GET /v1/work` lists items; the two checkpoint step
   names (`route`, `execute`) say how far the last attempt got.
2. **AWAITING_HUMAN.** Answer the HITL. The answer bridge calls
   `WorkPump.requeue`, which returns the item to PENDING and RESETS `attempts`
   to zero ([`boltrig/fleet/pump.py:481`](../../../boltrig/fleet/pump.py)
   `"item.attempts = 0"`). An operator or the console may call it directly. This
   write is deliberately UNFENCED, on the stated ground that a human re-queue is
   an authorised reset that overrides whatever the last attempt left behind
   ([`boltrig/fleet/pump.py:466`](../../../boltrig/fleet/pump.py)
   `"D3 disposal: this write is deliberately NOT lease-fenced"`).
3. **FAILED.** `requeue` refuses it: the guard admits only AWAITING_HUMAN and
   BLOCKED ([`boltrig/fleet/pump.py:475`](../../../boltrig/fleet/pump.py)
   `"if item is None or item.status not in ("`). A FAILED item must be moved
   through the governed `control.work` transition path instead, which permits
   `FAILED -> PENDING`.
4. **Stuck IN_FLIGHT.** Nothing renews a lease. After `lease_seconds` (300) the
   row becomes claimable again by any worker, and the losing worker's write is
   refused by the fence
   ([`boltrig/fleet/lease_token.py:5`](../../../boltrig/fleet/lease_token.py)
   `"Two workers can hold the same work item."`).
5. **Cancel.** `POST` the cancel request; the pump settles CANCELLED at the next
   cooperative boundary, idempotently, and emits one `work.cancel` audit row
   ([`boltrig/fleet/pump.py:600`](../../../boltrig/fleet/pump.py)
   `"async def _cancel(self, item: WorkItem, run_id: str)"`).

### 8.4 Diagnosing whether the pump is alive

The pump publishes a FACT, not a verdict: one `pump` background-attempt receipt
per window carrying `item_count` and `succeeded`
([`boltrig/fleet/pump_progress.py:126`](../../../boltrig/fleet/pump_progress.py)
`"await record_background_attempt("`). The module explains why it cannot honestly
say STALLED: `claim_work_item` returning `None` covers four different situations
and the claimable predicate lives inside the SQL
([`boltrig/fleet/pump_progress.py:6`](../../../boltrig/fleet/pump_progress.py)
`"``claim_work_item`` returning None covers"`). Reflection publishes its own
`reflection` receipt only when the feature is on, which is what makes
idle / broken / off distinguishable
([`boltrig/fleet/pump_progress.py:145`](../../../boltrig/fleet/pump_progress.py) `"job_name=\"reflection\","`).

### 8.5 Gates that bind changes to this subsystem

`make check` runs invariants, ruff, architecture, structure, reachability,
typecheck and pytest, and its own help text says it is NOT what CI enforces
([`Makefile:223`](../../../Makefile) `"check: invariants lint architecture"`).
`make python-quality` is the pre-push gate
([`Makefile:228`](../../../Makefile) `"python-quality: invariants lint architecture"`).
Three of its targets bear directly on this area: `unwired-claims` ("Fail when
the record names a mechanism no production path constructs",
[`Makefile:136`](../../../Makefile)), `reachability`
([`Makefile:139`](../../../Makefile)) and `structure` (file and function size
ratchets, which is why `pump.py` sheds code into `pump_progress.py` and
`reflection.py`, [`Makefile:124`](../../../Makefile)).

---

## 9. Failure modes and fail-open / fail-closed posture

| Guard | Direction | Proof |
| --- | --- | --- |
| Spawn-rule policy unreadable or invalid | **FAIL-CLOSED.** Raises `SpawnRulePolicyInvalid`; there is no empty-rule-set fallback | [`boltrig/fleet/spawn_policy.py:61`](../../../boltrig/fleet/spawn_policy.py) `"except Exception as exc:"` then `raise SpawnRulePolicyInvalid` |
| Equal-priority spawn-rule tie | **FAIL-CLOSED.** Raises rather than picking by list order | [`boltrig/config/spawn_rules.py:275`](../../../boltrig/config/spawn_rules.py) `"spawn rules tie at priority"` |
| No capable capability | **FAIL-CLOSED.** `NoCapableRuntime` 404 | [`boltrig/fleet/spawn_skills.py:156`](../../../boltrig/fleet/spawn_skills.py) `"raise NoCapableRuntime("` |
| Skill context requirements unmet | **FAIL-CLOSED.** `ContextRequirementsUnmet` | [`boltrig/fleet/spawn_policy.py:100`](../../../boltrig/fleet/spawn_policy.py) `"raise ContextRequirementsUnmet("` |
| Recursion depth exceeded | **FAIL-CLOSED where reached.** `DepthExceeded` raises out of intake; on the permanent-profile path it DEGRADES instead of raising | [`boltrig/fleet/spawn_policy.py:125`](../../../boltrig/fleet/spawn_policy.py) `"raise DepthExceeded("` vs [`boltrig/fleet/permanent_runtime.py:207`](../../../boltrig/fleet/permanent_runtime.py) `"elif context.depth > self.capability.max_depth:"` |
| Budget hard stop at reservation | **FAIL-CLOSED but caller-selectable shape.** `partial_on_budget=False` re-raises `BudgetExceeded`; `True` (the default at every fleet and chat call site) returns a degraded `partial` envelope and the run is skipped | [`boltrig/fleet/spawn_reservation.py:48`](../../../boltrig/fleet/spawn_reservation.py) `"if not partial_on_budget:"` |
| Budget exhausted MID-run | **NOT ENFORCED.** There is no mid-run check. `reconcile` explicitly never re-checks the hard stop: "it corrects the record of a call that already ran, it does not gate a new one" | [`boltrig/kernel/cost.py:344`](../../../boltrig/kernel/cost.py) `"Unlike ``reserve`` this never re-checks the hard stop"` |
| Multi-scope reservation partial debit | **FAIL-CLOSED.** One transaction locks every scope FOR UPDATE and debits all or none; `None` back means refuse | [`boltrig/kernel/cost.py:316`](../../../boltrig/kernel/cost.py) `"windows = await self._store.reserve_budgets_atomic("` |
| Budget alert callback raises | **FAIL-SAFE (P9).** Swallowed at debug; never aborts a metered reservation | [`boltrig/kernel/cost.py:302`](../../../boltrig/kernel/cost.py) `"except Exception:  # alert side-channel must never break reserve (P9)"` |
| Runtime raises after reservation | **REFUND.** Full estimate refunded, subagent frame settled `error`, credentials retired, exception re-raised | [`boltrig/fleet/spawn.py:256`](../../../boltrig/fleet/spawn.py) `"with contextlib.suppress(Exception):"` |
| Child spawn raises inside a step | **FAIL-SOFT, HONESTLY.** Captured as a failed-child record with `degraded=True`, never raised past the join | [`boltrig/fleet/department_head.py:191`](../../../boltrig/fleet/department_head.py) `"except Exception as exc:  # captured, never raised past the join (D8)"` |
| Per-step fan-out / discovery cap breach | **FAIL-CLOSED to a human.** HITL escalation, no over-cap spawn | [`boltrig/fleet/department_head.py:106`](../../../boltrig/fleet/department_head.py) `"return await self._escalate("` |
| Per-tree spawn budget | **FAIL-CLOSED, atomically, cross-worker.** The conditional upsert applies the whole increment or none | [`boltrig/store/postgres.py:477`](../../../boltrig/store/postgres.py) `"WHERE fanout_counters.value + EXCLUDED.value <= $5"` |
| Unroutable item | **FAIL-CLOSED to a human.** Parked AWAITING_HUMAN with a HITL, never executed under an arbitrary fallback | [`boltrig/fleet/pump.py:339`](../../../boltrig/fleet/pump.py) `"await self._park("` |
| Unknown addressed workflow | **FAIL-CLOSED to a human.** Parked, never falling through to agent routing | [`boltrig/fleet/pump.py:386`](../../../boltrig/fleet/pump.py) `"reason=\"unknown_workflow\","` |
| Work item names no principal | **FAIL-CLOSED to `EMPTY_GRANTS`.** An unidentified principal is not a tenant-wide principal | [`boltrig/fleet/authority.py:61`](../../../boltrig/fleet/authority.py) `"if not item.on_behalf_of:"` |
| Lease lost during a step | **FAIL-CLOSED on the RECORD, not on execution.** The write is refused with a warning, never an exception, because raising would reach `_record_failure` and re-open an item the winner settled. The module states the honest limit: this does not make execution exactly-once | [`boltrig/fleet/lease_token.py:143`](../../../boltrig/fleet/lease_token.py) `"if not wrote:"`; [`boltrig/fleet/lease_token.py:30`](../../../boltrig/fleet/lease_token.py) `"D9, the honest limit"` |
| Payload with no lease token | **FAIL-OPEN, DECLARED.** The write goes through unfenced and logs that it did, so a rolling restart does not strand in-flight older payloads | [`boltrig/fleet/lease_token.py:134`](../../../boltrig/fleet/lease_token.py) `"unfenced work-item write (%s) for item %s"` |
| Fault after the terminal write | **FAIL-CLOSED against re-execution.** A settled row is never re-opened; the fault is logged | [`boltrig/fleet/pump.py:535`](../../../boltrig/fleet/pump.py) `"work item %s faulted after settling as %s; not re-opening it"` |
| Cancel racing a failure record | **CANCEL WINS.** `_record_failure` re-checks the marker first and calls the idempotent `_cancel` | [`boltrig/fleet/pump.py:521`](../../../boltrig/fleet/pump.py) `"if await self._store.is_run_cancel_requested(item.tenant_id, run_id):"` |
| Retry exhausted | **FAIL-CLOSED to FAILED with a redacted error**, then one reflection and one terminal notify | [`boltrig/fleet/pump.py:541`](../../../boltrig/fleet/pump.py) `"will_retry = item.attempts < self.max_attempts"` |
| Convergent item with a degraded aggregate | **FAIL-CLOSED to a human.** Never DONE | [`boltrig/fleet/pump.py:431`](../../../boltrig/fleet/pump.py) `"if item.convergent and item.degraded:"` |
| Unregistered durable task name | **FAIL-CLOSED.** `KeyError` on both executors, deliberately mirrored | [`boltrig/fleet/workers.py:178`](../../../boltrig/fleet/workers.py) `"wf = self.workflows[task_name]  # KeyError = unregistered task, fail-closed"` |
| Hatchet work-item task with no pump | **FAIL-CLOSED.** Raises rather than silently dropping | [`boltrig/fleet/hatchet_app.py:337`](../../../boltrig/fleet/hatchet_app.py) `"raise RuntimeError(\"no pump wired for boltrig-work-item\")"` |
| Durable engine unavailable | **FAIL-OPEN BY DEFAULT.** Falls back to a NON-durable in-process executor unless `BOLTRIG_REQUIRE_DURABLE` is set | [`boltrig/fleet/workers.py:239`](../../../boltrig/fleet/workers.py) `"def _fallback_or_raise(reason: str, exc: Exception)"` |
| Manifest load failure | **FAIL-OPEN to a one-agent default org.** Logged as a warning | [`boltrig/api/worker.py:285`](../../../boltrig/api/worker.py) `"log.warning(\"manifest load failed (%s); using the default org\", exc)"` |
| Pump cycle raises | **FAIL-SAFE (P9).** Logged, counted as a window failure, loop continues | [`boltrig/fleet/pump_progress.py:118`](../../../boltrig/fleet/pump_progress.py) `"except Exception:  # a bad cycle never kills the pump (P9)"` |
| Reflection fails | **FAIL-SAFE, LOUDLY.** Swallowed at WARNING (deliberately not DEBUG) and counted | [`boltrig/fleet/reflection.py:120`](../../../boltrig/fleet/reflection.py) `"except Exception:  # reflection is best-effort; never fail the run (P9)"` |
| Subagent relay publish fails | **FAIL-SAFE.** Both the open and the settle frame swallow | [`boltrig/fleet/spawn.py:358`](../../../boltrig/fleet/spawn.py) `"except Exception:"` |
| Child credential sweep fails | **FAIL-SAFE.** Logged; hygiene never fails a spawn | [`boltrig/fleet/spawn.py:327`](../../../boltrig/fleet/spawn.py) `"except Exception:  # noqa: BLE001 - a sweep fault is the pre-existing leak"` |
| Terminal notify or credential sweep fails | **FAIL-SAFE.** Never changes the item's outcome | [`boltrig/fleet/pump.py:651`](../../../boltrig/fleet/pump.py) `"log.warning(\"terminal notify failed for item %s\", item.id, exc_info=True)"` |
| Named-agent turn heartbeat lost | **FAIL-CLOSED after the body.** `AgentTurnLeaseLost` is raised on exit | [`boltrig/fleet/agent_turns.py:88`](../../../boltrig/fleet/agent_turns.py) `"raise AgentTurnLeaseLost(\"named agent turn lease was lost\")"` |
| Chief of Staff routing runtime fails | **FAIL-SAFE to deterministic routing** (legacy lane only) | [`boltrig/fleet/chief_of_staff.py:113`](../../../boltrig/fleet/chief_of_staff.py) `"except Exception:  # routing must never crash the loop (P9)"` |

### 9.1 What actually happens when budget is exhausted mid-run

This was asked explicitly, so it is stated as a sequence rather than a table row.

1. **There is no mid-run budget check anywhere in the tree.** The only calls to
   `CostAccountant.reserve` are the three pre-run boundaries: `Spawner.spawn`,
   the agent-bound verb invoker, and a permanent profile phase (bounded:
   `rg -n "cost\.reserve\(" --glob '!tests/**' --glob '!docs/**' .`, 2026-08-24,
   pinned tree: three hits, all pre-run).
2. A run that overspends its estimate therefore RUNS TO COMPLETION. The overage
   is discovered only at `_true_up_cost`, which applies the signed delta and
   returns the real priced figure
   ([`boltrig/fleet/spawn.py:397`](../../../boltrig/fleet/spawn.py)
   `"await self._kernel.cost.reconcile("`).
3. `reconcile` never re-checks the hard stop and never alerts. The store floors
   each accumulator at zero, so a full refund cannot drive the ledger negative,
   but nothing stops an overspend being recorded past the ceiling
   ([`boltrig/kernel/cost.py:344`](../../../boltrig/kernel/cost.py)
   `"Unlike ``reserve`` this never re-checks the hard stop or alerts"`).
4. **The NEXT reservation is what refuses.** The following spawn on that scope
   sees the raised `spent_micros` and raises `BudgetExceeded` at step 1 of
   `reserve` ([`boltrig/kernel/cost.py:286`](../../../boltrig/kernel/cost.py)
   `"raise BudgetExceeded("`).
5. **What the caller then sees depends on `partial_on_budget`.** Every fleet and
   chat call site passes `True`, so the caller gets
   `{"status": "partial", "degraded": True, "reason": "budget_exceeded",
   "summary": "spawn skipped: budget hard-stop reached", "tokens_used": 0,
   "cost_micros": 0}` and an `AGENT_SPAWN` audit row with
   `status="budget_exceeded"`
   ([`boltrig/fleet/spawn.py:520`](../../../boltrig/fleet/spawn.py) `"\"reason\": \"budget_exceeded\","`). `POST /v1/spawn` and Ultracode pass
   `False` and get the raise
   ([`boltrig/fleet/spawn_entrypoints.py:76`](../../../boltrig/fleet/spawn_entrypoints.py)
   `"partial_on_budget=False,"`).
6. **Inside a delegated step the partial becomes a DONE child.** `_run_child`
   marks the child work item FAILED only when `result["status"] == "error"`;
   `"partial"` is not that, so a budget-skipped child is persisted DONE with
   `degraded=True`
   ([`boltrig/fleet/department_head.py:202`](../../../boltrig/fleet/department_head.py)
   `"child_item.status = ("`).
7. **The parent then depends on `convergent`.** The join sets
   `item.degraded=True`; a convergent item parks AWAITING_HUMAN, a divergent one
   reaches DONE carrying `degraded=True` and an outcome score of 0.5
   ([`boltrig/fleet/pump.py:125`](../../../boltrig/fleet/pump.py) `"score: float | None = 0.5 if degraded else 1.0"`).
8. **A permanent profile phase degrades rather than raising**, writing a
   `MODEL_CALL` audit row with `status="budget_exceeded"` and returning a
   degraded `AgentResult`
   ([`boltrig/fleet/permanent_runtime.py:235`](../../../boltrig/fleet/permanent_runtime.py) `"async def _budget_denied("`).

---

## 10. What is proven

Invariants in `tests/invariants.yaml` that bind this subsystem:

| Invariant | What it pins | Where |
| --- | --- | --- |
| `FLT-PEER-01` | The live serving composition is a flat tier-1 roster; the declared default only receives unaddressed intake; unknown addresses park; the old Chief/Department shape is a migration input only | [`tests/invariants.yaml:2741`](../../../tests/invariants.yaml) `"Live serving composition is a flat roster"` |
| `FLT-PEER-02` | Ephemerals are task-scoped leaves with no registry row, no mailbox and no unspoofable sender | [`tests/invariants.yaml:2748`](../../../tests/invariants.yaml) `"Ephemeral workers are task-scoped leaves, not identities"` |
| `US-FLT-04` | Preferred capability when requested, otherwise the cheapest capable runtime | [`tests/invariants.yaml:440`](../../../tests/invariants.yaml) `"otherwise the cheapest capable runtime"` |
| `US-FLT-05` | Exactly-once claim, reclaimable expired lease, and the claim-time lease fence on both stores | [`tests/invariants.yaml:445`](../../../tests/invariants.yaml) `"A pending work item is claimed exactly once"` |
| `US-FLT-06` | A filed item completes through the org with checkpoints and an audited spawn | [`tests/invariants.yaml:460`](../../../tests/invariants.yaml) `"A filed work item completes through the org"` |
| `US-FLT-07` | Degraded is first-class end to end; a convergent degraded aggregate parks | [`tests/invariants.yaml:465`](../../../tests/invariants.yaml) `"Degraded results are first-class"` |
| `US-EXE-05` | Executor selection is honest and optionally fail-closed | [`tests/invariants.yaml:474`](../../../tests/invariants.yaml) `"Executor selection is honest and optionally fail-closed"` |
| `US-EXE-06` | Retries capped, then FAILED with the error recorded; cap-breach escalates | [`tests/invariants.yaml:480`](../../../tests/invariants.yaml) `"Retries are capped"` |
| `US-EXE-07` | Fan-out caps enforced by atomic store-backed counters shared across workers | [`tests/invariants.yaml:485`](../../../tests/invariants.yaml) `"Fan-out caps are enforced by atomic store-backed counters"` |
| `FR-EXE-03` | Recursion depth is bounded: a spawn past the capability max depth is refused | [`tests/invariants.yaml:783`](../../../tests/invariants.yaml) `"Recursion depth is bounded"` |
| `FR-EXE-06` | Task bodies re-enter the chokepoint; a tenant mismatch is refused | [`tests/invariants.yaml:752`](../../../tests/invariants.yaml) `"Task bodies re-enter the chokepoint"` |
| `SEC-147` | Every legacy spawn path intersects selected-skill tool grants with the parent context even with no extra ceiling | [`tests/invariants.yaml:77`](../../../tests/invariants.yaml) `"SEC-147:"` |
| `SEC-164` | The delegated lane executes at the requesting principal's authority, with the creation-time ceiling intersected | [`tests/invariants.yaml:2121`](../../../tests/invariants.yaml) `"SEC-164:"` |
| `SEC-165` | Pump routing fails closed: an unroutable item parks | [`tests/invariants.yaml:2135`](../../../tests/invariants.yaml) `"SEC-165:"` |
| `SEC-166` | Cancel boundary 2: no new domain effect BEGINS after revocation | [`tests/invariants.yaml:2141`](../../../tests/invariants.yaml) `"SEC-166:"` |
| `SEC-178` | Channel addressing is routing data, not authority; a `workflow:` target is honoured first and an unknown one parks | [`tests/invariants.yaml:274`](../../../tests/invariants.yaml) `"SEC-178:"` |
| `SEC-WRK-27` | The permanent-fleet authoring surface is a closed compatibility bridge; `build_org` normalises rather than reconstructing Chief/Department authority | [`tests/invariants.yaml:2716`](../../../tests/invariants.yaml) `"SEC-WRK-27:"` |
| `REL-AGENT-01` | A per-identity turn lease serializes named-agent turns across workers | [`tests/invariants.yaml:2755`](../../../tests/invariants.yaml) `"REL-AGENT-01:"` |
| `FR-COST-02` | Hard stop halts before exceeding; run windows fail closed without an exact run id | [`tests/invariants.yaml:952`](../../../tests/invariants.yaml) `"FR-COST-02:"` |
| `FR-COST-03` | The ledger is trued up to actual usage; a degraded run refunds the whole estimate | [`tests/invariants.yaml:965`](../../../tests/invariants.yaml) `"FR-COST-03:"` |
| `FR-COST-04` | Per-model price wins, tier default is the fallback, tier vocabulary is closed | [`tests/invariants.yaml:972`](../../../tests/invariants.yaml) `"FR-COST-04:"` |
| `FR-COST-05` | The multi-scope reserve is transactional, verified on both stores | [`tests/invariants.yaml:977`](../../../tests/invariants.yaml) `"FR-COST-05:"` |
| `US-COST-02` | Exactly one pre-emptive alert at the 0.8 threshold | [`tests/invariants.yaml:961`](../../../tests/invariants.yaml) `"US-COST-02:"` |
| `FR-CTL-01` | Department config takes effect live via the provider, no router reconstruction (legacy topology only) | [`docs/invariants.md:116`](../../../docs/invariants.md) `"FR-CTL-01"` |

**Declared but unbound.** `US-FLT-01` (Chief of Staff), `US-FLT-02` (Department
Head) and `US-FLT-03` are cited in module docstrings but are NOT declared ids in
`tests/invariants.yaml` (bounded: `grep -n "US-FLT-0[123]" tests/invariants.yaml
docs/invariants.md`, 2026-08-24, pinned tree: zero hits). The engine catalogue
records the same absence for `DepartmentHead`
([`docs/architecture/engine-components.md:292`](../../../docs/architecture/engine-components.md) `"No binding invariant pins it"`).

---

## 11. RISKS

RISK: The durable Hatchet lane SILENTLY DROPS the claim-time lease token, so
every work item processed through the engine writes UNFENCED. `run_once` puts
`lease_owner` and `lease_expires_at` on the payload
([`boltrig/fleet/pump.py:227`](../../../boltrig/fleet/pump.py)
`"**lease_token.encode(item)"`), but the registered Hatchet task validates the
input with `WorkItemInput`, which declares only `tenant_id` and `item_id` and has
no `model_config` (pydantic 2.13.4 defaults to `extra="ignore"`)
([`boltrig/fleet/hatchet_contract.py:22`](../../../boltrig/fleet/hatchet_contract.py)
`"class WorkItemInput(BaseModel):"`), and the body is then handed
`inp.model_dump()` ([`boltrig/fleet/hatchet_app.py:338`](../../../boltrig/fleet/hatchet_app.py)
`"return await work_item_task_body(res[\"pump\"], inp.model_dump())"`). `decode`
returns `None`, and every write takes the declared fail-open branch
([`boltrig/fleet/lease_token.py:82`](../../../boltrig/fleet/lease_token.py)
`"if OWNER_KEY not in payload and EXPIRES_KEY not in payload:"`). Severity: high.

RISK: The test that certifies the lease token survives the durable boundary
tests `json.loads(json.dumps(payload))` and calls that "exactly what Hatchet
does" ([`tests/fleet/test_lease_fence.py:55`](../../../tests/fleet/test_lease_fence.py)
`"round_tripped = json.loads(json.dumps(payload))  # exactly what Hatchet does"`).
It never constructs `WorkItemInput`, which is the thing on the actual path. The
US-FLT-05 binding therefore rests on a check that cannot detect the defect
above. Severity: high.

RISK: Recursion depth is not enforced on the pump lane or the chat lane at all.
`authority._context` constructs the `InvocationContext` without a `depth`
argument, so it is 0
([`boltrig/fleet/authority.py:74`](../../../boltrig/fleet/authority.py)
`"return InvocationContext("`), and `chat_invocation_context` does the same
([`boltrig/fleet/chat_turn_inputs.py:54`](../../../boltrig/fleet/chat_turn_inputs.py)
`"return InvocationContext("`). A delegated child is therefore always depth 1
against a `max_depth` of 2 or more, and the work item's own `depth` field, which
DOES grow along a follow-on chain, is never compared to anything. The real bound
on a runaway tree is the per-tree fanout counter, not depth. Severity: high.

RISK: `POST /v1/spawn` reads the recursion depth from the caller's request body:
`depth=int(body.context.get("depth", 0))`
([`boltrig/fleet/spawn_entrypoints.py:66`](../../../boltrig/fleet/spawn_entrypoints.py)
`"depth=int(body.context.get(\"depth\", 0)),"`). `foreign_run_asserted` fences
`run_id` and `parent_run_id` but not `depth`
([`boltrig/kernel/run_access.py:130`](../../../boltrig/kernel/run_access.py)
`"for key in (\"run_id\", \"parent_run_id\"):"`), so a caller can reset the counter
on every call. Severity: medium.

RISK: The budget department scope is chosen from CALLER PREFERENCE, not from an
authorised binding. `budget_scope_ids` adds a department scope only when
`prefer["department"]` is present
([`boltrig/fleet/spawn_budget.py:12`](../../../boltrig/fleet/spawn_budget.py)
`"return [tenant_id, *([str(department)] if department else [])]"`), and a scope
with no budget row is a no-op in the store, so omitting the key charges only the
tenant scope. The in-tree wiring register already records this and the fix:
"Derive department scope from the authorised work item/principal, not caller
preference"
([`docs/proposals/policy-as-data-wiring-gates.md:21`](../../../docs/proposals/policy-as-data-wiring-gates.md)
`"Derive department scope from the authorised work item/principal"`). Severity: medium.

RISK: "Cheapest capable runtime" is cheapest by TIER LABEL, never by configured
price. `select_capability` sorts on `_COST_ORDER` over the `cheap|standard|
expensive` strings
([`boltrig/fleet/spawn_skills.py:193`](../../../boltrig/fleet/spawn_skills.py)
`"return min(capable, key=lambda cap:"`) and never consults
`CostAccountant._prices`, which is the table the run is actually BILLED from
([`boltrig/kernel/cost.py:209`](../../../boltrig/kernel/cost.py) `"self._prices: dict[str, Rate] = dict(prices or {})"`). A `cheap`-tier profile
pointing at an expensive endpoint always beats a `standard`-tier profile on a
cheap one. Severity: medium.

RISK: The per-tree fanout counter has no decrement, no reset and no purge, and a
human requeue does not clear it. `requeue` resets `attempts` to zero
([`boltrig/fleet/pump.py:481`](../../../boltrig/fleet/pump.py)
`"item.attempts = 0"`) but the only fanout operation in the tree is the capped
increment ([`boltrig/store/postgres.py:472`](../../../boltrig/store/postgres.py)
`"row = await self._pool.fetchrow("`; bounded: `rg -n "fanout" boltrig/store/`,
2026-08-24, pinned tree). An item parked with reason `spawn_budget_exhausted`
therefore re-escalates immediately on requeue, forever. That park is proven
reachable
([`tests/integration/test_delegation_pump.py:290`](../../../tests/integration/test_delegation_pump.py)
`"assert parked[0].result[\"reason\"] == \"spawn_budget_exhausted\""`), and the only
test that exercises requeue-after-escalation breaches `max_children_per_step`
instead, which is checked BEFORE the counter is touched
([`tests/integration/test_delegation_pump.py:196`](../../../tests/integration/test_delegation_pump.py)
`"assert parked.result[\"reason\"] == \"max_children_per_step\""`). No test requeues a
budget-exhausted tree (bounded: `rg -n "spawn_budget_exhausted" tests/`,
2026-08-24, pinned tree: one hit, the assertion above). Severity: medium.

RISK: `_named_context` adds `agent.send` to the ALLOW set unconditionally,
including for a system-originated item whose principal resolved to
`EMPTY_GRANTS` ([`boltrig/fleet/named_work_routing.py:24`](../../../boltrig/fleet/named_work_routing.py)
`"list(context.grants.allow) + [\"agent.send\"],"`). Its docstring says it seats a
peer "without widening the principal's external authority", which is true of
external verbs but not of this one. SEC-164's stated posture is that an item
naming no principal carries nothing. The tenant ceiling still binds at dispatch.
Severity: medium.

RISK: `NamedAgent.handle` waits for the per-identity turn lease in an UNBOUNDED
poll loop ([`boltrig/fleet/agent_turns.py:58`](../../../boltrig/fleet/agent_turns.py)
`"while lease is None:"`), inside a work-item body whose own 300s lease nothing
renews ([`boltrig/fleet/lease_token.py:5`](../../../boltrig/fleet/lease_token.py)
`"Nothing renews a lease"`). A peer busy on a long foreground chat turn will hold
the work-item body past its lease, letting a second worker claim the same item;
the first worker's eventual write is then refused. Severity: medium.

RISK: The fleet worker serves EXACTLY ONE tenant id for the life of the process,
taken from the manifest or `_DEFAULT_TENANT`
([`boltrig/api/worker.py:287`](../../../boltrig/api/worker.py)
`"tenant = manifest.tenant_id if manifest is not None else _DEFAULT_TENANT"`), and
there is one `run_forever` caller in the tree (bounded:
`rg -n "run_forever\(" --glob '!tests/**' .`, 2026-08-24, pinned tree). Work items
created for any other tenant on a shared store are never claimed and never
diagnosed as unclaimed, because the pump publishes a fact rather than a stalled
verdict. Severity: medium.

RISK: `docs/architecture/engine-components.md` is materially stale on this
subsystem and states the opposite of the code in two places. 2.2 calls
`DepartmentHead` never constructed
([`docs/architecture/engine-components.md:294`](../../../docs/architecture/engine-components.md)
`"never constructed in serving or in tests"`) when `NamedAgent` subclasses it and
`build_org` constructs one per roster member
([`boltrig/fleet/org_builder.py:47`](../../../boltrig/fleet/org_builder.py)
`"agents[profile.address] = NamedAgent("`). 8.2 calls the fleet worker's loop a
keepalive that leaves channel-intake items unpumped
([`docs/architecture/engine-components.md:806`](../../../docs/architecture/engine-components.md)
`"a keepalive. Consequence: work items created by channel intake"`) when that
worker runs the pump
([`boltrig/api/worker.py:429`](../../../boltrig/api/worker.py)
`"await pump.run_forever(tenant, interval=_POLL_SECONDS)"`). A third place was
recorded here and is WITHDRAWN: 2.1 says `ChiefOfStaff` is never constructed in
the serving path
([`docs/architecture/engine-components.md:280`](../../../docs/architecture/engine-components.md)
`"never constructed anywhere in the serving path"`), which is accurate and is
what BT-REQ-0303 records (bounded: `rg -n "ChiefOfStaff\(" --glob '!tests/**'
--glob '!docs/**' .`, 2026-08-24, pinned tree, zero hits). `docs/ARCHITECTURE.md`
is stale in the same direction: its component map still books the fleet as a
hierarchy assembled from `chief_of_staff.py` and `department_head.py`
([`docs/ARCHITECTURE.md:32`](../../../docs/ARCHITECTURE.md)
`"The durable hierarchy and ephemeral spawning"`), and names no flat roster
(bounded: `grep -nEi "named agent|namedagent|roster|flat" docs/ARCHITECTURE.md`,
2026-08-24, pinned tree, zero hits). Severity: medium (documentation, but the
catalogue calls itself definitive and code-verified
([`docs/architecture/engine-components.md:3`](../../../docs/architecture/engine-components.md)
`"The definitive catalogue of every component"`)).

RISK: `SEC-165` (pump routing fails closed) is bound by exactly one test, and
that test exercises the LEGACY `route_to_head` lane through an `_UnroutableCoS`
([`tests/security/test_pump_principal_authority.py:314`](../../../tests/security/test_pump_principal_authority.py)
`"async def test_an_unroutable_department_parks_instead_of_running_under_another_head"`).
No test reaches the `unroutable_agent` park that the SHIPPED flat lane takes
(bounded: `rg -n "unroutable_agent|_route_to_named_agent" tests/ boltrig/`,
2026-08-24, pinned tree). The same applies to `US-FLT-06`, whose binding test
constructs `ChiefOfStaff` and `DepartmentHead` directly
([`tests/integration/test_delegation_pump.py:85`](../../../tests/integration/test_delegation_pump.py)
`"cos = ChiefOfStaff(kernel, [Department(DEPT, intent_keywords=[\"bug\", \"fix\"])])"`).
The proven topology is not the shipped topology. Severity: medium.

RISK: The workflow-learning flywheel has no production writer, and the module
says so: `GENERATED_WORKFLOW_KEY` is "defined here, read once below, and set only
by tests, so `_maybe_learn` has never fired in production"
([`boltrig/fleet/pump.py:72`](../../../boltrig/fleet/pump.py)
`"NOTHING WRITES IT."`). `_settle` still calls `_maybe_learn` on every clean
success, so the code path is live and inert. Severity: low (recorded because a
court was told otherwise; see the cited D7).

RISK: An agent whose manifest `scope_id` differs from its `address` charges its
own reasoning phase and its children's spawns to DIFFERENT budget scopes. The
permanent runtime's department is `agent.scope_id`
([`boltrig/fleet/permanent_runtime.py:114`](../../../boltrig/fleet/permanent_runtime.py) `"department=agent.scope_id,"`) while the children's is
`prefer.setdefault("department", self.name)` where `self.name` is the ADDRESS
([`boltrig/fleet/department_head.py:101`](../../../boltrig/fleet/department_head.py)
`"prefer.setdefault(\"department\", self.name)"`). The seeded budget row uses
`scope_id or address`
([`boltrig/config/manifest_apply.py:66`](../../../boltrig/config/manifest_apply.py)
`"scope_id=tenant if tenant_budget else (agent.scope_id or agent.address),"`), so
the children's scope silently has no budget row and is unmetered. The shipped
example keeps the two equal, which hides it. Severity: low.

RISK: The delegation-tree work items have no depth cap. `MAX_GOVERNED_WORK_DEPTH
= 32` binds only the governed `control.work` create/move paths
([`boltrig/store/work_mutations.py:13`](../../../boltrig/store/work_mutations.py)
`"MAX_GOVERNED_WORK_DEPTH = 32"`), which the fleet does not use; the fleet calls
`store.create_work_item` directly
([`boltrig/fleet/work_follow_ons.py:48`](../../../boltrig/fleet/work_follow_ons.py)
`"await store.create_work_item(child)"`). Severity: low, because the shared
per-tree fanout counter bounds the tree in practice.

RISK: The duplicate follow-on window is narrowed but open, as the module states:
closing it needs a database uniqueness constraint on `(parent_id, intent)`, and
the schema declares none
([`boltrig/store/schema.sql:418`](../../../boltrig/store/schema.sql)
`"PRIMARY KEY (tenant_id, id)"`). Severity: low.

RISK: Neither `work_items` nor `fanout_counters` nor `run_checkpoints` has any
retention policy. The only retention janitor in the fleet purges CLOSED
conversations ([`boltrig/fleet/retention.py:1`](../../../boltrig/fleet/retention.py)
`"Retention purge: hard-erasure of closed conversations"`). Severity: low.

RISK: `_park` sets `requested_by` to `item.owner_member or self._default_agent or
"fleet-pump"` ([`boltrig/fleet/pump.py:580`](../../../boltrig/fleet/pump.py) `"requested_by=item.owner_member or self._default_agent or \"fleet-pump\","`). On
the unroutable-agent branch `owner_member` was never stamped, so the HITL is
attributed to the DEFAULT agent, which is not the agent the item addressed.
Severity: low.

---

## 12. OPEN QUESTIONS

1. Does the Hatchet SDK strip unknown keys before or after `input_validator`
   parsing, that is, would a payload key ever reach the body at all? The
   `model_dump()` call makes the answer moot for the current code, but it decides
   whether the fix is a contract change or a body change. Settled by reading
   `hatchet_sdk` 1.33.x task input handling, which is not vendored in this tree
   (bounded: `find . -name 'hatchet_sdk' -type d`, 2026-08-24, pinned tree: no hits).
2. Is any deployment actually running with `BOLTRIG_REQUIRE_DURABLE` set? The
   repo ships no default and compose does not name it in the `fleet-worker`
   environment block. Settled by reading a live `.env`, which is out of the
   pinned tree.
3. A tree parked with reason `spawn_budget_exhausted` has no recovery path
   short of manual database surgery: `requeue` restores `attempts` but nothing
   restores the tree's fanout counter. The park itself IS proven reachable
   (`tests/integration/test_delegation_pump.py::test_two_pumps_over_one_store_cannot_jointly_exceed_the_fanout_cap`,
   which sets `spawn_budget=3`); what is unsettled is whether the intended
   operator answer is a counter reset, a new tree, or accepting the park.
   Settled by a decision record or a reset surface; neither found.
4. What is the intended relationship between the work item's `depth` field and
   `AgentCapability.max_depth`? They are two different counters with the same
   name and neither is compared to the other. Settled by a decision record; none
   found (bounded: `rg -n "max_depth" docs/decisions/`, 2026-08-24, pinned tree).
5. Does `acquire_agent_turn` guarantee fairness across waiters, or can a
   background work-item turn starve indefinitely behind repeated foreground chat
   turns? The lane enum distinguishes FOREGROUND from BACKGROUND but the
   ordering policy lives in the store implementations, which this reading did
   not cover exhaustively.
6. Is there any operator surface to reset a tree's fanout counter? None found:
   `rg -n "fanout" boltrig/config/ boltrig/kernel/` (2026-08-24, pinned tree)
   returns five hits, all of them the unrelated HITL approval fanout in
   `kernel/hitl.py` and `kernel/channel_notify.py`, and the store exposes only
   `try_increment_fanout`. Settled by either finding a reset surface or
   accepting that a budget-exhausted tree is permanently parked.

---

## 13. Requirements

| id | statement | status | evidence | invariant |
| --- | --- | --- | --- | --- |
| BT-REQ-0300 | The live serving composition is a flat roster of tier-1 named peers, not a tier1-over-tier2 hierarchy. | IMPLEMENTED | `boltrig/fleet/org_builder.py:60` `"None,"` (chief positional) | FLT-PEER-01 |
| BT-REQ-0301 | `build_org` normalises a legacy `hierarchy` manifest into the flat named roster rather than reconstructing Chief/Department authority. | IMPLEMENTED | `boltrig/config/manifest_agents.py:107` `"address=\"cos\","` | SEC-WRK-27 |
| BT-REQ-0302 | With no manifest, `build_org` degrades to a single script-runtime agent addressed `general`. | IMPLEMENTED | `boltrig/fleet/org_builder.py:36` `"roster = (NamedAgentConfig(name=\"general\""` | FLT-PEER-01 |
| BT-REQ-0303 | `ChiefOfStaff` is present in the tree but constructed by no production composition root, so its routing code is unreachable in serving. | DEAD | bounded `rg -n "ChiefOfStaff\(" --glob '!tests/**' --glob '!docs/**' .` (2026-08-24, pinned tree) returns ZERO hits; the only constructions are eight call sites across six test modules | - |
| BT-REQ-0304 | `DepartmentHead` reaches production only as the base class of `NamedAgent`. | IMPLEMENTED | `boltrig/fleet/named_agent.py:29` `"class NamedAgent(DepartmentHead):"` | FLT-PEER-01 |
| BT-REQ-0305 | Every named agent's address is a lowercase slug unique within the roster, and `agents.default` must name a declared address. | IMPLEMENTED | `boltrig/config/manifest.py:167` `"agents.default must name a declared agent address"` | FLT-PEER-01 |
| BT-REQ-0306 | A named agent's `max_depth` is bounded 1..5 and its runtime restricted to codex, script or python-script at parse time. | IMPLEMENTED | `boltrig/config/manifest_agents.py:62` `"if runtime not in {\"codex\", \"script\", \"python-script\"}:"` | FLT-PEER-01 |
| BT-REQ-0307 | An ephemeral child holds no named-agent registry row, no mailbox address and an explicit deny on `agent.send` and `chat.present`. | IMPLEMENTED | `boltrig/fleet/named_agent.py:107` `"list(context.grants.deny) + [\"agent.send\", \"chat.present\"]"` | FLT-PEER-02 |
| BT-REQ-0308 | A named agent with a registry row takes each work-item turn inside a serialized, heartbeaten cross-worker turn lease. | IMPLEMENTED | `boltrig/fleet/named_agent.py:84` `"async with coordinator.hold("` | REL-AGENT-01 |
| BT-REQ-0309 | A permanent profile resolves its runtime per call under `pinned_policy=True` and is never a resident process. | IMPLEMENTED | `boltrig/fleet/permanent_runtime.py:280` `"pinned_policy=True,"` | SEC-WRK-27 |
| BT-REQ-0310 | A spawn resolves exactly one spawn-rule policy snapshot before any spend. | IMPLEMENTED | `boltrig/fleet/spawn_policy.py:83` `"rules = await _effective_rules(store, tenant_id, base_rules)"` | - |
| BT-REQ-0311 | An unreadable or schema-invalid spawn-rule policy raises `SpawnRulePolicyInvalid` and never falls back to an empty rule set. | IMPLEMENTED | `boltrig/fleet/spawn_policy.py:67` `"current spawn-rule policy could not be read"` | - |
| BT-REQ-0312 | Two spawn rules tied at the highest matched priority fail closed. | IMPLEMENTED | `boltrig/config/spawn_rules.py:275` `"spawn rules tie at priority"` | - |
| BT-REQ-0313 | A matched spawn rule refuses a conflicting caller `capability`, `runtime` or `cost_tier` pin rather than ignoring it. | IMPLEMENTED | `boltrig/config/spawn_rules.py:368` `"conflicts with requested {selector}"` | - |
| BT-REQ-0314 | A matched spawn rule may add skills and tighten depth but never widen grants. | IMPLEMENTED | [`boltrig/config/spawn_rules.py:5`](../../../boltrig/config/spawn_rules.py) `"add reviewed skills and tighten depth, but it cannot"`, with the intersection at [`boltrig/fleet/spawn.py:169`](../../../boltrig/fleet/spawn.py) `"child_grants = GrantSet.of(allow=list(intake.tool_grants)).intersect("` | SEC-147 |
| BT-REQ-0315 | Skills resolve parent-first through `extends` with a cycle guard, merging prompt fragments, tool grants and context schemas. | IMPLEMENTED | `boltrig/fleet/spawn_skills.py:78` `"async def _resolve_skill_chain("` | - |
| BT-REQ-0316 | A spawn whose context fails the merged skill schema is refused with `ContextRequirementsUnmet`. | IMPLEMENTED | `tests/integration/test_fleet_spawn.py::test_context_requirements_validated` | - |
| BT-REQ-0317 | Capability selection considers only active profiles in the caller's workspace union the org-wide profiles. | IMPLEMENTED-UNTESTED | `boltrig/fleet/spawn_skills.py:152` `"tenant_id, workspace_id=workspace_id, enforce_workspace=True"`; no test found under `tests/integration/test_fleet_spawn.py` exercising the workspace split | - |
| BT-REQ-0318 | With no pin, the selected capability is the cheapest capable one by cost tier, ties broken by name. | IMPLEMENTED | `tests/integration/test_fleet_spawn.py::test_cheapest_capable_runtime_chosen` | US-FLT-04 |
| BT-REQ-0319 | An explicit `prefer.capability` wins over cost order, and an incapable pin is refused. | IMPLEMENTED | `tests/integration/test_fleet_spawn.py::test_preferred_capability_chosen_when_capable` | US-FLT-04 |
| BT-REQ-0320 | An explicit `prefer.runtime` wins over cost order and accepts `script` as an alias for `python-script`. | IMPLEMENTED | `tests/integration/test_fleet_spawn.py::test_script_runtime_alias_selects_python_script_capability` | - |
| BT-REQ-0321 | Capability selection never consults the configured per-model price table. | IMPLEMENTED | `boltrig/fleet/spawn_skills.py:193` `"return min(capable, key=lambda cap:"` sorts only on `_COST_ORDER` | - |
| BT-REQ-0322 | A spawn whose child depth would exceed `capability.max_depth`, tightened by any rule `max_depth`, raises `DepthExceeded`. | IMPLEMENTED | `tests/integration/test_fleet_spawn.py::test_depth_limit_enforced` | FR-EXE-03 |
| BT-REQ-0323 | The pump builds its execution context with depth 0, so the delegated lane never reaches a capability depth ceiling. | IMPLEMENTED-UNTESTED | `boltrig/fleet/authority.py:74` `"return InvocationContext("` with no depth argument; no test asserts pump-lane depth | - |
| BT-REQ-0324 | `POST /v1/spawn` takes the recursion depth from the caller-supplied request body. | IMPLEMENTED-UNTESTED | `boltrig/fleet/spawn_entrypoints.py:66` `"depth=int(body.context.get(\"depth\", 0)),"`; no test asserts a fence on it | - |
| BT-REQ-0325 | A child's effective grants are the merged skill grants intersected with the parent context, and with any caller ceiling. | IMPLEMENTED | `tests/integration/test_fleet_spawn.py::test_every_spawn_caps_skill_requirements_to_parent_authority` | SEC-147 |
| BT-REQ-0326 | The child context carries the parent's run id as `parent_run_id`, `actor_tier="ephemeral"`, and only the trusted spawn-rule receipt from the parent's extras. | IMPLEMENTED | `boltrig/fleet/spawn_policy.py:158` `"if key != _SPAWN_RULE_CONTEXT_KEY"` | - |
| BT-REQ-0327 | The composed prompt is handed to the routing seam as the egress payload so the PII scanner classifies it before the destination is chosen, and a detection reroutes rather than rewrites. | IMPLEMENTED | `tests/security/test_sensitive_routing.py::test_pii_bearing_payload_routes_local_despite_caller_classification` | SEC-12 |
| BT-REQ-0328 | An unset `sensitive_endpoint_id` keeps the router fail-closed rather than letting sensitive work escape through a standard provider, including on the spawn path. | IMPLEMENTED | `tests/security/test_sensitive_routing.py::test_pii_bearing_payload_without_local_endpoint_fails_closed`; `tests/security/test_sensitive_routing.py::test_spawn_blocks_sensitive_on_hosted_capability` | SEC-12 |
| BT-REQ-0329 | A caller's sealed adapter bearer is re-sealed under the child run id, best-effort, and retired at the child's terminal on both exits. | IMPLEMENTED | `boltrig/fleet/spawn.py:307` `"async def _retire_child_credentials("` | - |
| BT-REQ-0330 | Budget is reserved before the runtime is resolved or invoked. | IMPLEMENTED | `boltrig/fleet/spawn.py:106` `"reservation = await reserve_spawn("` precedes line 126 | FR-COST-02 |
| BT-REQ-0331 | The pre-run estimate is deterministic: `max(16, chars // 4)` tokens priced at the capability's cost tier. | IMPLEMENTED | `boltrig/fleet/spawn_budget.py:18` `"tokens = max(16, chars // 4)"` | - |
| BT-REQ-0332 | Reservation scopes are the tenant plus a department scope present only when `prefer.department` is supplied. | IMPLEMENTED | `boltrig/fleet/spawn_budget.py:12` `"return [tenant_id, *([str(department)] if department else [])]"` | - |
| BT-REQ-0333 | The multi-scope reservation debits every scope or none, in one transaction that re-checks each hard stop under lock. | IMPLEMENTED | `boltrig/kernel/cost.py:316` `"windows = await self._store.reserve_budgets_atomic("` | FR-COST-05 |
| BT-REQ-0334 | A hard-stop breach at reservation writes an `AGENT_SPAWN` audit row with `status="budget_exceeded"` before returning or raising. | IMPLEMENTED | `boltrig/fleet/spawn_reservation.py:43` `"status=\"budget_exceeded\","` | FR-COST-02 |
| BT-REQ-0335 | With `partial_on_budget=True` a budget-blocked spawn returns a degraded partial envelope and the run never happens. | IMPLEMENTED | `boltrig/fleet/spawn.py:520` `"\"reason\": \"budget_exceeded\","` | US-FLT-07 |
| BT-REQ-0336 | With `partial_on_budget=False` a budget-blocked spawn re-raises `BudgetExceeded`. | IMPLEMENTED-UNTESTED | `boltrig/fleet/spawn_reservation.py:48` `"if not partial_on_budget:"`; no test found for the raise branch (bounded: `rg -n "partial_on_budget" tests/`) | - |
| BT-REQ-0337 | No budget check runs during a model call; the ledger is corrected only after the run. | IMPLEMENTED | `boltrig/kernel/cost.py:344` `"Unlike ``reserve`` this never re-checks the hard stop"` | FR-COST-03 |
| BT-REQ-0338 | The post-run true-up applies the signed `(actual - estimate)` delta to every reserved scope and returns the priced figure to the caller. | IMPLEMENTED | `tests/security/test_cost_trueup.py::test_budget_trued_up_to_actual_after_run` | FR-COST-03 |
| BT-REQ-0339 | A runtime that raises after reservation refunds the entire estimate. | IMPLEMENTED | `tests/security/test_cost_trueup.py::test_degraded_run_refunds_the_estimate` | FR-COST-03 |
| BT-REQ-0340 | Actual usage is priced per leg when the runtime reports an input/output split, otherwise at a single rate on the total, never at zero. | IMPLEMENTED | `boltrig/kernel/cost.py:158` `"def price_micros("` with `_priced_micros`; `tests/security/test_cost_trueup.py::test_model_price_from_config_overrides_tier_default` | FR-COST-04 |
| BT-REQ-0341 | A budget scope with no policy row is unmetered rather than refused, on both stores. | IMPLEMENTED | `tests/store/test_budget_atomic_reserve.py::test_reserve_debits_every_scope_when_all_fit` asserts `get_budget(T, "no-budget") is None` after a successful reserve naming it | FR-COST-05 |
| BT-REQ-0342 | A soft budget crossing 0.8 of its cost limit fires exactly one pre-emptive alert and a raising callback never aborts the reservation. | IMPLEMENTED | `tests/security/test_budget_and_pii.py::test_soft_budget_fires_preemptive_alert_when_crossing_the_threshold` | US-COST-02 |
| BT-REQ-0343 | The pump claims at most one work item per cycle, atomically, incrementing `attempts` on the claim. | IMPLEMENTED | `tests/store/test_durable_delegation.py::test_pending_item_claimed_exactly_once_concurrently` | US-FLT-05 |
| BT-REQ-0344 | An expired lease is reclaimable and a lease is never renewed. | IMPLEMENTED | `tests/store/test_durable_delegation.py::test_expired_lease_is_reclaimable_and_attempts_increment` | US-FLT-05 |
| BT-REQ-0345 | Every write to a claimed row is fenced by the backend against the lease tuple minted at claim, never against a value the body re-read. | IMPLEMENTED | `tests/store/test_store_parity.py::test_a_worker_that_lost_its_lease_cannot_overwrite_the_winner` | US-FLT-05 |
| BT-REQ-0346 | A refused fenced write is a no-op plus a warning, never an exception. | IMPLEMENTED | `tests/fleet/test_lease_fence.py::test_a_worker_that_lost_its_lease_writes_nothing_and_does_not_raise` | US-FLT-05 |
| BT-REQ-0347 | A payload carrying no lease token writes unfenced and logs that it did. | IMPLEMENTED | `tests/fleet/test_lease_fence.py::test_an_unbound_write_says_so_rather_than_pretending_to_be_fenced` | US-FLT-05 |
| BT-REQ-0348 | The durable Hatchet task input contract declares only `tenant_id` and `item_id`, so the lease token does not reach the body on that lane. | IMPLEMENTED-UNTESTED | `boltrig/fleet/hatchet_contract.py:22` `"class WorkItemInput(BaseModel):"` with `boltrig/fleet/hatchet_app.py:338` `"inp.model_dump()"`; no test constructs `WorkItemInput` (bounded: `rg -n "WorkItemInput" tests/`) | - |
| BT-REQ-0349 | The pump alternates the peer-mailbox lane and the work-item lane so neither starves the other. | IMPLEMENTED-UNTESTED | `boltrig/fleet/pump.py:214` `"if self._mailbox is not None and self._prefer_mailbox:"`; no test asserts the alternation | - |
| BT-REQ-0350 | `handle_claimed_item` parks a BLOCKED item for a human rather than retrying it, but the claim predicate never returns a BLOCKED row, so the branch is reached only by a direct call or by a status change racing the body. | IMPLEMENTED-UNTESTED | `boltrig/fleet/pump.py:257` `"if item.status == WorkStatus.BLOCKED:"` against `tests/store/test_durable_delegation.py::test_claim_is_tenant_scoped_and_skips_unclaimable`; no test drives the branch (bounded: `rg -n "WorkStatus.BLOCKED" tests/`, 2026-08-24, pinned tree, hits only the claim-skip and the governed status verb) | - |
| BT-REQ-0351 | A `workflow:<id>` target is honoured before any agent routing, through the durable governed path under the item's own context. | IMPLEMENTED | `tests/security/test_channel_addressing.py::test_a_config_mapped_workflow_target_triggers_the_workflow` | SEC-178 |
| BT-REQ-0352 | An addressed workflow that does not exist parks the item for a human instead of falling through to agent routing. | IMPLEMENTED | `tests/security/test_channel_addressing.py::test_an_unknown_workflow_target_parks_for_a_human` | SEC-178 |
| BT-REQ-0353 | A bare `workflow:` prefix with no id is not a workflow target. | IMPLEMENTED | `tests/security/test_channel_addressing.py::test_a_bare_workflow_prefix_is_not_a_workflow_target` | SEC-178 |
| BT-REQ-0354 | On the flat lane an empty or `cos` target routes to the declared default peer and any other target routes to that exact address. | IMPLEMENTED | `boltrig/fleet/named_work_routing.py:40` `"address = self._default_agent if target in {\"\", \"cos\"} else target"`; `tests/security/test_channel_addressing.py::test_an_explicit_target_addresses_a_named_agent` | SEC-178 |
| BT-REQ-0355 | An item addressing an unknown named agent is parked AWAITING_HUMAN with a HITL escalation and nothing is spawned. | IMPLEMENTED-UNTESTED | `boltrig/fleet/pump.py:342` `"reason=(\"unroutable_agent\" if self._flat_agents else \"unroutable_department\")"`; no test reaches the flat branch (bounded: `rg -n "unroutable_agent" tests/`) | SEC-165 |
| BT-REQ-0356 | The routed agent is recorded as `owner_member` and is the `principal_scope` the run's context claims. | IMPLEMENTED | `tests/security/test_pump_principal_authority.py::test_an_addressed_item_routes_to_its_named_head_not_the_inferred_one` | SEC-178 |
| BT-REQ-0357 | The pump consults the cancellation marker at three boundaries and never interrupts an in-flight step. | IMPLEMENTED | `tests/security/test_run_cancel.py::test_in_flight_adapter_call_is_not_interrupted` | SEC-166 |
| BT-REQ-0358 | A cancel seen after a completed step suppresses follow-on work and workflow learning while preserving the step's own record. | IMPLEMENTED | `tests/security/test_run_cancel.py::test_a_cancel_during_the_step_spawns_no_follow_on_work` | SEC-166 |
| BT-REQ-0359 | The terminal CANCELLED state is written in a `finally`, is idempotent, and emits one `work.cancel` audit row. | IMPLEMENTED | `boltrig/fleet/pump.py:600` `"async def _cancel(self, item: WorkItem, run_id: str)"`; `tests/security/test_run_cancel.py` | SEC-166 |
| BT-REQ-0360 | A transient body failure re-queues the item to PENDING until `attempts` reaches `max_attempts` (3), then records FAILED with the error type and a redacted, truncated detail. | IMPLEMENTED | `tests/integration/test_delegation_pump.py::test_transient_failure_requeues_until_the_cap_then_fails` | US-EXE-06 |
| BT-REQ-0361 | A fault raised after the item already reached a settled status never re-opens it. | IMPLEMENTED | `tests/integration/test_delegation_pump.py::test_a_fault_after_the_terminal_write_never_reopens_a_settled_item` | US-EXE-06 |
| BT-REQ-0362 | A cancel that lands during a failure record wins over the failure. | IMPLEMENTED | `boltrig/fleet/pump.py:521` `"if await self._store.is_run_cancel_requested(item.tenant_id, run_id):"`; `tests/security/test_run_cancel.py` | SEC-166 |
| BT-REQ-0363 | A human re-queue moves an AWAITING_HUMAN or BLOCKED item to PENDING, clears the lease and resets `attempts` to zero. | IMPLEMENTED | `tests/integration/test_delegation_pump.py::test_cap_breach_escalates_to_a_human_and_requeue_restores_it` | US-EXE-06 |
| BT-REQ-0364 | A FAILED item cannot be re-queued through `WorkPump.requeue`. | IMPLEMENTED-UNTESTED | `boltrig/fleet/pump.py:475` `"if item is None or item.status not in ("`; no test asserts the refusal | - |
| BT-REQ-0365 | The human re-queue write is deliberately unfenced because it is an authorised reset. | IMPLEMENTED-UNTESTED | `boltrig/fleet/pump.py:466` `"D3 disposal: this write is deliberately NOT lease-fenced"`; no test asserts the absence of a fence | - |
| BT-REQ-0366 | A step producing more than `max_children_per_step` (8) sub-tasks escalates to a human and spawns nothing. | IMPLEMENTED | `tests/integration/test_delegation_pump.py::test_cap_breach_escalates_to_a_human_and_requeue_restores_it` | US-EXE-06 |
| BT-REQ-0367 | The whole step's fan-out is reserved against a per-tree counter atomically, so two pumps over one store cannot jointly exceed it. | IMPLEMENTED | `tests/integration/test_delegation_pump.py::test_two_pumps_over_one_store_cannot_jointly_exceed_the_fanout_cap` | US-EXE-07 |
| BT-REQ-0368 | The per-tree fan-out counter is keyed by the tree ROOT work-item id, found by a cycle-safe parent walk. | IMPLEMENTED | `boltrig/fleet/department_head.py:33` `"async def tree_root_id(store: Any, item: WorkItem) -> str:"` | US-EXE-07 |
| BT-REQ-0369 | The per-tree fan-out counter has no decrement, reset or purge operation. | IMPLEMENTED | bounded `rg -n "fanout" boltrig/store/` returns only `try_increment_fanout` and the DDL | - |
| BT-REQ-0370 | A step whose children report more than `max_new_items_per_step` (16) follow-ons escalates, carrying the children on the escalation record. | IMPLEMENTED-UNTESTED | `boltrig/fleet/department_head.py:138` `"if len(new_items) > self.max_new_items_per_step:"`; no test found (bounded: `rg -n "max_new_items_per_step" tests/`) | US-EXE-06 |
| BT-REQ-0371 | Children run bounded-parallel under a semaphore of `max_children_per_step`, and a child exception becomes a degraded failed-child record rather than raising past the join. | IMPLEMENTED | `boltrig/fleet/department_head.py:191` `"except Exception as exc:  # captured, never raised past the join (D8)"`; `tests/integration/test_delegation_pump.py` `_ExplodingSpawner` | US-FLT-07 |
| BT-REQ-0372 | Each sub-task is persisted as an IN_FLIGHT child work item with a NULL lease, which neither store's claim predicate can match. | IMPLEMENTED | `boltrig/fleet/department_head.py:225` `"status=WorkStatus.IN_FLIGHT,"`; `docs/vjs/2026-VJS-CC-BOLTRIG-WORK-ITEM-LEASE-FENCE-001-opinion.md:75` `"neither backend's claim predicate can match a NULL lease"` | US-FLT-05 |
| BT-REQ-0373 | A budget-skipped child is recorded DONE with `degraded=True`, because only `status == "error"` marks a child FAILED. | IMPLEMENTED-UNTESTED | `boltrig/fleet/department_head.py:202` `"child_item.status = ("`; no test covers the `partial` status | - |
| BT-REQ-0374 | A cap or budget escalation files a `HITLType.ESCALATION` scoped to the escalating agent and returns a structured escalated outcome. | IMPLEMENTED | `boltrig/fleet/department_head.py:272` `"request = await self._spawner._kernel.hitl.create("` | US-EXE-06 |
| BT-REQ-0375 | An escalated outcome parks the item AWAITING_HUMAN against the HITL id the agent already filed. | IMPLEMENTED | `boltrig/fleet/pump.py:427` `"if outcome.get(\"status\") == \"escalated\":"` | US-EXE-06 |
| BT-REQ-0376 | A convergent item whose joined aggregate is degraded parks for a human and is never DONE. | IMPLEMENTED | `tests/integration/test_delegation_pump.py::test_convergent_degraded_aggregate_parks_for_a_human_never_done` | US-FLT-07 |
| BT-REQ-0377 | A terminal item is stamped with a deterministic outcome score: 1.0 clean DONE, 0.5 degraded DONE, 0.0 FAILED, null for AWAITING_HUMAN and CANCELLED. | IMPLEMENTED | `boltrig/fleet/pump.py:115` `"def outcome_score(terminal_status: str, degraded: bool)"` | - |
| BT-REQ-0378 | Follow-on work items inherit the parent's principal, workspace and stamped authority ceilings and are created PENDING at `parent.depth + 1`. | IMPLEMENTED | `tests/security/test_pump_principal_authority.py::test_creator_ceiling_survives_promotion_and_propagates_to_follow_on_work` | SEC-164 |
| BT-REQ-0379 | A follow-on whose intent already exists among the parent's children is skipped, and the check is not a concurrency fence. | IMPLEMENTED | `tests/fleet/test_lease_fence.py::test_the_duplicate_child_window_is_narrowed_but_not_closed` | US-FLT-05 |
| BT-REQ-0380 | A delegated run executes at the requesting principal's authority, resolved through the same `effective_grants_for_request` the request path uses. | IMPLEMENTED | `tests/security/test_pump_principal_authority.py::test_low_privilege_principals_item_cannot_execute_a_verb_it_lacks` | SEC-164 |
| BT-REQ-0381 | An item naming no principal, or one the store cannot identify, carries `EMPTY_GRANTS` and never the tenant ceiling. | IMPLEMENTED | `tests/security/test_pump_principal_authority.py::test_an_unidentified_principal_carries_no_authority` | SEC-164 |
| BT-REQ-0382 | The channel-thread ceiling and the creation-time creator ceiling are each intersected into the execution grants. | IMPLEMENTED | `tests/security/test_channel_policy.py::test_thread_ceiling_is_stamped_and_narrows_execution_authority` | SEC-164 |
| BT-REQ-0383 | The tenant permission ceiling is a separate axis, enforced independently at dispatch and never folded into the execution grants. | IMPLEMENTED | `tests/security/test_pump_principal_authority.py::test_a_tenant_wide_principal_is_still_bound_by_a_narrow_tenant_ceiling` | SEC-164 |
| BT-REQ-0384 | Seating a peer adds `agent.send` to the run's allow set unconditionally, including for a system-originated item with no principal. | IMPLEMENTED-UNTESTED | `boltrig/fleet/named_work_routing.py:24` `"list(context.grants.allow) + [\"agent.send\"],"`; no test asserts the empty-principal case | - |
| BT-REQ-0385 | Post-run reflection carries a two-verb system seat (`memory.remember`, `memory.propose`) and never the principal's or the tenant's authority. | IMPLEMENTED | `tests/security/test_self_improvement_competence.py::test_build_org_wires_the_kernel_so_reflection_is_reachable` | - |
| BT-REQ-0386 | Reflection is off unless `BOLTRIG_REFLECT=1`, and a reflection failure never fails the run. | IMPLEMENTED | `boltrig/fleet/pump.py:165` `"os.getenv(\"BOLTRIG_REFLECT\") == \"1\""`; `boltrig/fleet/reflection.py:120` `"except Exception:  # reflection is best-effort"` | - |
| BT-REQ-0387 | The workflow-learning branch inside `_settle` is unreachable in production because nothing writes the `generated_workflow` key it reads. | DEAD | `boltrig/fleet/pump.py:72` `"NOTHING WRITES IT."`; bounded `rg -n "generated_workflow" --glob '!tests/**' --glob '!docs/**' .` (2026-08-24, pinned tree) returns exactly one hit, the constant's own definition at [`boltrig/fleet/pump.py:78`](../../../boltrig/fleet/pump.py) `"GENERATED_WORKFLOW_KEY = \"generated_workflow\""` | - |
| BT-REQ-0388 | Executor selection returns a durable Hatchet executor when the SDK is installed and configured, otherwise a declared non-durable local fallback, and logs which. | IMPLEMENTED | `tests/integration/test_executor_selection.py::test_default_falls_back_to_local_with_durable_false` | US-EXE-05 |
| BT-REQ-0389 | With `BOLTRIG_REQUIRE_DURABLE` set, a durable-engine failure refuses to boot instead of falling back. | IMPLEMENTED | `tests/integration/test_executor_selection.py::test_require_durable_refuses_to_fall_back` | US-EXE-05 |
| BT-REQ-0390 | Enqueuing an unregistered task name fails closed with `KeyError` on both executors. | IMPLEMENTED | `boltrig/fleet/workers.py:80` `"fn = self._tasks[task_name]  # KeyError = unregistered task, fail-closed"` | US-EXE-05 |
| BT-REQ-0391 | The durable and direct lanes run the same registered work-item body. | IMPLEMENTED | `tests/integration/test_delegation_pump.py::test_durable_lane_enqueues_the_same_registered_body` | US-FLT-06 |
| BT-REQ-0392 | A durable task body re-enters the kernel chokepoint and refuses a payload whose tenant differs from its context envelope. | IMPLEMENTED | `tests/integration/test_durable_resume.py::test_task_payload_tenant_must_match_the_envelope` | FR-EXE-06 |
| BT-REQ-0393 | The Hatchet work-item task refuses to run when no pump is wired rather than dropping the item. | IMPLEMENTED-UNTESTED | `boltrig/fleet/hatchet_app.py:337` `"raise RuntimeError(\"no pump wired for boltrig-work-item\")"`; no test found | - |
| BT-REQ-0394 | Each spawn writes exactly one `AGENT_SPAWN` audit row carrying capability, runtime, spawn-rule receipt, filtered model route, degrade reason, latency, tokens and cost. | IMPLEMENTED | `tests/integration/test_fleet_spawn.py::test_spawn_audit_records_latency_for_model_telemetry` | - |
| BT-REQ-0395 | The audit write happens before the observability sink, and a sink failure never loses the audit row. | IMPLEMENTED | `tests/integration/test_fleet_spawn.py::test_observability_sink_runs_after_audit_persist` | - |
| BT-REQ-0396 | Every published `subagent` open frame is paired with a `subagent_end` settle frame for the same child run id on the same parent relay, on success and on a runtime raise. | IMPLEMENTED | `tests/integration/test_fleet_spawn.py::test_subagent_open_is_settled_by_subagent_end_frame` | US-FLT-04 |
| BT-REQ-0397 | The pump publishes one windowed throughput receipt per window reporting processed count and whether any cycle raised, and never escalates to a stalled verdict. | IMPLEMENTED | `tests/unit/test_pump_progress.py::test_the_loop_records_a_receipt_under_the_pump_job_name`; `tests/unit/test_pump_progress.py::test_any_raising_cycle_makes_the_whole_window_a_failure` | - |
| BT-REQ-0398 | A FAILED item's recorded error detail has URLs redacted and is truncated to 200 characters. | IMPLEMENTED-UNTESTED | `boltrig/fleet/pump.py:112` `"return _URL_RE.sub(\"[url]\", str(exc))[:_MAX_ERROR_DETAIL]"`; no test found (bounded: `rg -n "_error_detail" tests/`) | - |
| BT-REQ-0399 | One fleet-worker process serves exactly one tenant id for its lifetime. | IMPLEMENTED | `boltrig/api/worker.py:429` `"await pump.run_forever(tenant, interval=_POLL_SECONDS)"` with the tenant fixed at line 287 | - |
