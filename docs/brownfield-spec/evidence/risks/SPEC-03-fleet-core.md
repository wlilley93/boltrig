# Risks harvested from SPEC-03-fleet-core.md

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

---

RISK: The test that certifies the lease token survives the durable boundary
tests `json.loads(json.dumps(payload))` and calls that "exactly what Hatchet
does" ([`tests/fleet/test_lease_fence.py:55`](../../../tests/fleet/test_lease_fence.py)
`"round_tripped = json.loads(json.dumps(payload))  # exactly what Hatchet does"`).
It never constructs `WorkItemInput`, which is the thing on the actual path. The
US-FLT-05 binding therefore rests on a check that cannot detect the defect
above. Severity: high.

---

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

---

RISK: `POST /v1/spawn` reads the recursion depth from the caller's request body:
`depth=int(body.context.get("depth", 0))`
([`boltrig/fleet/spawn_entrypoints.py:66`](../../../boltrig/fleet/spawn_entrypoints.py)
`"depth=int(body.context.get(\"depth\", 0)),"`). `foreign_run_asserted` fences
`run_id` and `parent_run_id` but not `depth`
([`boltrig/kernel/run_access.py:130`](../../../boltrig/kernel/run_access.py)
`"for key in (\"run_id\", \"parent_run_id\"):"`), so a caller can reset the counter
on every call. Severity: medium.

---

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

---

RISK: "Cheapest capable runtime" is cheapest by TIER LABEL, never by configured
price. `select_capability` sorts on `_COST_ORDER` over the `cheap|standard|
expensive` strings
([`boltrig/fleet/spawn_skills.py:193`](../../../boltrig/fleet/spawn_skills.py)
`"return min(capable, key=lambda cap:"`) and never consults
`CostAccountant._prices`, which is the table the run is actually BILLED from
([`boltrig/kernel/cost.py:209`](../../../boltrig/kernel/cost.py) `"self._prices: dict[str, Rate] = dict(prices or {})"`). A `cheap`-tier profile
pointing at an expensive endpoint always beats a `standard`-tier profile on a
cheap one. Severity: medium.

---

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

---

RISK: `_named_context` adds `agent.send` to the ALLOW set unconditionally,
including for a system-originated item whose principal resolved to
`EMPTY_GRANTS` ([`boltrig/fleet/named_work_routing.py:24`](../../../boltrig/fleet/named_work_routing.py)
`"list(context.grants.allow) + [\"agent.send\"],"`). Its docstring says it seats a
peer "without widening the principal's external authority", which is true of
external verbs but not of this one. SEC-164's stated posture is that an item
naming no principal carries nothing. The tenant ceiling still binds at dispatch.
Severity: medium.

---

RISK: `NamedAgent.handle` waits for the per-identity turn lease in an UNBOUNDED
poll loop ([`boltrig/fleet/agent_turns.py:58`](../../../boltrig/fleet/agent_turns.py)
`"while lease is None:"`), inside a work-item body whose own 300s lease nothing
renews ([`boltrig/fleet/lease_token.py:5`](../../../boltrig/fleet/lease_token.py)
`"Nothing renews a lease"`). A peer busy on a long foreground chat turn will hold
the work-item body past its lease, letting a second worker claim the same item;
the first worker's eventual write is then refused. Severity: medium.

---

RISK: The fleet worker serves EXACTLY ONE tenant id for the life of the process,
taken from the manifest or `_DEFAULT_TENANT`
([`boltrig/api/worker.py:287`](../../../boltrig/api/worker.py)
`"tenant = manifest.tenant_id if manifest is not None else _DEFAULT_TENANT"`), and
there is one `run_forever` caller in the tree (bounded:
`rg -n "run_forever\(" --glob '!tests/**' .`, 2026-08-24, pinned tree). Work items
created for any other tenant on a shared store are never claimed and never
diagnosed as unclaimed, because the pump publishes a fact rather than a stalled
verdict. Severity: medium.

---

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

---

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

---

RISK: The workflow-learning flywheel has no production writer, and the module
says so: `GENERATED_WORKFLOW_KEY` is "defined here, read once below, and set only
by tests, so `_maybe_learn` has never fired in production"
([`boltrig/fleet/pump.py:72`](../../../boltrig/fleet/pump.py)
`"NOTHING WRITES IT."`). `_settle` still calls `_maybe_learn` on every clean
success, so the code path is live and inert. Severity: low (recorded because a
court was told otherwise; see the cited D7).

---

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

---

RISK: The delegation-tree work items have no depth cap. `MAX_GOVERNED_WORK_DEPTH
= 32` binds only the governed `control.work` create/move paths
([`boltrig/store/work_mutations.py:13`](../../../boltrig/store/work_mutations.py)
`"MAX_GOVERNED_WORK_DEPTH = 32"`), which the fleet does not use; the fleet calls
`store.create_work_item` directly
([`boltrig/fleet/work_follow_ons.py:48`](../../../boltrig/fleet/work_follow_ons.py)
`"await store.create_work_item(child)"`). Severity: low, because the shared
per-tree fanout counter bounds the tree in practice.

---

RISK: The duplicate follow-on window is narrowed but open, as the module states:
closing it needs a database uniqueness constraint on `(parent_id, intent)`, and
the schema declares none
([`boltrig/store/schema.sql:418`](../../../boltrig/store/schema.sql)
`"PRIMARY KEY (tenant_id, id)"`). Severity: low.

---

RISK: Neither `work_items` nor `fanout_counters` nor `run_checkpoints` has any
retention policy. The only retention janitor in the fleet purges CLOSED
conversations ([`boltrig/fleet/retention.py:1`](../../../boltrig/fleet/retention.py)
`"Retention purge: hard-erasure of closed conversations"`). Severity: low.

---

RISK: `_park` sets `requested_by` to `item.owner_member or self._default_agent or
"fleet-pump"` ([`boltrig/fleet/pump.py:580`](../../../boltrig/fleet/pump.py) `"requested_by=item.owner_member or self._default_agent or \"fleet-pump\","`). On
the unroutable-agent branch `owner_member` was never stamped, so the HITL is
attributed to the DEFAULT agent, which is not the agent the item addressed.
Severity: low.

---
