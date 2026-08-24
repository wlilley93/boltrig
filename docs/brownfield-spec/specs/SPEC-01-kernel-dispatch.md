# SPEC-01 The kernel dispatch chokepoint

- **area**: 01 The kernel dispatch chokepoint
- **id-block**: BT-REQ-0100 to BT-REQ-0199
- **referent commit**: `19bcae7fa81663fe8998377c86451ba08fb16e48` (`origin/main`, tree pinned)
- **author-agent**: brownfield-spec area 01
- **date**: 2026-08-24

## Bound of this reading

Read in full, line by line: `boltrig/kernel/dispatch.py`, `__init__.py`, `routing.py`,
`registry.py`, `grants.py`, `credentials.py`, `audit.py`, `audit_outbox.py`,
`approval_gate.py`, `approval_posture.py`, `approval_digest.py`, `cost.py`,
`effect_inverses.py`, `adapter_provider.py`, `adapter_errors.py`, `idempotency.py`,
`ratelimit.py`, `hitl.py`, `hitl_fingerprint.py`, `schema_diagnosis.py`,
`run_event_projection.py`, `questions.py`, `held_call.py`, `run_effect_recorder.py`,
`run_scoped_credentials.py`, `invoke_finalization.py`; plus
`boltrig/models/registry.py`, `grants.py`, `context.py`, `capability_routing.py`,
`errors.py`, `boltrig/adapters/base.py`, `boltrig/store/idempotency.py`,
`idempotency_contract.py`, and the relevant DDL in `boltrig/store/schema.sql` and
`rls.sql`.

Sampled rather than read exhaustively: `boltrig/kernel/events.py` (top-level
definitions of both classes read; the relay's `subscribe`/`snapshot`/`seq` internals
past line 225 read only by signature), `security_events.py` (`SecurityWriter` read;
the anchorer not), `pii.py` (top-level predicates only), `mcp.py` (the two
`kernel.invoke` call sites and `_may_disclose` only), `trajectory.py`
(`RecordingDispatcher` only). `boltrig/store/postgres.py` and the fleet are outside
this area and are cited only where the chokepoint's contract depends on them.

## Purpose

`Dispatcher.invoke` is the single function every external action in Boltrig passes
through, and its job is to compose the governance steps in one fixed order and to
write exactly one audit row for the outcome whatever that outcome is
([`boltrig/kernel/dispatch.py:1`](../../../boltrig/kernel/dispatch.py) `"The dispatch chokepoint (P2, US-KER-01, K-1)"`).
It implements no policy of its own: it resolves a verb to a binding out of the
store, calls out to the grant checker, the schema validator, the idempotency
coordinator, the approval gate, the rate limiter and the credential resolver, then
executes exactly one adapter or one agent
([`boltrig/kernel/__init__.py:3`](../../../boltrig/kernel/__init__.py) `"one object. It implements"`).
The security property the whole design rests on is that a credential is resolved
inside this boundary at the last possible moment and is handed to one adapter call
and nothing else
([`boltrig/kernel/credentials.py:3`](../../../boltrig/kernel/credentials.py) `"Credentials are resolved only inside the kernel"`).

## Boundaries

### What it owns

- Verb and binding resolution for a tenant, including the capability router that
  collapses many eligible capability bindings to one execution plan
  ([`boltrig/kernel/routing.py:209`](../../../boltrig/kernel/routing.py) `"The dispatcher's step 1: the verb definition"`).
- The ordered gate composition and the single `finally`-block audit write
  ([`boltrig/kernel/dispatch.py:428`](../../../boltrig/kernel/dispatch.py) `"finally:"`).
- Credential resolution and the run-scoped secret seams
  ([`boltrig/kernel/credentials.py:142`](../../../boltrig/kernel/credentials.py) `"Resolve the credential an adapter needs"`).
- The append-only hash-chained audit stream and its outbox
  ([`boltrig/kernel/audit.py:315`](../../../boltrig/kernel/audit.py) `"class AuditWriter:"`).

### What it must not touch

The layering rule is that `kernel/` and `models/` import nothing from `fleet/` or
the sidecars
([`AGENTS.md:41`](../../../AGENTS.md) `"Respect the import boundary: `kernel/` and `models/` import nothing from"`).
This is machine-enforced, not aspirational: `scripts/check_architecture.py` walks
every `.py` under `boltrig/kernel` with a deny-list of `boltrig.fleet` and
`services`, flags dynamic-import escapes, and treats a MISSING kernel root as a
violation rather than a skip
([`scripts/check_architecture.py:58`](../../../scripts/check_architecture.py) `"_KERNEL_FORBIDDEN = (\"boltrig.fleet\", \"services\")"`;
[`scripts/check_architecture.py:189`](../../../scripts/check_architecture.py) `"kernel dependency points outward"`).
It runs as `make architecture`
([`Makefile:115`](../../../Makefile) `"architecture: ## Enforce inward-only thin-orchestration"`).

Consequences visible in the code: the fleet's agent invoker is INJECTED after
construction rather than imported
([`boltrig/kernel/__init__.py:117`](../../../boltrig/kernel/__init__.py) `"def set_agent_invoker(self, invoker: AgentInvoker)"`),
and the HITL answer-to-resume bridge is a callable set from outside
([`boltrig/kernel/hitl.py:90`](../../../boltrig/kernel/hitl.py) `"def set_resume_notifier(self, notifier"`).
The run-terminal credential sweep is likewise a seam the kernel offers and the
fleet calls
([`boltrig/kernel/credentials.py:365`](../../../boltrig/kernel/credentials.py) `"Lifecycle honesty: the kernel owns no run-terminal hook"`).

### The one-chokepoint claim, tested

`adapter.execute(...)` is called from exactly ONE place in the shipped package:
[`boltrig/kernel/dispatch.py:719`](../../../boltrig/kernel/dispatch.py)
`"result: Result = await adapter.execute(verb_def.id, resolved_params"`.
Bounded: `rg -n "\.execute\(" boltrig/ apps/ services/ tools/ scripts/` on the
pinned tree (2026-08-24), filtering the SQL-pool spellings
(`_pool.execute`, `connection.execute`, `pipe.execute`), leaves three non-kernel
hits, all outside the request path of a Boltrig caller:

- `scripts/smoke.py:196` `"result = await adapter.execute(verb, params, cred"` (a
  developer smoke script, deliberately calling an adapter raw).
- `boltrig/fleet/browser_executor.py:90` `"result = await browser.execute(verb, params, None, context)"`,
  the browser SIDECAR's own HTTP face. It is not a second kernel path: it is the
  far side of a process boundary the kernel-side browser adapter calls into, and
  it hands the adapter a `None` credential. It is still an execute endpoint that
  runs no grant check of its own and is protected only by the
  `x-boltrig-browser-protocol` header and the `allowed` verb set
  ([`boltrig/fleet/browser_executor.py:80`](../../../boltrig/fleet/browser_executor.py) `"x-boltrig-browser-protocol\") != \"1\""`).
  Recorded here as a boundary observation; it belongs to the fleet/sidecar area.
- `boltrig/adapters/**` `super().execute(...)` calls, which are within one adapter.

Every model-facing and HTTP-facing door funnels into `Kernel.invoke`, which
delegates straight to the dispatcher
([`boltrig/kernel/__init__.py:175`](../../../boltrig/kernel/__init__.py) `"return await self.dispatcher.invoke("`).
The MCP face states this explicitly and is invariant-bound
([`boltrig/kernel/mcp.py:367`](../../../boltrig/kernel/mcp.py) `"Translate to ``kernel.invoke`` - the unchanged chokepoint (SEC-26)"`;
[`tests/invariants.yaml:835`](../../../tests/invariants.yaml) `"Chokepoint parity - every MCP-originated call"`).

## Objects and contracts

### Noun

A stable concept an agent reasons about, keyed `(tenant_id, id)`
([`boltrig/models/registry.py:40`](../../../boltrig/models/registry.py) `"A stable concept agents reason about"`).
Fields: `id`, `tenant_id`, `description`, `schema` (a free JSON blob, unused by
dispatch), `is_active`. Archival is recoverable: an archived noun stays stored but
is not discoverable, bindable or invocable
([`boltrig/models/registry.py:46`](../../../boltrig/models/registry.py) `"archived nouns remain stored but are not"`).
The archival fence is enforced in the store read, not in dispatch: `get_verb`
joins `nouns` and requires both `is_active` flags
([`boltrig/store/authored_definitions_postgres.py:43`](../../../boltrig/store/authored_definitions_postgres.py) `"AND v.is_active=TRUE AND n.is_active=TRUE"`;
in-memory twin at [`boltrig/store/authored_definitions_memory.py:38`](../../../boltrig/store/authored_definitions_memory.py) `"async def get_verb(self, tenant_id, verb_id):"`).

### Verb

The capability offered on a noun. Fields:

| field | type | meaning at dispatch |
| --- | --- | --- |
| `id` | `VerbId` | the addressable name, PK with `tenant_id` |
| `noun_id` | `NounId` | FK to `nouns`; archival of either hides the verb |
| `input_schema` | JSON Schema | validated at step 3; `{}` means no validation |
| `output_schema` | JSON Schema | validated at step 8; `{}` means no validation |
| `consequence` | `low` / `high` | the posture gate's default input |
| `degraded_mode` | dict or None | the P9 fallback shape; None means fail hard |
| `identity_mode` | `service-principal` / `delegated` | declared, NOT read by dispatch |
| `idempotency_mode` | `cacheable` / `disabled` | `disabled` refuses a key outright |
| `is_active` | bool | archival, enforced in the store read |

([`boltrig/models/registry.py:53`](../../../boltrig/models/registry.py) `"A capability available on a noun"`.)
`identity_mode` is declared and stored but read nowhere on the dispatch path.
Bounded: `rg -n "identity_mode" boltrig/kernel/` returns nothing (pinned tree,
2026-08-24).

### VerbBinding

Resolves one verb to its implementation for one tenant, PK `(verb_id, tenant_id)`
([`boltrig/models/registry.py:96`](../../../boltrig/models/registry.py) `"Resolves a verb to its implementation for a tenant"`;
[`boltrig/store/schema.sql:46`](../../../boltrig/store/schema.sql) `"CREATE TABLE IF NOT EXISTS verb_bindings ("`).
Fields read at dispatch: `target_type` (`adapter` or `agent`), `target_ref` (an
adapter id or an agent-capability name), `rate_limit`. The four presentation fields
(`internal_source_operation_id`, `canonical_capability_id`, `model_display_name`,
`connection_label`) are declared unread by enforcement
([`boltrig/models/registry.py:105`](../../../boltrig/models/registry.py) `"enforcement sites until the multi-binding shard"`),
and dispatch confirms it: none is referenced under `boltrig/kernel/dispatch.py`
or `routing.py` (bounded: `rg -n "canonical_capability_id|model_display_name" boltrig/kernel/`,
pinned tree).

`owned_by` states the activation-ownership convention: a binding is an adapter's
only when it is an ADAPTER binding whose `target_ref` is that adapter's id, so an
agent-pointed verb survives re-registration
([`boltrig/models/registry.py:112`](../../../boltrig/models/registry.py) `"Is this binding the named adapter's to change or remove?"`).

### RateLimit

`per` (`minute` / `hour`), `max`, `scope` (`tenant` / `verb`). The window is a FIXED
CALENDAR window, not a sliding one, and the docstring says so at the point of
configuration because a configured 5/min admits up to 10 across a boundary
([`boltrig/models/registry.py:75`](../../../boltrig/models/registry.py) `"``max`` is per FIXED CALENDAR window, not per sliding one"`).
There is NO validation of `per` or `scope` on the dataclass: it is a plain frozen
dataclass with no `__post_init__`.

### GrantSet and the grant

A grant is not a row: it is a tuple of allow patterns and a tuple of deny patterns
carried immutably on the caller's context
([`boltrig/models/grants.py:93`](../../../boltrig/models/grants.py) `"An immutable set of allow/deny verb patterns held by a caller"`).
A grant TOKEN is a verb id (`ticket.create`), a terminal-wildcard pattern
(`ticket.*`) or the lone `*`
([`boltrig/models/grants.py:13`](../../../boltrig/models/grants.py) `"Grant tokens are verb ids (``ticket.create``)"`).

`permits` is deny-dominant and fail-closed, in that order:

1. any deny match returns False immediately (K-5),
2. any allow match returns True,
3. nothing matched returns False (K-13)

([`boltrig/models/grants.py:103`](../../../boltrig/models/grants.py) `"True iff this set authorises ``verb_id``. Deny-dominant, fail-closed."`).

`_matches` refuses a verb id that is not a SAFE identifier before any pattern
comparison, so a Unicode confusable can never impersonate an ASCII verb; both sides
are NFKC-normalised; `jira.*` matches `jira.read` and `jira` but not `jirax.read`
([`boltrig/models/grants.py:71`](../../../boltrig/models/grants.py) `"Match one grant pattern against a verb id (K-9 terminal-wildcard rule)"`;
[`boltrig/models/grants.py:86`](../../../boltrig/models/grants.py) `"``jira.*`` matches ``jira.read`` (next char is a boundary)"`).

`intersect` is how an ephemeral's effective grants are computed. Allows must be
permitted by BOTH sides; denies UNION. A `*` on this side against an exact-verb
ceiling becomes that ceiling's own entries rather than being dropped, and a
`foo.*` against a ceiling narrows to the ceiling's entries the wildcard covers
([`boltrig/models/grants.py:111`](../../../boltrig/models/grants.py) `"Tenant ∩ skill grants. Allows must be permitted by BOTH; denies union."`).

`TenantPermissions` is the tenant ceiling, a `GrantSet` keyed by tenant, defaulting
to `EMPTY_GRANTS`
([`boltrig/models/grants.py:169`](../../../boltrig/models/grants.py) `"A tenant's ceiling of permitted verbs"`).
Persisted as two JSONB arrays
([`boltrig/store/schema.sql:728`](../../../boltrig/store/schema.sql) `"CREATE TABLE IF NOT EXISTS tenant_permissions ("`).

### InvocationContext

The authority envelope carried on every call
([`boltrig/models/context.py:18`](../../../boltrig/models/context.py) `"class InvocationContext:"`).
`tenant_id`, `run_id`, `parent_run_id`, `depth`, `on_behalf_of`, `workspace_id`,
`ip_address`, `user_agent`, `grants` (defaulting to `EMPTY_GRANTS`), `actor`,
`actor_tier` (`tier1|tier2|ephemeral|human`), `skills_loaded`, `extra`.
Identity is authenticated-by-construction: the door stamps `tenant_id` and
`on_behalf_of` from the verified bearer and no handler reads them from a body
([`boltrig/models/context.py:3`](../../../boltrig/models/context.py) `"Identity in the context is authenticated-by-construction (K-3)"`).
`extra` is explicitly NOT read by dispatch itself
([`boltrig/models/context.py:44`](../../../boltrig/models/context.py) `"The kernel dispatch never reads this"`),
with two exceptions added later that are worth naming: `approval_gate` WRITES
`approved_by` / `approval_request_id` / `approval_request_fingerprint` /
`approval_resource_context` into it after a successful consume
([`boltrig/kernel/approval_gate.py:216`](../../../boltrig/kernel/approval_gate.py) `"return replace("`),
`run_effect_recorder` reads `extra["effect_revert"]`
([`boltrig/kernel/run_effect_recorder.py:46`](../../../boltrig/kernel/run_effect_recorder.py) `"if not context.run_id or (context.extra or {}).get(\"effect_revert\")"`),
and the approval fingerprint binds `extra["principal_role"]` and
`extra["principal_scope"]`
([`boltrig/kernel/hitl_fingerprint.py:64`](../../../boltrig/kernel/hitl_fingerprint.py) `"\"role\": context.extra.get(\"principal_role\")"`).

The envelope serialisation is shared so three replay lanes cannot each drop a
different authority-bearing field, and reconstruction narrows to fail-closed
defaults (empty grants, ephemeral tier)
([`boltrig/models/context.py:80`](../../../boltrig/models/context.py) `"fields take the fail-closed defaults (empty grants, ephemeral tier)"`).

### The capability layer (decision 0036)

Four records sit BESIDE `verb_bindings` rather than through it
([`docs/decisions/0036-multi-binding-lands-beside-verb-bindings.md:25`](../../../docs/decisions/0036-multi-binding-lands-beside-verb-bindings.md) `"The plural layer is a NEW table"`).

| record | identity | eligibility rule |
| --- | --- | --- |
| `ProviderConnection` | `(tenant_id, id)` | `eligible` iff `status == "active"` and `health not in ("revoked","down")` |
| `SourceOperation` | `(tenant_id, id)` | provider-verbatim, never model-facing, carries `schema_digest` |
| `CapabilityBinding` | `(tenant_id, binding_id)` | `status == "approved"` and `serves(workspace_id)` |
| `RoutingPolicy` | `(tenant_id, id)` | `applies(version, operation_class, workspace_id)` |

([`boltrig/models/capability_routing.py:101`](../../../boltrig/models/capability_routing.py) `"return self.status == \"active\" and self.health not in"`;
[`boltrig/models/capability_routing.py:168`](../../../boltrig/models/capability_routing.py) `"Whether this binding is in scope for a workspace"`;
[`boltrig/models/capability_routing.py:203`](../../../boltrig/models/capability_routing.py) `"def applies(self, version: int, operation_class: str"`.)

`CapabilityBinding.serves` fails closed: an unbound caller (`workspace_id is None`)
never matches a workspace-scoped binding
([`boltrig/models/capability_routing.py:172`](../../../boltrig/models/capability_routing.py) `"unbound caller (``workspace_id`` None) never matches a workspace-scoped"`).
A `RoutingPolicy` with `scope == "workspace"` and no `workspace_id` (or the
converse) raises at construction
([`boltrig/models/capability_routing.py:201`](../../../boltrig/models/capability_routing.py) `"workspace policies require a workspace id"`).

A capability is addressed `id@version`; a bare id means the newest live version and
a malformed pin degrades to "any live version" rather than silently routing
somewhere else
([`boltrig/models/capability_routing.py:56`](../../../boltrig/models/capability_routing.py) `"Split ``crm.contact.search@1`` into its id and pinned version"`).

The `ExecutionPlan` the router produces carries `capability_id`,
`capability_version`, `operation_class`, one `PlanTarget`, and `selected_by`
(`workspace_policy` / `tenant_policy` / `only_eligible`)
([`boltrig/kernel/routing.py:81`](../../../boltrig/kernel/routing.py) `"class ExecutionPlan:"`).
`PlanTarget.consequence_override` may only ever RAISE consequence, never lower it
([`boltrig/kernel/routing.py:74`](../../../boltrig/kernel/routing.py) `"A binding may only ever RAISE it"`).

### Errors and their transport codes

Every failure the chokepoint can produce is one of these, and the `reason` string
is what lands in the audit row's `status` column
([`boltrig/models/errors.py:3`](../../../boltrig/models/errors.py) `"These map 1:1 to the dispatch contract (S7.1)"`).

| error | code | reason | raised by |
| --- | --- | --- | --- |
| `BindingNotFound` | 404 | `binding_not_found` | resolve; unknown target_type |
| `RouteRequired` | 409 | `route_required` | router, two eligible destinations |
| `GrantMissing` | 403 | `grant_missing` | `GrantChecker.check` |
| `SchemaValidationError` | 400 | `schema_invalid` | input and output validation |
| `IdempotencyConflict` | 409 | `idempotency_conflict` | claim / start / complete |
| `ApprovalNotHoldable` | 409 | `approval_not_holdable` | gate, no redeemer lane |
| `HITLStateConflict` | 409 | `hitl_state_conflict` | a spent approval replayed |
| `PendingHuman` | 202 | `pending_human` | gate, and `chat.ask_user` |
| `RateLimited` | 429 | `rate_limited` | limiter, and adapter RATE_LIMITED |
| `CredentialResolution` | 502 | `credential_resolution_failed` | resolver |
| `AdapterFailure` | 400/403/404/409/502 | `adapter_*` | `adapter_errors.adapter_failure` |
| `DegradedMode` | 503 | `degraded` | `_degrade_or_fail` |

`PendingHuman` and `DegradedMode` are control-flow signals carrying a payload, not
failures ([`boltrig/models/errors.py:4`](../../../boltrig/models/errors.py) `"``PendingHuman`` and ``DegradedMode`` are control-flow"`).
Both subclass `BoltrigError`, and dispatch's handler order is
`PendingHuman`, `DegradedMode`, `BoltrigError`, `Exception`, which is the only
order that gives each its own status
([`boltrig/kernel/dispatch.py:397`](../../../boltrig/kernel/dispatch.py) `"except PendingHuman as e:"` through
[`boltrig/kernel/dispatch.py:424`](../../../boltrig/kernel/dispatch.py) `"except Exception as e:  # adapter/agent crash"`).

## Control flow

### The doctrine sentence, and what the code actually does

`AGENTS.md` states the fixed order as
`resolve verb+binding -> validate params -> grant check -> idempotency claim -> HITL gate -> rate limit -> resolve credential -> execute -> validate output -> audit`
([`AGENTS.md:21`](../../../AGENTS.md) `"ONE chokepoint. Every external action goes through"`).
`dispatch.py`'s own module docstring repeats that order verbatim
([`boltrig/kernel/dispatch.py:7`](../../../boltrig/kernel/dispatch.py) `"validate params          (SchemaValidationError, SEC-21)"`
then [`boltrig/kernel/dispatch.py:8`](../../../boltrig/kernel/dispatch.py) `"grant check              (GrantMissing, SEC-07)"`).

**The code runs grant check BEFORE param validation.** This is a real divergence,
and it is deliberate, argued and load-bearing, but neither `AGENTS.md` nor the
module docstring above the function records it:

- [`boltrig/kernel/dispatch.py:507`](../../../boltrig/kernel/dispatch.py) `"# 2. grant check (SEC-07) BEFORE validation"`
- [`boltrig/kernel/dispatch.py:511`](../../../boltrig/kernel/dispatch.py) `"# 3. validate params (SEC-21)"`

The reason is disclosure: a routed call is validated against the SOURCE
OPERATION's input schema, and the rejection hands the caller that schema's field
names and its digest, so validating first described a verb to a caller who may not
call it, using the capability name as the way in
([`boltrig/kernel/routing.py:250`](../../../boltrig/kernel/routing.py) `"THE CHECK PRECEDES SCHEMA VALIDATION, and that order is not tidiness"`).
The SEC-21 invariant text survives the reversal because a grant check has no
dispatch side effect: `"Verb params are schema-validated before any dispatch side effect"`
([`tests/invariants.yaml:940`](../../../tests/invariants.yaml) `"Verb params are schema-validated before any dispatch side effect"`).

`docs/ARCHITECTURE.md` is further from the code than the docstring is. Its table
puts validation at 2 and grants at 3 (reversed, as above) AND puts idempotency
replay at step 6, after the HITL gate and the rate limit
([`docs/ARCHITECTURE.md:55`](../../../docs/ARCHITECTURE.md) `"| 6 | Idempotency replay (return the prior result) |"`).
The code claims and its tests pin the opposite: a completed result replays BEFORE
the execution-side gates
([`boltrig/kernel/dispatch.py:515`](../../../boltrig/kernel/dispatch.py) `"replay before execution-side approval/rate-limit gates (SEC-15)"`;
[`tests/invariants.yaml:773`](../../../tests/invariants.yaml) `"test_replay_precedes_spent_approval_gate"`).
`README.md`'s honesty section lists the order with idempotency replay in the right
place (third) but validation before grant-check
([`README.md:211`](../../../README.md) `"resolve, schema-validate, grant-check, idempotency replay, HITL gate"`).
Three documents, three different orders, one of them the code's.

### The real ordered path

`Dispatcher.invoke` is the outer wrapper; `_invoke_inner` carries the gates.

**Step 0. Mint a call id and emit `tool_call`.**
[`boltrig/kernel/dispatch.py:380`](../../../boltrig/kernel/dispatch.py) `"call_id = uuid.uuid4().hex"`,
then [`boltrig/kernel/dispatch.py:386`](../../../boltrig/kernel/dispatch.py) `"{\"type\": \"tool_call\", \"verb\": verb, \"noun\": noun,"`.
The redacted `input` rides for the run canvas; the chat stream forwards only
`tool` / `call_id` / `args_summary`. Published to THIS run AND to the parent run,
because a chat turn dispatches under a child run id while the client follows the
root ([`boltrig/kernel/dispatch.py:288`](../../../boltrig/kernel/dispatch.py) `"Publish to THIS run and to the run that delegated to it"`).
FAILURE BRANCH: none reaches the caller. `_emit` swallows every exception
([`boltrig/kernel/dispatch.py:310`](../../../boltrig/kernel/dispatch.py) `"except Exception:  # observability must never break dispatch (P9)"`).

**Step 1. Read the tenant ceiling, resolve verb + binding (+ plan).**
[`boltrig/kernel/dispatch.py:498`](../../../boltrig/kernel/dispatch.py) `"perms = await self._store.get_tenant_permissions(tenant)"`,
then [`boltrig/kernel/dispatch.py:502`](../../../boltrig/kernel/dispatch.py) `"verb_def, binding, plan = await resolve_invocation_target("`.
The router tries `store.get_verb` first; ONLY a name that is not a stored verb is
offered to the capability resolver, so routing can add a destination where there
was a 404 and can never move an existing one
([`boltrig/kernel/routing.py:211`](../../../boltrig/kernel/routing.py) `"A stored verb id resolves exactly as it always did"`).
The `authorize` callback is the caller's grant check, passed in so the CAPABILITY
grant is checked inside the resolution, after the capability is known to exist and
before any destination is read
([`boltrig/kernel/dispatch.py:504`](../../../boltrig/kernel/dispatch.py) `"authorize=lambda name: self._grants.check(context, name, perms)"`;
[`boltrig/kernel/routing.py:160`](../../../boltrig/kernel/routing.py) `"authorize(capability_id)"`).
That order is not tidiness: `route_required` names the tenant's connections by
human-readable label, so resolving the route first would hand an ungranted caller
a list of every CRM the tenant has connected
([`boltrig/kernel/routing.py:149`](../../../boltrig/kernel/routing.py) `"resolving the route first hands an ungranted caller a list"`).
FAILURE BRANCHES, all FAIL-CLOSED:
- no bindings for the name: `BindingNotFound("unknown verb ...")`
  ([`boltrig/kernel/routing.py:158`](../../../boltrig/kernel/routing.py) `"raise BindingNotFound(f\"unknown verb '{name}'\")"`).
- bindings exist but none eligible: `BindingNotFound("... has no eligible binding")`
  ([`boltrig/kernel/routing.py:164`](../../../boltrig/kernel/routing.py) `"capability '{name}' has no eligible binding"`).
- more than one eligible and no policy selects: `RouteRequired` with the named
  destinations, never a "pick the first"
  ([`boltrig/kernel/routing.py:176`](../../../boltrig/kernel/routing.py) `"raise RouteRequired("`;
  the absence of a step 5 is stated at [`boltrig/kernel/routing.py:13`](../../../boltrig/kernel/routing.py) `"there is no step 5"`).
- a routed name whose source operation is not a stored verb, or a verb with no
  binding row: `BindingNotFound`
  ([`boltrig/kernel/routing.py:224`](../../../boltrig/kernel/routing.py) `"raise BindingNotFound(f\"unknown verb '{verb}'\")"`;
  [`boltrig/kernel/routing.py:227`](../../../boltrig/kernel/routing.py) `"verb '{verb_def.id}' has no binding"`).
Route precedence, top down: workspace policy, tenant policy, the only eligible
binding, otherwise refuse. A policy naming a disabled or deleted binding is
SKIPPED, not fatal, so a stale rule is not an outage
([`boltrig/kernel/routing.py:121`](../../../boltrig/kernel/routing.py) `"A policy pointing at a disabled or deleted binding is"`).
Unpinned addressing takes the maximum live version and then filters to it, so a
plan never straddles two contracts
([`boltrig/kernel/routing.py:166`](../../../boltrig/kernel/routing.py) `"that straddled two versions would be routing across two contracts"`).
Operation class is read from the capability's last segment, and an UNKNOWN suffix
is classed `update`, the write path that never fans out
([`boltrig/kernel/routing.py:51`](../../../boltrig/kernel/routing.py) `"Unknown suffixes are classed ``update``"`).

**Step 2. Grant check.**
[`boltrig/kernel/dispatch.py:508`](../../../boltrig/kernel/dispatch.py) `"for granted in grant_verbs(verb, verb_def, plan):"`.
For a direct verb id this is one check on the typed name; for a routed call it is
TWO, the capability id AND the source operation id, because checking only the
capability would make a canonical name a way to reach a verb the caller was never
granted ([`boltrig/kernel/routing.py:242`](../../../boltrig/kernel/routing.py) `"Every grant a routed call must hold"`).
The capability is checked UNVERSIONED on purpose: a grant list spelled with pinned
versions would silently stop matching the day a version moved
([`boltrig/kernel/routing.py:257`](../../../boltrig/kernel/routing.py) `"The capability is checked UNVERSIONED"`).
FAILURE BRANCH: `GrantMissing`, FAIL-CLOSED, from either the tenant ceiling or the
caller's own set
([`boltrig/kernel/grants.py:20`](../../../boltrig/kernel/grants.py) `"if not tenant_perms.grants.permits(verb_id):"`).

**Step 3. Validate params.**
[`boltrig/kernel/dispatch.py:512`](../../../boltrig/kernel/dispatch.py) `"_reject_if_invalid(\"params\", verb, verb_def.input_schema, params)"`.
Input and output share ONE seam, because two call sites that each built their own
error are how the output twin came to be forgotten
([`boltrig/kernel/dispatch.py:136`](../../../boltrig/kernel/dispatch.py) `"ONE seam for input and output"`).
The findings are value-free by construction: only `absolute_schema_path` (schema
keywords and property names) and `validator` checked against an allowlist. The
near misses were refused by name: `json_path`/`absolute_path` are instance-derived
(under `additionalProperties` an instance key IS a path segment), `validator_value`
is a schema VALUE, and `message` embeds the instance
([`boltrig/kernel/dispatch.py:100`](../../../boltrig/kernel/dispatch.py) `"Refused, and both look safe: ``json_path`` / ``absolute_path``"`).
Bounded: at most 10 findings, path depth 10, segment length 64
([`boltrig/kernel/schema_diagnosis.py:67`](../../../boltrig/kernel/schema_diagnosis.py) `"MAX_SCHEMA_ERRORS = 10"`).
FAILURE BRANCH: `SchemaValidationError`, carrying `errors`, `schema_digest` and
caller-only `hints`. `audit_detail()` deliberately omits `hints` because they carry
schema VALUES ([`boltrig/models/errors.py:65`](../../../boltrig/models/errors.py) `"``hints`` is deliberately ABSENT here"`).
FAIL-OPEN CASE, by design and worth naming: `if not schema: return []`
([`boltrig/kernel/dispatch.py:106`](../../../boltrig/kernel/dispatch.py) `"if not schema:"`).
A verb registered with `input_schema={}` or `output_schema={}` is validated NOT AT
ALL. `chat.ask_user` ships exactly that on the output side
([`boltrig/kernel/questions.py:81`](../../../boltrig/kernel/questions.py) `"QUESTIONS_OUTPUT_SCHEMA: dict = {}"`).

**Step 4. Idempotency claim, and the replay return.**
[`boltrig/kernel/dispatch.py:516`](../../../boltrig/kernel/dispatch.py) `"idempotency = await self._idempotency.claim("`.
No key means no claim (returns None)
([`boltrig/kernel/idempotency.py:136`](../../../boltrig/kernel/idempotency.py) `"if key is None:"`).
A key on a `disabled`-mode verb is refused outright with `IdempotencyConflict`,
which is the mechanism protecting one-time bearer results
([`boltrig/kernel/idempotency.py:139`](../../../boltrig/kernel/idempotency.py) `"verb '{verb}' does not support replay caching"`;
[`boltrig/adapters/base.py:100`](../../../boltrig/adapters/base.py) `"``disabled`` is for one-time/bearer-secret results"`).
The claim is bound to tenant, actor, `on_behalf_of`, workspace, noun, verb and the
canonical request hash, with a fresh random owner token and a 300s lease
([`boltrig/kernel/idempotency.py:141`](../../../boltrig/kernel/idempotency.py) `"claim = await self._store.idempotency_claim("`;
[`boltrig/kernel/idempotency.py:21`](../../../boltrig/kernel/idempotency.py) `"_LEASE_SECONDS = 300"`).
The hash is canonical JSON with `sort_keys`, tight separators and `allow_nan=False`;
a non-canonicalisable param set becomes a `SchemaValidationError`
([`boltrig/kernel/idempotency.py:119`](../../../boltrig/kernel/idempotency.py) `"idempotent params must be canonical JSON"`).
Outcomes:
- `ACQUIRED` -> an `IdempotencyRun` owner token, execution proceeds.
- `COMPLETED` -> the stored result is RETURNED HERE, before the approval and
  rate-limit gates ([`boltrig/kernel/dispatch.py:519`](../../../boltrig/kernel/dispatch.py) `"if isinstance(idempotency, IdempotencyReplay):"`).
- `MISMATCH`, `IN_PROGRESS`, `UNCERTAIN`, `UNCACHEABLE` -> `IdempotencyConflict`
  with a distinct message each
  ([`boltrig/kernel/idempotency.py:158`](../../../boltrig/kernel/idempotency.py) `"idempotency key is bound to a different identity or request"`).
Store semantics: an EXPIRED `claimed` lease is re-acquirable; an EXPIRED
`executing` lease transitions to `uncertain` and demands reconciliation, never a
silent re-run ([`boltrig/store/idempotency.py:77`](../../../boltrig/store/idempotency.py) `"record[\"status\"] = \"uncertain\""`).

**Step 5. The approval verdict (unlabelled in the source).**
[`boltrig/kernel/dispatch.py:523`](../../../boltrig/kernel/dispatch.py) `"gated = await requires_approval("`.
The comment numbering in `_invoke_inner` runs 1, 2, 3, 4, then jumps to `# 6. rate limit`:
there is no `# 5.`, and the verdict computation is the missing step. The verdict is
also stashed for the undo ledger
([`boltrig/kernel/dispatch.py:526`](../../../boltrig/kernel/dispatch.py) `"meta[\"gated\"] = gated  # the run-effect ledger reuses the gate's verdict"`).
`requires_approval` is three reasons in order of bluntness
([`boltrig/kernel/approval_posture.py:75`](../../../boltrig/kernel/approval_posture.py) `"Every reason one invocation must pause for a human, in one place"`):
1. the operator's always-ask list, matched against every NAME the call answers to:
   what the caller typed, the canonical capability, and the source operation
   actually executed ([`boltrig/kernel/routing.py:268`](../../../boltrig/kernel/routing.py) `"The names available WITHOUT a store read"`).
   The operator's own entries are normalised with any version pin removed, so the
   gate cannot quietly expire when a binding's version moves
   ([`boltrig/kernel/routing.py:317`](../../../boltrig/kernel/routing.py) `"An operator's always-ask entries with any version pin removed"`).
2. the same list against the capabilities resolved from STORED bindings, which is
   the half a name cannot know: the MCP face offers source-operation ids and never
   capability names, so an operator who blocked the capability blocked nothing a
   model could reach ([`boltrig/kernel/routing.py:332`](../../../boltrig/kernel/routing.py) `"The capabilities this call answers to"`).
   Only `approved` bindings count, exactly as routing counts them.
3. the binding's `consequence_override`, read for the direct spelling too, and only
   ever upwards: `if override == "high": return True`
   ([`boltrig/kernel/approval_posture.py:106`](../../../boltrig/kernel/approval_posture.py) `"if override == \"high\":"`).
   A stored `low` override is inert.
Otherwise the posture gate decides
([`boltrig/kernel/approval_posture.py:111`](../../../boltrig/kernel/approval_posture.py) `"def posture_requires_approval("`):
- NOT a delegated agent call (`on_behalf_of` empty, or `actor_tier == "human"`):
  the plain consequence gate, `consequence == HIGH`.
- a delegated agent call whose binding is an AGENT, or whose `target_ref` is
  `control`, or whose verb starts `control.`: the plain consequence gate.
- otherwise the owner's stored `agentic.approval_posture`: `always_ask` -> True,
  `full_access` -> False, `risk_based` (the default) -> `consequence == HIGH`.
A missing or malformed stored value falls back to `risk_based`
([`boltrig/kernel/approval_posture.py:34`](../../../boltrig/kernel/approval_posture.py) `"return DEFAULT_APPROVAL_POSTURE"`).

**Step 6. Rate limit and the gate, ordered by whether an approval is carried.**
[`boltrig/kernel/dispatch.py:546`](../../../boltrig/kernel/dispatch.py) `"carries_approval = gated and approval_id is not None"`.
On the leg that CARRIES an approval the throttle runs FIRST, then the gate; on
every other leg the gate runs first and the throttle after
([`boltrig/kernel/dispatch.py:548`](../../../boltrig/kernel/dispatch.py) `"if carries_approval:"`).
The reason: the gate SPENDS the approval with an atomic ANSWERED -> CONSUMED
transition that nothing can hand back, so a `RateLimited` raised after the consume
burns a human authorisation for a call the adapter provably never saw
([`boltrig/kernel/dispatch.py:529`](../../../boltrig/kernel/dispatch.py) `"so on the leg that carries one the throttle must decide FIRST"`).
The accepted cost is stated rather than glossed: a stale, unanswered or bogus
`approval_id` takes the same branch, so such a call costs a rate token while only
pending for a human
([`boltrig/kernel/dispatch.py:534`](../../../boltrig/kernel/dispatch.py) `"The name is CARRIES, not spends"`).
The narrowness is also stated: this does NOT make the whole pre-execution path
approval-safe, and the invariant is worded to match
([`boltrig/kernel/dispatch.py:542`](../../../boltrig/kernel/dispatch.py) `"invariant is worded to match: _idempotency.start (IdempotencyConflict), a"`;
[`tests/invariants.yaml:903`](../../../tests/invariants.yaml) `"That is the rate-limit gate specifically and not every pre-execution refusal"`).
FAILURE BRANCH for the whole block: any raise releases the idempotency claim first
([`boltrig/kernel/dispatch.py:558`](../../../boltrig/kernel/dispatch.py) `"await self._idempotency.release(run)"`).

Inside the gate ([`boltrig/kernel/approval_gate.py:150`](../../../boltrig/kernel/approval_gate.py) `"async def enforce_approval("`):
1. the adapter's optional `approval_context(verb, params, context)` hook is called
   for an ADAPTER binding only, and canonicalised
   ([`boltrig/kernel/approval_gate.py:114`](../../../boltrig/kernel/approval_gate.py) `"async def _resource_context("`).
2. the request fingerprint is computed over tenant, noun, verb, params VERBATIM,
   the initiator (actor, tier, on_behalf_of, workspace, run id, principal role,
   principal scope, sorted grants, sorted skills) and the resource context
   ([`boltrig/kernel/hitl_fingerprint.py:50`](../../../boltrig/kernel/hitl_fingerprint.py) `"Bind one approval to one canonical action and authenticated initiator"`).
   Non-string dict keys, non-finite floats, non-JSON values and NFC key collisions
   all raise ([`boltrig/kernel/hitl_fingerprint.py:30`](../../../boltrig/kernel/hitl_fingerprint.py) `"normalised key collision in approval context"`),
   surfacing as `BoltrigError("approval context is not canonical JSON")`.
3. a display context is built for the approver with sensitive KEYS and
   secret-shaped VALUES redacted, and a special case for
   `control.mcp_server.update` that shows only the server id
   ([`boltrig/kernel/approval_gate.py:53`](../../../boltrig/kernel/approval_gate.py) `"def _approval_display_inputs(verb: str, params"`).
4. if an `approval_id` was supplied, `consume_approved_by` runs. It returns the
   respondent ONLY after every check passes and the CAS succeeds: status must be
   ANSWERED, `timeout_at` must not have passed, type must be APPROVAL, `verb` must
   match exactly, the fingerprint must match under `hmac.compare_digest`, the
   response decision must be approving, and `store.consume_hitl` must win the
   transition ([`boltrig/kernel/hitl.py:289`](../../../boltrig/kernel/hitl.py) `"Consume a valid approval and return its authenticated respondent"`).
5. if that yields nothing and the id names an already-CONSUMED request, the gate
   raises `HITLStateConflict` rather than silently re-pending, so a retry after a
   successful consume cannot loop on fresh 202s
   ([`boltrig/kernel/approval_gate.py:196`](../../../boltrig/kernel/approval_gate.py) `"approval '{approval_id}' was already consumed"`).
6. before minting anything, `_require_redeemer` demands that a redeeming lane can
   be NAMED from the record, else `ApprovalNotHoldable` and nothing is created: no
   request row, no seal, no checkpoint
   ([`boltrig/kernel/approval_gate.py:132`](../../../boltrig/kernel/approval_gate.py) `"Refuse to MINT an approval no lane could ever redeem"`).
   The lanes are `caller` (no run id at all), `held_write` (the pause is
   recordable), and `interpreter` (an already-checkpointed run); anything else is
   None ([`boltrig/kernel/held_call.py:118`](../../../boltrig/kernel/held_call.py) `"Name the lane that will redeem an approval minted for THIS call"`).
7. the request is created with the manifest's timeout stamped on it, then
   `PendingHuman(request.id)` is raised
   ([`boltrig/kernel/approval_gate.py:212`](../../../boltrig/kernel/approval_gate.py) `"timeout_seconds=hitl.approval_timeout_seconds"`).
8. on success the context is REPLACED with approval evidence in `extra`, stamped
   only after the exact consume CAS succeeded
   ([`boltrig/kernel/approval_gate.py:221`](../../../boltrig/kernel/approval_gate.py) `"Trusted evidence stamped only after the exact consume CAS succeeds"`).

**Step 6a. Take ownership of the idempotency claim.**
[`boltrig/kernel/dispatch.py:561`](../../../boltrig/kernel/dispatch.py) `"await self._idempotency.start(run)"`.
FAILURE BRANCH: `IdempotencyConflict("idempotency claim ownership was lost")`,
raised AFTER any approval consume (named in the invariant as an accepted gap).

**Step 6b. The governed built-in `chat.ask_user`.**
[`boltrig/kernel/dispatch.py:580`](../../../boltrig/kernel/dispatch.py) `"if verb == QUESTIONS_VERB:"`.
It reaches here only after schema validation, the grant check and the approval
gate, so it is fully governed like any verb; its effect is to PAUSE and it never
touches an adapter or an agent
([`boltrig/kernel/dispatch.py:576`](../../../boltrig/kernel/dispatch.py) `"so it is fully governed like any verb. Its effect is"`).
`_ask_user` creates a QUESTION HITL bound to the run and the work item (a chat
turn's work item id IS its run id), emits a `question` run event and raises
`PendingHuman` ([`boltrig/kernel/dispatch.py:314`](../../../boltrig/kernel/dispatch.py) `"Create a QUESTION HITL, emit a ``question`` run event"`).
With `secure: true` and a `purpose` label the question is marked secure so the
answer route seals the answer as a run+purpose-scoped credential and only the
REFERENCE enters the run
([`boltrig/kernel/dispatch.py:328`](../../../boltrig/kernel/dispatch.py) `"SEC-181 secure input: the QUESTION is marked secure"`).
Its verb is seeded LOW consequence with a native AGENT binding
(`target_ref = "native:questions"`) that is a label for the audit row, never a
loadable adapter ([`boltrig/kernel/questions.py:113`](../../../boltrig/kernel/questions.py) `"a label for the audit row, never a loadable adapter"`).
The registry declines to overwrite an AGENT binding on re-registration, which is
what stops an adapter restart from disabling this pause
([`boltrig/kernel/registry.py:172`](../../../boltrig/kernel/registry.py) `"AN AGENT BINDING IS NEVER AN ADAPTER'S TO REPLACE"`).

**Step 7. Execute.**
Adapter path ([`boltrig/kernel/dispatch.py:584`](../../../boltrig/kernel/dispatch.py) `"if binding.target_type == TargetType.ADAPTER:"`):
1. the adapter is fetched through the store-authoritative provider. A missing
   adapter RECORD is authoritative absence: the loader is unloaded, the credential
   binding is cleared, and None is returned
   ([`boltrig/kernel/adapter_provider.py:19`](../../../boltrig/kernel/adapter_provider.py) `"A replica may retain an instance after another replica deleted"`).
   A generated adapter is returned only when `record.activated`; an MCP consumer
   only when its lifecycle row is `active`
   ([`boltrig/kernel/adapter_provider.py:54`](../../../boltrig/kernel/adapter_provider.py) `"if lifecycle is not None and lifecycle.state == \"active\""`).
2. `adapter is None` -> `_degrade_or_fail(reason="adapter_not_loaded")` BEFORE any
   credential is touched ([`boltrig/kernel/dispatch.py:693`](../../../boltrig/kernel/dispatch.py) `"if adapter is None:"`).
3. the static credential is resolved for the acting identity, `on_behalf_of` when
   an agent runs for somebody, else `actor`, because `on_behalf_of` is None for a
   person logged in directly and reading it alone would silently serve the ORG
   credential to every console user
   ([`boltrig/kernel/credentials.py:144`](../../../boltrig/kernel/credentials.py) `"``owner`` is the acting identity"`).
4. a per-run adapter bearer, if one is sealed for THIS run and THIS adapter and
   THIS owner, OVERRIDES the static service credential, so the downstream service
   enforces the caller's grants rather than the adapter's own token
   ([`boltrig/kernel/dispatch.py:705`](../../../boltrig/kernel/dispatch.py) `"override = await self._creds.resolve_run_scoped_credential("`).
   Absent, the static credential stands: fail-safe for dev and non-passthrough
   tenants ([`boltrig/kernel/credentials.py:335`](../../../boltrig/kernel/credentials.py) `"or ``None`` when none is sealed"`).
5. params carrying a run-scoped credential REFERENCE are resolved to material on a
   COPY, so the params the agent authored, the events and the audit only ever held
   the reference ([`boltrig/kernel/dispatch.py:716`](../../../boltrig/kernel/dispatch.py) `"resolved_params = await self._creds.resolve_run_scoped_params("`).
6. `adapter.execute(verb_def.id, resolved_params, credential, context)`. Note the
   verb passed is `verb_def.id`, the SOURCE OPERATION, not the caller's spelling.
7. result mapping: `RATE_LIMITED` -> `RateLimited` with the adapter's
   `retry_after_seconds`; `UNAVAILABLE` -> `_degrade_or_fail("backend_unavailable")`;
   anything else -> `adapter_failure(err)` mapping the class to 404/403/400/409/502
   ([`boltrig/kernel/adapter_errors.py:8`](../../../boltrig/kernel/adapter_errors.py) `"_TRANSPORT_ERRORS = {"`).
   A failed result with NO error detail becomes a 502 `adapter_internal`
   ([`boltrig/kernel/adapter_errors.py:21`](../../../boltrig/kernel/adapter_errors.py) `"adapter returned no error detail"`).

Agent path ([`boltrig/kernel/dispatch.py:729`](../../../boltrig/kernel/dispatch.py) `"async def _execute_agent("`):
no invoker wired -> `_degrade_or_fail("agent_runtime_absent")`; a not-ok result ->
`_degrade_or_fail("agent_failed")`. NO credential is resolved on this path at all.

Unknown target type -> `BindingNotFound(f"unknown target_type '{binding.target_type}'")`,
FAIL-CLOSED ([`boltrig/kernel/dispatch.py:588`](../../../boltrig/kernel/dispatch.py) `"else:  # fail-closed on an unknown target type"`).

`_degrade_or_fail` raises either way: a verb with no `degraded_mode` gets a bare
`BoltrigError(f"verb '{verb_def.id}' unavailable ({reason})")`, and one with a
declared shape gets `DegradedMode` carrying `output["_degraded"] = {reason, strategy}`
([`boltrig/kernel/dispatch.py:744`](../../../boltrig/kernel/dispatch.py) `"Produce a degraded result if the verb defines one, else fail (P9)"`).

**Step 8. Validate output.**
[`boltrig/kernel/dispatch.py:595`](../../../boltrig/kernel/dispatch.py) `"_reject_if_invalid(\"output\", verb, verb_def.output_schema, output)"`.
The comment names why this half matters more: the instance here is the adapter's
RESPONSE, which is where credentials live
([`boltrig/kernel/dispatch.py:593`](../../../boltrig/kernel/dispatch.py) `"it is the worse half: the instance here is the adapter's"`).
FAILURE BRANCH: `SchemaValidationError` AFTER the adapter already ran. The claim is
released ([`boltrig/kernel/dispatch.py:597`](../../../boltrig/kernel/dispatch.py) `"await self._idempotency.release(run)"`)
and `tests/kernel/test_chokepoint_order.py::test_out_of_schema_adapter_output_is_rejected`
asserts the adapter ran exactly once.

**Step 9. Complete the claim; secret-shaped output becomes uncacheable.**
[`boltrig/kernel/dispatch.py:601`](../../../boltrig/kernel/dispatch.py) `"await self._idempotency.complete(run, output)"`.
`secret_shaped` walks dicts, lists and strings; a sensitive KEY anywhere, a value
starting `bearer `/`basic `/`sk-`/`ghp_`/`github_pat_`/`xoxb-`/`xoxp-`/`boltrig_invite_`,
or a three-part JWT-shaped token taints the whole output
([`boltrig/kernel/idempotency.py:93`](../../../boltrig/kernel/idempotency.py) `"def secret_shaped(value: Any) -> bool:"`).
Key normalisation handles acronyms with two ZERO-WIDTH regexes, deliberately, after
CodeQL flagged the greedy form as polynomial ReDoS on an ADAPTER-CHOSEN key
([`boltrig/kernel/idempotency.py:67`](../../../boltrig/kernel/idempotency.py) `"BOTH PATTERNS ARE ZERO-WIDTH ON PURPOSE"`).

**Step 9a. The author-tier crossing row.**
For any verb starting `control.`, the active author-tier user count is measured
before AND after the call, and a row is written ONLY on an actual 1 <-> 2 crossing
([`boltrig/kernel/dispatch.py:632`](../../../boltrig/kernel/dispatch.py) `"Announce a crossing of the 1<->2 author boundary"`).
It exists because at exactly one active author the sole-author bootstrap exemption
is live and self-approval is lawful; at two it is not, so the count is the tenant's
approval REGIME and it once changed silently
([`boltrig/kernel/dispatch.py:637`](../../../boltrig/kernel/dispatch.py) `"count is not a detail of the user record, it is the tenant's approval"`).
Measured by COUNTING rather than by knowing which verbs touch users, because the
crossing that matters is the one made by the verb nobody thought of
([`boltrig/kernel/dispatch.py:646`](../../../boltrig/kernel/dispatch.py) `"measured by COUNTING rather than by knowing which verbs touch"`).
FAILURE BRANCH: swallowed and logged, because the action already ran and the key is
COMPLETED ([`boltrig/kernel/dispatch.py:603`](../../../boltrig/kernel/dispatch.py) `"Observability, not correctness"`).

**Step 10. Audit, always.**
The `finally` block runs on every path
([`boltrig/kernel/dispatch.py:428`](../../../boltrig/kernel/dispatch.py) `"finally:"`).
It emits the paired `tool_result` frames (and a `voice_tone` frame when the verb
reported one), computes latency, reads `target_adapter` out of `meta`, derives
`(resource, resource_id)`, defaults `detail["params"]` to the key-name summary, and
writes ONE `AuditEvent`
([`boltrig/kernel/dispatch.py:445`](../../../boltrig/kernel/dispatch.py) `"await self._audit.write("`).
`pending_human` skips the result frames because `_emit_pause` already published its
own event ([`boltrig/kernel/dispatch.py:434`](../../../boltrig/kernel/dispatch.py) `"if status != \"pending_human\":"`).
The audit `status` is `ok`, `pending_human`, `degraded`, the `BoltrigError.reason`,
or `error` for a bare adapter crash whose detail is the exception TYPE NAME only
([`boltrig/kernel/dispatch.py:426`](../../../boltrig/kernel/dispatch.py) `"detail = {\"message\": type(e).__name__}"`).

**Step 10a. Run-effect ledger (success path only).**
[`boltrig/kernel/dispatch.py:394`](../../../boltrig/kernel/dispatch.py) `"await record_run_effect(self._store, verb, params, output,"`.
Recorded when the call was GATED, or when the inverse registry knows the verb; a
run with no run id and a revert run record nothing
([`boltrig/kernel/run_effect_recorder.py:36`](../../../boltrig/kernel/run_effect_recorder.py) `"async def record_run_effect("`).
The inverse registry ships EMPTY, so every verb starts not-undoable and coverage
grows verb by verb without a single lying default
([`boltrig/kernel/effect_inverses.py:20`](../../../boltrig/kernel/effect_inverses.py) `"EMPTY, so every verb starts not-undoable"`).
`inverse_for` fails closed twice: unregistered verb -> None, and a builder that
RAISES -> None ([`boltrig/kernel/effect_inverses.py:53`](../../../boltrig/kernel/effect_inverses.py) `"Fail-closed twice over"`).
Builders are registered from an adapter's optional `inverses()` at
`register_adapter`, last-wins
([`boltrig/kernel/__init__.py:142`](../../../boltrig/kernel/__init__.py) `"for verb_id, builder in declared_inverses().items():"`).

**Step 10b. The held call, on an approval pause.**
`except PendingHuman` announces the pause to this run AND the parent, then makes it
DURABLE ([`boltrig/kernel/dispatch.py:400`](../../../boltrig/kernel/dispatch.py) `"Announce the pause, and RECORD it so the approved call can be replayed"`).
Only an APPROVAL is held; a QUESTION has no held write to replay and sealing its
params would put a plain question's inputs under a secret kind
([`boltrig/kernel/dispatch.py:272`](../../../boltrig/kernel/dispatch.py) `"Only an APPROVAL is held"`).
The record is two things: a `held:<call_id>` PAUSED checkpoint on the ROOT run
carrying the request id, and the canonical `{noun, verb, params, ctx}` sealed as a
run-scoped credential under `HELD_CALL_KIND`, with the params VERBATIM because the
fingerprint binds them verbatim
([`boltrig/kernel/held_call.py:182`](../../../boltrig/kernel/held_call.py) `"The params VERBATIM: the approval fingerprint binds them verbatim"`).
A delegated call writes a SECOND pointer checkpoint on the child run carrying the
root run id, never params
([`boltrig/kernel/held_call.py:161`](../../../boltrig/kernel/held_call.py) `"Two checkpoint rows when the call is delegated"`).
Unlike the event emit, a failure here is NOT swallowed
([`boltrig/kernel/dispatch.py:269`](../../../boltrig/kernel/dispatch.py) `"a failure here is NOT swallowed: the relay is"`).

### The RecordingDispatcher wrapper

The composition root wraps the dispatcher in a trajectory recorder AFTER
construction ([`boltrig/kernel/__init__.py:114`](../../../boltrig/kernel/__init__.py) `"self.dispatcher = RecordingDispatcher(self.dispatcher, self.trajectory)"`).
It is a decorator rather than an edit to the chokepoint, and it delegates BOTH
reads and writes so `k.dispatcher._creds = rec` lands on the real dispatcher rather
than the wrapper ([`boltrig/kernel/trajectory.py:175`](../../../boltrig/kernel/trajectory.py) `"WRITES GO THROUGH TOO, or the proxy is only half transparent"`).
That is why `set_agent_invoker` setting `self.dispatcher._agent_invoker` still
reaches the inner object. A disabled recorder costs one attribute lookup
([`boltrig/kernel/trajectory.py:200`](../../../boltrig/kernel/trajectory.py) `"if not self._recorder.enabled:"`).

## Data

### Tables this subsystem reads or writes

| table | key | written by | notes |
| --- | --- | --- | --- |
| `nouns` | `(tenant_id, id)` | registry | `is_active` gate |
| `verbs` | `(tenant_id, id)` | registry | schemas, consequence, idempotency_mode |
| `verb_bindings` | `(verb_id, tenant_id)` | registry, `bind_verb_to_agent` | 1:1 by design |
| `provider_connections` | `(tenant_id, id)` | capability records | no adapter uniqueness |
| `source_operations` | `(tenant_id, id)` | registry ingestion | carries `schema_digest` |
| `capability_bindings` | `(tenant_id, binding_id)` | capability records | MANY per capability |
| `routing_policies` | `(tenant_id, id)` | control plane | one per capability/scope/class |
| `tenant_permissions` | `tenant_id` | manifest | the ceiling |
| `idempotency_keys` | `(tenant_id, key)` | coordinator | 5 statuses, lease |
| `hitl_requests` / `hitl_responses` | id | HITL manager | fingerprint + digest |
| `run_checkpoints` | run + step | held-call recorder | `held:` prefix reserved |
| `credential_refs` | `(tenant_id, id)` | resolver, held-call | `data` is SEALED |
| `audit_log` | `(tenant_id, seq)` UNIQUE | audit writer | hash-chained |
| `audit_outbox` | serial | audit writer on fault | payload only, no chain fields |
| `security_log` | `(tenant_id, seq)` UNIQUE | security writer | distinct stream |
| `run_effects` | `(tenant_id, run_id, seq)` | run-effect recorder | undo ledger |

DDL: [`boltrig/store/schema.sql:28`](../../../boltrig/store/schema.sql) `"CREATE TABLE IF NOT EXISTS verbs ("`,
[`boltrig/store/schema.sql:46`](../../../boltrig/store/schema.sql) `"CREATE TABLE IF NOT EXISTS verb_bindings ("`,
[`boltrig/store/schema.sql:123`](../../../boltrig/store/schema.sql) `"CREATE TABLE IF NOT EXISTS capability_bindings ("`,
[`boltrig/store/schema.sql:542`](../../../boltrig/store/schema.sql) `"CREATE TABLE IF NOT EXISTS audit_log ("`,
[`boltrig/store/schema.sql:590`](../../../boltrig/store/schema.sql) `"CREATE TABLE IF NOT EXISTS audit_outbox ("`,
[`boltrig/store/schema.sql:653`](../../../boltrig/store/schema.sql) `"CREATE TABLE IF NOT EXISTS idempotency_keys ("`,
[`boltrig/store/schema.sql:713`](../../../boltrig/store/schema.sql) `"CREATE TABLE IF NOT EXISTS credential_refs ("`,
[`boltrig/store/schema.sql:2874`](../../../boltrig/store/schema.sql) `"CREATE TABLE IF NOT EXISTS run_effects ("`.

### Indexes worth naming

`capability_bindings_claim_idx` is a UNIQUE partial index on
`(tenant_id, capability_id, capability_version, connection_id, source_operation_id)`
where `status <> 'retired'`, so a re-import updates the binding it already made
instead of growing a duplicate route
([`boltrig/store/schema.sql:157`](../../../boltrig/store/schema.sql) `"CREATE UNIQUE INDEX IF NOT EXISTS capability_bindings_claim_idx"`).
`audit_log` carries `UNIQUE (tenant_id, seq)`, which is the multi-process backstop
behind the writer's per-tenant asyncio lock
([`boltrig/kernel/audit.py:321`](../../../boltrig/kernel/audit.py) `"for a multi-process deployment the Postgres"`).
`run_effects` carries CHECK constraints bounding `summary` to 512 bytes and
`inverse_params` to 16KB
([`boltrig/store/schema.sql:2888`](../../../boltrig/store/schema.sql) `"CHECK (octet_length(summary) <= 512)"`).

### Encryption and append-only posture

`credential_refs.data` is the SEALED reference envelope (ciphertext), unsealed
transparently on read by the store seam
([`boltrig/store/schema.sql:718`](../../../boltrig/store/schema.sql) `"-- the SEALED reference envelope (ciphertext)"`;
[`boltrig/kernel/credentials.py:6`](../../../boltrig/kernel/credentials.py) `"the store seam envelope-SEALS at rest"`).
`audit_log`, `security_log`, `config_revisions` and `execution_events` have
`UPDATE` and `DELETE` REVOKEd from the app role, so a compromised app role cannot
rewrite the chains
([`boltrig/store/rls.sql:37`](../../../boltrig/store/rls.sql) `"strip write-back rights and leave SELECT/INSERT"`).
Every table above is inside the FORCE-RLS tenant fence keyed on the per-transaction
`app.tenant_id` GUC, which yields zero rows when null
([`boltrig/store/rls.sql:78`](../../../boltrig/store/rls.sql) `"'nouns','verbs','verb_bindings','adapters','skills'"`;
[`boltrig/store/rls.sql:88`](../../../boltrig/store/rls.sql) `"'audit_outbox',"`;
[`boltrig/store/rls.sql:137`](../../../boltrig/store/rls.sql) `"'provider_connections','source_operations','capability_bindings'"`).

### The hash chain

Each row hashes `HMAC-SHA256(key, canonical(event))` over tenant, seq, ts, run ids,
actor, tier, depth, action type, noun, verb, target adapter, on_behalf_of, status,
latency, tokens, cost, skills, detail, prev_hash, plus the five Opbox-depth fields
FOLDED IN ONLY WHEN NON-NONE so a pre-enrichment row canonicalises byte-for-byte as
before ([`boltrig/kernel/audit.py:107`](../../../boltrig/kernel/audit.py) `"A stable serialisation of the fields the hash covers"`).
Key epochs let a leaked key be rotated without losing verification of the history
it sealed: a retired key is bounded by the seq at which it was retired, and exactly
one key verifies each row, never "try them all"
([`boltrig/kernel/audit.py:76`](../../../boltrig/kernel/audit.py) `"The ONE key a row at ``seq`` is allowed to verify under"`).
The bound is load-bearing because one of the retired keys is a PUBLIC constant in
this repository ([`boltrig/kernel/audit.py:46`](../../../boltrig/kernel/audit.py) `"here one of them is a PUBLIC constant"`).
`verify_chain` re-derives the ENTIRE chain from seq 1 ascending, and returns at the
FIRST bad row, which is why segment verification with an explicit `seed_prev`
exists ([`boltrig/kernel/audit.py:233`](../../../boltrig/kernel/audit.py) `"Re-derive a tamper-evidence hash chain for a tenant from seq 1 upward"`).
A misbehaving scan page that does not advance returns `(False, seq)` rather than
looping forever ([`boltrig/kernel/audit.py:272`](../../../boltrig/kernel/audit.py) `"a misbehaving scan page must never loop forever"`).

### Migrations

- `0024_bound_idempotency` added identity/request binding and TRUNCATEd the replay
  cache, deliberately invalidating cached outputs that predate identity binding
  ([`migrations/versions/0024_bound_idempotency.py:3`](../../../migrations/versions/0024_bound_idempotency.py) `"Existing cached outputs are deliberately invalidated"`).
- `0077_audit_outbox` created the deferral table.
- `0079_capability_routing_shard` added the four capability tables, additive only,
  no existing table altered
  ([`migrations/versions/0079_capability_routing_shard.py:24`](../../../migrations/versions/0079_capability_routing_shard.py) `"Additive only. ``store/schema.sql`` is edited in lockstep"`).
- `0085_run_effect_ledger` created `run_effects`.

`make migration-parity` compares the Alembic head with `schema.sql` on a disposable
PostgreSQL ([`Makefile:343`](../../../Makefile) `"migration-parity: ## Compare Alembic head with schema.sql"`).
AGENTS.md still lists "an ordered alembic set" among the SEAMS
([`AGENTS.md:64`](../../../AGENTS.md) `"gateway, an on-box model, the production Codex cutover, and an ordered alembic"`), and the
version directory does carry two pairs of duplicate numeric prefixes
(`0077_audit_outbox` / `0077_trajectory`, `0078_capability_presentation_fields` /
`0078_scoped_integration_connections`) reconciled by
`0081_merge_capability_and_integration_scope`.

### Retention

The run-event relay keeps at most `backlog` (default 500) events per stream and
forgets the oldest CLOSED streams beyond `max_closed` (default 256)
([`boltrig/kernel/events.py:90`](../../../boltrig/kernel/events.py) `"def __init__(self, backlog: int = 500, max_closed: int = 256)"`).
A forgotten run's events snapshot is empty and the durable record is the persisted
conversation message plus the audit trail
([`boltrig/kernel/events.py:18`](../../../boltrig/kernel/events.py) `"A forgotten run's /v1/runs/{id}/events snapshot is"`).
There is NO documented retention on `audit_log`, `security_log`, `idempotency_keys`
or `run_effects` in the DDL. Bounded: `rg -n "retention|DELETE FROM audit_log|purge" boltrig/store/schema.sql`
returns nothing for those tables (pinned tree).

## Configuration surface

| knob | read at | default | what breaks if wrong |
| --- | --- | --- | --- |
| `BOLTRIG_AUDIT_HMAC_KEY` | module import, [`boltrig/kernel/audit.py:28`](../../../boltrig/kernel/audit.py) `"_HMAC_KEY = os.environ.get(\"BOLTRIG_AUDIT_HMAC_KEY\""` | `dev-insecure-audit-key` | the chain is forgeable; boot refuses in prod |
| `BOLTRIG_AUDIT_HMAC_RETIRED` | per verification, [`boltrig/kernel/audit.py:63`](../../../boltrig/kernel/audit.py) `"raw = os.environ.get(_RETIRED_ENV"` | unset | rotated-away history stops verifying |
| `BOLTRIG_AUDIT_OUTBOX_INTERVAL` | [`boltrig/kernel/audit_outbox.py:49`](../../../boltrig/kernel/audit_outbox.py) `"The drain interval in seconds; <= 0 disables the janitor."` | 60.0s; `<= 0` disables | deferred rows never re-enter the chain |
| `REDIS_URL` | [`boltrig/api/bootstrap.py:423`](../../../boltrig/api/bootstrap.py) `"counter = build_counter(os.environ.get(\"REDIS_URL\"))"` | unset -> in-memory counter | every rate bound becomes per-process and per-boot |
| `BOLTRIG_EVENT_RELAY_NAMESPACE` | [`boltrig/api/bootstrap.py:427`](../../../boltrig/api/bootstrap.py) `"namespace=os.environ.get(\"BOLTRIG_EVENT_RELAY_NAMESPACE\", \"default\")"` | `default` | stream key collisions across deployments |
| `BOLTRIG_TRAJECTORY` | `TrajectoryRecorder` | off | verbatim turn recording on or off |
| manifest `hitl.blocking_verbs` | [`boltrig/config/manifest.py:409`](../../../boltrig/config/manifest.py) `"return set(self.hitl.blocking_verbs)"` | empty set | the operator always-ask gate fires or does not |
| manifest `hitl.approval_timeout_seconds` | [`boltrig/api/bootstrap.py:447`](../../../boltrig/api/bootstrap.py) `"approval_timeout_seconds=manifest.hitl.approval_timeout_seconds"` | 86400 when the key is absent ([`boltrig/config/manifest.py:213`](../../../boltrig/config/manifest.py) `"APPROVAL_TIMEOUT_SECONDS_FLOOR = 86400"`); 3600 in `manifest.example.yaml` | a Kernel built with no manifest passes None, and None means a gate-minted approval NEVER expires |
| manifest `development_posture` | [`boltrig/api/bootstrap.py:448`](../../../boltrig/api/bootstrap.py) `"development_posture=manifest.development_posture"` | none | approver eligibility fan-out |
| manifest `models.prices` | `CostAccountant.set_prices` | empty -> tier default | over/under-billing; a hard-stop trips early or late |
| per-verb `rate_limit` (adapter `VerbSpec`) | [`boltrig/kernel/registry.py:200`](../../../boltrig/kernel/registry.py) `"rate_limit=RateLimit(**rl) if rl else None"` | None -> NO limit | an unlimited verb |
| per-user `agentic.approval_posture` | [`boltrig/kernel/approval_posture.py:18`](../../../boltrig/kernel/approval_posture.py) `"APPROVAL_POSTURE_SETTING = \"agentic.approval_posture\""` | `risk_based` ([`boltrig/kernel/approval_posture.py:27`](../../../boltrig/kernel/approval_posture.py) `"DEFAULT_APPROVAL_POSTURE = ApprovalPosture.RISK_BASED"`) | `full_access` removes the HIGH-consequence prompt |

Notes that matter operationally:

- `_HMAC_KEY` is captured AT MODULE IMPORT
  ([`boltrig/kernel/audit.py:28`](../../../boltrig/kernel/audit.py) `"_HMAC_KEY = os.environ.get(\"BOLTRIG_AUDIT_HMAC_KEY\""`),
  so a key rotation needs a process restart, while `BOLTRIG_AUDIT_HMAC_RETIRED` is
  parsed per verification so an epoch is picked up without one
  ([`boltrig/kernel/audit.py:58`](../../../boltrig/kernel/audit.py) `"Parsed per verification rather than at import"`).
- A placeholder audit key with a production signal is a FATAL boot refusal, and the
  predicate knows every placeholder the project has ever shipped, not just the
  in-source default ([`boltrig/api/boot_guards.py:58`](../../../boltrig/api/boot_guards.py) `"if signal is not None and is_placeholder_secret(key):"`).
- `build_counter` falls back to the in-memory counter with no `REDIS_URL`, and
  argues that this is not a silent production downgrade because production
  readiness independently REQUIRES Redis
  ([`boltrig/kernel/ratelimit.py:80`](../../../boltrig/kernel/ratelimit.py) `"The counter the kernel should use: Redis when a URL is configured"`).
  The module docstring records that the Redis backend was ASSERTED but constructed
  nowhere for a long time, so every bound was per-process and per-boot including
  the 2FA brute-force bound
  ([`boltrig/kernel/ratelimit.py:7`](../../../boltrig/kernel/ratelimit.py) `"That sentence was FALSE for a long time"`).

## PROCESS

### Bringing the chokepoint up

`build_kernel` / `_build_kernel` is the composition root
([`boltrig/api/bootstrap.py:410`](../../../boltrig/api/bootstrap.py) `"Construct and fully wire a Kernel (store, adapters, capabilities, invoker)"`).
Order: refuse a placeholder audit key under a production signal, build the store,
build the shared Redis counter and event relay from `REDIS_URL`, load the manifest,
construct `Kernel(...)` with `blocking_verbs`, `approval_timeout_seconds` and
`development_posture` threaded from the manifest, seed from the manifest, then
attach the fleet's agent invoker. With no manifest the process boots a minimal demo
tenant and a default seed
([`boltrig/api/bootstrap.py:459`](../../../boltrig/api/bootstrap.py) `"no manifest found; booted minimal demo tenant"`).

Note the fail-open shape here: `approval_timeout_seconds` is threaded ONLY on the
manifest branch. On the no-manifest branch `HITLManager.approval_timeout_seconds`
stays None, and `enforce_approval` then stamps `timeout_seconds=None`, so
`HITLRequest.timeout_at` is None and the gate-minted approval never expires
([`boltrig/kernel/hitl.py:147`](../../../boltrig/kernel/hitl.py) `"timeout_at=(utcnow() + timedelta(seconds=timeout_seconds) if timeout_seconds else None)"`).

### Adding an integration (the everything-as-data procedure)

Write an adapter exposing `describe()` returning `VerbSpec` rows, and call
`kernel.register_adapter(tenant_id, adapter)`
([`boltrig/kernel/__init__.py:131`](../../../boltrig/kernel/__init__.py) `"Load an adapter and register its verbs as data (P1)"`).
That call, in order: registers with the loader, registers any declared inverse
builders, registers MCP resource specs, upserts the `AdapterRecord`, then upserts
nouns, verbs and bindings from the specs
([`boltrig/kernel/registry.py:68`](../../../boltrig/kernel/registry.py) `"Register every verb an adapter provides"`).
Two rules bite here:
- an existing AGENT binding is NEVER replaced by an adapter; ADAPTER-over-ADAPTER
  IS allowed, deliberately, because several adapters publish the same verb on
  purpose and manifest order picks the provider
  ([`boltrig/kernel/registry.py:181`](../../../boltrig/kernel/registry.py) `"ADAPTER-over-ADAPTER is deliberately still allowed"`).
- an EXTERNAL provider's operations are recorded as source operations even when
  they claim nothing; BUILTINS are deliberately excluded because ingesting thirty
  adapters' operations on every tenant at every startup is a cost with no reader
  ([`boltrig/kernel/registry.py:94`](../../../boltrig/kernel/registry.py) `"BUILTINS ARE DELIBERATELY EXCLUDED"`).
Re-pointing a verb at a reasoning agent is `KernelRegistry.bind_verb_to_agent`,
which refuses when the verb is missing or archived
([`boltrig/kernel/registry.py:247`](../../../boltrig/kernel/registry.py) `"Re-point a verb at a reasoning agent instead of an adapter"`).
Pass an `EffectLog` to receive an inverse for everything a registration changed,
built while what was displaced is still known
([`boltrig/kernel/registry.py:77`](../../../boltrig/kernel/registry.py) `"Pass ``effects`` to receive an inverse for everything this call changes"`).

### Changing anything in this area

`AGENTS.md` binds every security or correctness claim to a test marked
`@pytest.mark.invariant("NAME")` declared in `tests/invariants.yaml`, with binding
debt at 0 ([`AGENTS.md:53`](../../../AGENTS.md) `"Every security or correctness claim must be pinned to a test"`).
The gate is `make invariants` -> `scripts/check_invariants.py`
([`Makefile:474`](../../../Makefile) `"invariants: ## The K-29/K-30 binding gate"`).
The full local gate that the pre-push hook runs is `make python-quality`, which
includes `invariants lint architecture structure ... unwired-claims reachability
prose-references ... no-vacuous-greens`
([`Makefile:228`](../../../Makefile) `"python-quality: invariants lint architecture structure"`).
`make check` is explicitly NOT what CI enforces and its own help text says so
([`Makefile:223`](../../../Makefile) `"NOT what CI enforces"`).

Two gates matter specifically for this area's honesty:
- `make unwired-claims` fails when the record NAMES a mechanism no production path
  constructs, and its own docstring cites `sweep_run_scoped` as the case that
  produced it ([`scripts/check_unwired_claims.py:34`](../../../scripts/check_unwired_claims.py) `"(``sweep_run_scoped``)\". Four more modules named it as THE lifecycle seam"`).
- `make reachability` reports every function unreachable from every root
  ([`Makefile:139`](../../../Makefile) `"reachability: ## Reachability is TRANSITIVE"`).

### Diagnosing a schema rejection after the fact

The audit row stores value-free findings plus a `schema_digest`; the expectation is
DERIVED at read time. `schema_diagnosis.diagnose` returns one of three states:
`not_recorded` (row predates the order or is not a schema failure), `schema_moved`
(the recorded digest is not the current schema's, and NO diff is offered because
answering from a schema that was not in force is worse than declining), or
`diagnosed` with `keys_sent`, `missing` and `unexpected`
([`boltrig/kernel/schema_diagnosis.py:87`](../../../boltrig/kernel/schema_diagnosis.py) `"Render a recorded ``schema_invalid`` failure against the schema in force NOW"`).

### Recovering an unaudited action

An append fault does not drop the event: the scrubbed payload is enqueued to
`audit_outbox` and the event returns without seq/hash
([`boltrig/kernel/audit.py:337`](../../../boltrig/kernel/audit.py) `"DURABLE DEFERRAL (SEC-16 audit-always, 2026-08-16)"`).
The janitor drains it, re-deriving `seq`/`prev_hash`/`hash` against the head as of
THEN so the chain stays contiguous; the event's own `ts` preserves the action time
and a `detail.outbox_deferred` marker records the late admission, honest about
ordering rather than silently backdated
([`boltrig/kernel/audit_outbox.py:9`](../../../boltrig/kernel/audit_outbox.py) `"CHAIN-SAFETY IS THE DESIGN CONSTRAINT"`).
Backoff is `attempts * 30s` capped at 10 minutes
([`boltrig/kernel/audit_outbox.py:80`](../../../boltrig/kernel/audit_outbox.py) `"backoff = min(_BACKOFF_BASE_SECONDS * attempts, _BACKOFF_CAP_SECONDS)"`).
A non-dict payload is QUARANTINED by deletion rather than retried forever
([`boltrig/kernel/audit_outbox.py:67`](../../../boltrig/kernel/audit_outbox.py) `"a JSONB row round-trips as dict; fail closed"`).
An enumeration of ZERO tenants logs a warning, because that silence once produced
no receipt and no log line over nine hours
([`boltrig/kernel/audit_outbox.py:119`](../../../boltrig/kernel/audit_outbox.py) `"audit outbox: enumerated ZERO tenants"`).
Wired at [`boltrig/api/worker.py:147`](../../../boltrig/api/worker.py) `"run_audit_outbox_forever("`.

### Recovering a held write

The answer bridge reads the record and replays it under the SAME run identity,
which is what makes the approval fingerprint match
([`boltrig/kernel/held_call.py:20`](../../../boltrig/kernel/held_call.py) `"Replaying THAT record is what makes the resumed call authorised by construction"`).
`read_held_call` returning None is a REFUSAL signal, never an invitation to
re-derive the call from a transcript
([`boltrig/kernel/held_call.py:328`](../../../boltrig/kernel/held_call.py) `"None is a REFUSAL signal, never an invitation to re-derive"`).
`held_write_is_waiting` is mutually exclusive with the interpreter route by the
reserved `held:` prefix, because two claimants would race the ANSWERED -> CONSUMED
CAS ([`boltrig/kernel/held_call.py:253`](../../../boltrig/kernel/held_call.py) `"Two claimants would race the ANSWERED -> CONSUMED CAS"`).
`settle_held_call` retires the seal and flips the checkpoints to `done` on EVERY
terminal outcome, then re-runs the guarded run-credential sweep
([`boltrig/kernel/held_call.py:362`](../../../boltrig/kernel/held_call.py) `"Retire a held call: drop the seal and mark its checkpoints spent"`).
The sweep is guarded because `delete_credential_refs_for_run` deletes the WHOLE
`run:<id>:` prefix, so an unguarded sweep at a run terminal would destroy the very
record decision 0018 replays from
([`boltrig/kernel/held_call.py:284`](../../../boltrig/kernel/held_call.py) `"Retire a finished run's sealed credentials, unless a held write still needs them"`).

### Resuming a lost notification

`refire_resume` is the ONLY trigger outside `answer()` itself, used by the expiry
sweep's reconciliation pass for a request whose answer committed but whose resume
notification was lost to process death
([`boltrig/kernel/hitl.py:265`](../../../boltrig/kernel/hitl.py) `"Re-run ``_fire_resume`` for an ANSWERED request (reconciliation)"`).
Safe because every resume leg is CAS-guarded or idempotent.

## Failure modes and fail-open/fail-closed posture

| guard | direction | proof |
| --- | --- | --- |
| verb/binding resolution | FAIL-CLOSED | every miss raises `BindingNotFound` ([`boltrig/kernel/routing.py:158`](../../../boltrig/kernel/routing.py) `"raise BindingNotFound(f\"unknown verb '{name}'\")"`, `:164`, `:224`, `:227`) |
| ambiguous route | FAIL-CLOSED | `RouteRequired`, never "pick the first" ([`boltrig/kernel/routing.py:13`](../../../boltrig/kernel/routing.py) `"there is no step 5"`) |
| stale routing policy | FAIL-SOFT | skipped, the next rule or the refusal decides ([`boltrig/kernel/routing.py:122`](../../../boltrig/kernel/routing.py) `"SKIPPED rather than fatal"`) |
| unknown operation-class suffix | FAIL-CAREFUL | classed `update`, the write path ([`boltrig/kernel/routing.py:53`](../../../boltrig/kernel/routing.py) `"fail towards the careful branch, not the permissive one"`) |
| grant check | FAIL-CLOSED | unmatched, empty or unknown denies ([`boltrig/models/grants.py:108`](../../../boltrig/models/grants.py) `"return False  # K-13: nothing matched -> deny"`) |
| confusable verb id | FAIL-CLOSED | never matches any pattern ([`boltrig/models/grants.py:77`](../../../boltrig/models/grants.py) `"a non-canonical / confusable id can never be authorised"`) |
| workspace-scoped binding, unbound caller | FAIL-CLOSED | ([`boltrig/models/capability_routing.py:172`](../../../boltrig/models/capability_routing.py) `"unbound caller (``workspace_id`` None) never matches a workspace-scoped"`) |
| param/output validation | FAIL-CLOSED with an empty-schema hole | `if not schema: return []` ([`boltrig/kernel/dispatch.py:106`](../../../boltrig/kernel/dispatch.py) `"if not schema:"`) |
| idempotency conflict states | FAIL-CLOSED | four statuses each raise ([`boltrig/kernel/idempotency.py:163`](../../../boltrig/kernel/idempotency.py) `"raise IdempotencyConflict(messages[claim.status])"`) |
| expired executing lease | FAIL-CLOSED | becomes `uncertain`, demands reconciliation ([`boltrig/store/idempotency.py:77`](../../../boltrig/store/idempotency.py) `"record[\"status\"] = \"uncertain\""`) |
| secret-shaped result | FAIL-CLOSED | completed UNCACHEABLE ([`boltrig/kernel/idempotency.py:181`](../../../boltrig/kernel/idempotency.py) `"if secret_shaped(output):"`) |
| approval consume | FAIL-CLOSED | seven conditions then a CAS ([`boltrig/kernel/hitl.py:309`](../../../boltrig/kernel/hitl.py) `"or not hmac.compare_digest(req.request_fingerprint"`) |
| spent approval replayed | FAIL-LOUD | typed 409, never a silent re-pend ([`boltrig/kernel/approval_gate.py:193`](../../../boltrig/kernel/approval_gate.py) `"A spent approval must never silently re-pend"`) |
| approval with no redeemer | FAIL-CLOSED | nothing created ([`boltrig/kernel/approval_gate.py:143`](../../../boltrig/kernel/approval_gate.py) `"raise ApprovalNotHoldable("`) |
| stale approval past deadline | FAIL-CLOSED | returns None, gate re-pends ([`boltrig/kernel/hitl.py:300`](../../../boltrig/kernel/hitl.py) `"A stale approval can never execute (SEC-14)"`) |
| answer after timeout | FAIL-CLOSED | expired on the spot, typed 409 ([`boltrig/kernel/hitl.py:215`](../../../boltrig/kernel/hitl.py) `"Lazy timeout enforcement (SEC-14)"`) |
| escalation replayed as an approval | FAIL-CLOSED | type + verb must match ([`boltrig/kernel/hitl.py:326`](../../../boltrig/kernel/hitl.py) `"H1 hardening: require ``type == APPROVAL``"`) |
| rate limit, no policy configured | FAIL-OPEN by design | `if rl is None: return` ([`boltrig/kernel/ratelimit.py:112`](../../../boltrig/kernel/ratelimit.py) `"if rl is None:"`) |
| rate limit, unrecognised `per` | FAIL-OPEN silently | `_WINDOW_SECONDS.get(rl.per, 60)` ([`boltrig/kernel/ratelimit.py:114`](../../../boltrig/kernel/ratelimit.py) `"window_seconds = _WINDOW_SECONDS.get(rl.per, 60)"`) |
| rate limit backend absent | FAIL-DEGRADED | in-memory counter, per-process ([`boltrig/kernel/ratelimit.py:90`](../../../boltrig/kernel/ratelimit.py) `"if not redis_url or not redis_url.strip():"`) |
| adapter record absent | FAIL-CLOSED | absence is authoritative, unload + clear ([`boltrig/kernel/adapter_provider.py:20`](../../../boltrig/kernel/adapter_provider.py) `"Absence is authoritative"`) |
| adapter not loaded | DEGRADE or FAIL | `_degrade_or_fail` before any credential ([`boltrig/kernel/dispatch.py:693`](../../../boltrig/kernel/dispatch.py) `"if adapter is None:"`) |
| conflicting credential references | FAIL-CLOSED | `CredentialResolution` ([`boltrig/kernel/credentials.py:174`](../../../boltrig/kernel/credentials.py) `"adapter '{adapter_id}' has conflicting credential references"`) |
| adapter needs no credential | FAIL-OPEN by design | `return None` ([`boltrig/kernel/credentials.py:178`](../../../boltrig/kernel/credentials.py) `"adapter requires no credential (e.g. a local script)"`) |
| run-scoped param reference, wrong run/purpose/owner | FAIL-CLOSED | ([`boltrig/kernel/credentials.py:239`](../../../boltrig/kernel/credentials.py) `"Resolve one parsed reference to its material, FAIL CLOSED"`) |
| run-scoped adapter bearer, any mismatch | FAIL-SAFE to static | returns None ([`boltrig/kernel/credentials.py:342`](../../../boltrig/kernel/credentials.py) `"mismatch, or a missing run id resolves to ``None``"`) |
| pre-owner-fence sealed rows | FAIL-CLOSED | resolve for nobody ([`boltrig/kernel/run_scoped_credentials.py:34`](../../../boltrig/kernel/run_scoped_credentials.py) `"Records created before the owner fence carry no owner"`) |
| unknown `target_type` | FAIL-CLOSED | `BindingNotFound` ([`boltrig/kernel/dispatch.py:588`](../../../boltrig/kernel/dispatch.py) `"else:  # fail-closed on an unknown target type"`) |
| agent runtime absent | DEGRADE or FAIL | ([`boltrig/kernel/dispatch.py:737`](../../../boltrig/kernel/dispatch.py) `"return self._degrade_or_fail(verb_def, reason=\"agent_runtime_absent\")"`) |
| run event publish | FAIL-SAFE | swallowed ([`boltrig/kernel/dispatch.py:310`](../../../boltrig/kernel/dispatch.py) `"except Exception:  # observability must never break dispatch (P9)"`) |
| held-call record | NOT swallowed | ([`boltrig/kernel/dispatch.py:269`](../../../boltrig/kernel/dispatch.py) `"a failure here is NOT swallowed"`) |
| author-crossing row | FAIL-SAFE | logged warning ([`boltrig/kernel/dispatch.py:612`](../../../boltrig/kernel/dispatch.py) `"author-crossing announcement failed for %s (action completed)"`) |
| run-effect ledger write | FAIL-OPEN, bounded | a missing undo affordance, never a wrong action ([`boltrig/kernel/run_effect_recorder.py:17`](../../../boltrig/kernel/run_effect_recorder.py) `"Fail-open here is deliberate and bounded"`) |
| inverse builder raises | FAIL-CLOSED to not-undoable | ([`boltrig/kernel/effect_inverses.py:64`](../../../boltrig/kernel/effect_inverses.py) `"except Exception:"`) |
| audit append fault | DEFERS to the outbox | ([`boltrig/kernel/audit.py:356`](../../../boltrig/kernel/audit.py) `"except Exception as exc:"`) |
| outbox enqueue ALSO fails | FAIL-OPEN, logged loudly | the action stands UNAUDITED ([`boltrig/kernel/dispatch.py:474`](../../../boltrig/kernel/dispatch.py) `"SEC-16's audit-always, honestly stated"`) |
| audit outbox drain, one bad tenant | FAIL-SAFE | logged, sweep continues ([`boltrig/kernel/audit_outbox.py:128`](../../../boltrig/kernel/audit_outbox.py) `"one tenant's fault never stops the sweep (P9)"`) |
| security signal write | FAIL-SAFE inside the writer | swallowed there, NOT at the chokepoint ([`boltrig/kernel/security_events.py:135`](../../../boltrig/kernel/security_events.py) `"Fail-safe convenience the auth / ratelimit / grant paths call"`) |
| budget alert callback | FAIL-SAFE | ([`boltrig/kernel/cost.py:302`](../../../boltrig/kernel/cost.py) `"except Exception:  # alert side-channel must never break reserve"`) |
| budget reserve, concurrent exhaustion | FAIL-CLOSED, all-or-nothing | ([`boltrig/kernel/cost.py:322`](../../../boltrig/kernel/cost.py) `"if windows is None:"`) |
| unknown model price | FAIL-TO-TIER | never free ([`boltrig/kernel/cost.py:125`](../../../boltrig/kernel/cost.py) `"A silent zero is worse than an imprecise charge"`) |
| malformed retired-key epoch entry | FAIL-SAFE | ignored, row falls through to the current key and fails honestly ([`boltrig/kernel/audit.py:59`](../../../boltrig/kernel/audit.py) `"Ignoring a malformed entry is the fail-safe"`) |

The two most important entries: **the audit is fail-open at the last resort**
(an append fault that also fails to enqueue lets an effectful action stand
unaudited, logged as the governance incident it is), and **cost is not on this path
at all**. `CostAccountant` is constructed by the kernel
([`boltrig/kernel/__init__.py:65`](../../../boltrig/kernel/__init__.py) `"self.cost = CostAccountant(store, alert)"`)
but `dispatch.py` never references it. Bounded: `rg -n "cost" boltrig/kernel/dispatch.py`
returns one hit, inside a comment about rate tokens. `AuditEvent.tokens_used` and
`cost_micros` are therefore always None on a `TOOL_CALL` row from this chokepoint;
metering happens on the fleet spawn path
(`boltrig/fleet/spawn_budget.py`, `spawn_reservation.py`).

## What is proven

Invariants declared in `tests/invariants.yaml` that bind this area:

| id | what it holds | a named test |
| --- | --- | --- |
| `SEC-21` | params are schema-validated before any dispatch side effect | `tests/kernel/test_dispatch.py::test_invalid_params_rejected_before_dispatch` |
| `SEC-21` | out-of-schema adapter OUTPUT never returns ok | `tests/kernel/test_chokepoint_order.py::test_out_of_schema_adapter_output_is_rejected` |
| `SEC-07` | a verb is denied unless the caller holds the grant | `tests/security/test_grant_enforcement.py::test_ungranted_verb_is_denied` |
| `SEC-07` | the capability grant does not bypass the source-operation grant | `tests/kernel/test_capability_routing.py::test_the_capability_grant_does_not_bypass_the_source_operation_grant` |
| `SEC-07` | `route_required` never reaches an ungranted caller | `tests/kernel/test_capability_routing.py::test_route_required_never_reaches_an_ungranted_caller` |
| `K-2` | the tenant ceiling caps caller grants | `tests/security/test_grant_enforcement.py::test_tenant_ceiling_caps_caller_grants` |
| `K-5` | deny dominates allow | `tests/unit/test_grants_model.py::test_deny_dominates_allow` |
| `K-9` | terminal wildcard, no prefix collision | `tests/unit/test_grants_model.py::test_wildcard_does_not_match_prefix_collision` |
| `K-13` | an unknown verb has no binding | `tests/kernel/test_dispatch.py::test_unknown_verb_fails_closed` |
| `SEC-15` | replay precedes the spent-approval gate and the rate limit | `tests/kernel/test_idempotency.py::test_replay_precedes_spent_approval_gate`, `::test_replay_precedes_rate_limit` |
| `SEC-14` | a blocking verb pauses; an approval is single-use and verb-bound | `tests/security/test_hitl_gate.py::test_approval_is_verb_bound_and_single_use` |
| `SEC-14` | a throttled gated call does not spend the approval | `tests/security/test_hitl_gate.py::test_rate_limited_gated_call_does_not_spend_the_approval` |
| `SEC-14` | an always-block entry cannot be walked past by canonical name | `tests/kernel/test_capability_routing.py::test_the_always_block_list_cannot_be_walked_past_by_canonical_name` |
| `SEC-14` | a binding consequence override raises the gate | `tests/kernel/test_capability_routing.py::test_a_binding_consequence_override_raises_the_gate` |
| `SEC-05` | no credential resolution for a call that dies at a gate | `tests/kernel/test_chokepoint_order.py::test_credential_never_resolved_when_the_grant_check_fails` and the HITL/rate twins |
| `SEC-05` | `Credential.material` is unprintable by construction | `tests/security/test_credential_isolation.py::test_credential_repr_never_leaks_material` |
| `SEC-16` | every action, allowed or denied, is audited | `tests/kernel/test_chokepoint_order.py::test_rate_limited_dispatch_is_audited`, `::test_schema_invalid_dispatch_is_audited`, `::test_adapter_exception_dispatch_is_audited` |
| `SEC-16` | a failed append defers instead of dropping, and the janitor re-chains | `tests/kernel/test_audit_outbox.py::test_the_janitor_rechains_deferred_events_and_the_chain_verifies` |
| `K-19` | the chain detects reorder, drop or edit | `tests/kernel/test_audit_chain.py::test_chain_verifies_and_detects_tampering` |
| `K-20` | the writer scrubs secrets and identity in `detail` | `tests/security/test_credential_isolation.py::test_audit_scrubs_secret_in_detail` |
| `SEC-168` | verification re-derives the entire chain from seq 1 | `tests/kernel/test_audit_chain.py::test_a_chain_longer_than_the_old_window_verifies_ok` |
| `SEC-181` | a secure answer never enters the run; resolution fails closed | `tests/security/test_secure_input.py::test_secure_answer_is_sealed_and_the_run_carries_only_the_reference` |
| `SEC-197` | posture cannot widen grants or bypass blocks | `tests/security/test_approval_posture.py::test_full_access_never_bypasses_blocks_control_gates_or_grants` |
| `SEC-26` | every MCP-originated call runs the full order and audits | `tests/security/test_mcp_face.py::test_tools_call_runs_chokepoint_and_audits` |
| `SEC-08` | no cross-tenant discovery or dispatch | `tests/security/test_tenant_isolation.py::test_other_tenant_dispatch_fails_closed` |
| `FR-KER-05` | rate limits enforced on a SHARED counter | `tests/kernel/test_ratelimit_degraded.py::test_rate_limit_enforced` |
| `P9` | backend unavailability degrades, never crashes | `tests/kernel/test_ratelimit_degraded.py::test_degraded_mode_when_backend_down` |
| `NFR-REL-04` | adapter error classes map to stable transport codes | `tests/kernel/test_adapter_error_mapping.py::test_adapter_error_class_maps_to_safe_transport_error` |
| `FR-REV-01` | a consequential verb records its inverse or an honest not-undoable row | `tests/unit/test_run_effect_ledger.py::test_gated_success_records_with_its_inverse` |
| `FR-REV-02` | a revert executes inverses through the chokepoint | `tests/integration/test_run_revert.py::test_revert_executes_inverses_lifo_through_dispatch` |

**Ids the code cites that are NOT declared invariants.** `dispatch.py`'s own first
line claims `P2, US-KER-01, K-1`
([`boltrig/kernel/dispatch.py:1`](../../../boltrig/kernel/dispatch.py) `"The dispatch chokepoint (P2, US-KER-01, K-1)"`),
and none of the three appears as a declared key in `tests/invariants.yaml`. Bounded
and measured on the pinned tree: `grep -c "^  P2:$" tests/invariants.yaml` -> 0,
same for `P1`, `P3`, `P4`, `P8`, `K-1`, `K-3`, `SEC-04`, `SEC-17`, `US-KER-01`;
`P9`, `K-2`, `K-5`, `K-9`, `K-13`, `K-19`, `K-20`, `SEC-05`, `SEC-07`, `SEC-14`,
`SEC-15`, `SEC-16`, `SEC-21`, `FR-KER-05` -> 1 each. So the one-chokepoint claim
itself (`P2`) is doctrine and prose, not a bound invariant, even though the
CONSEQUENCES of it (`SEC-26` chokepoint parity, `SEC-16` audit-always) are bound.

## RISKS

RISK: `dispatch.py`'s own module docstring lists `validate params` before
`grant check`, and its body does the reverse. A reader trusting the docstring at
the top of the file gets the order backwards.
[`boltrig/kernel/dispatch.py:7`](../../../boltrig/kernel/dispatch.py) `"validate params          (SchemaValidationError, SEC-21)"`
against [`boltrig/kernel/dispatch.py:507`](../../../boltrig/kernel/dispatch.py) `"# 2. grant check (SEC-07) BEFORE validation"`.

RISK: `docs/ARCHITECTURE.md`'s dispatch table places idempotency replay AFTER the
HITL gate and the rate limit, which is the opposite of the code and of the SEC-15
invariant. An operator reasoning about replay from that table will get the
approval-spend behaviour wrong.
[`docs/ARCHITECTURE.md:55`](../../../docs/ARCHITECTURE.md) `"| 6 | Idempotency replay (return the prior result) |"`.

RISK: `boltrig/kernel/mcp.py` gates schema disclosure on a comment that states the
order backwards and cites line numbers that no longer point at those steps:
"params are validated before grants are checked (dispatch.py:520 then :524)".
Lines 520 and 524 are now the idempotency replay return and the
`requires_approval` call.
[`boltrig/kernel/mcp.py:385`](../../../boltrig/kernel/mcp.py) `"same predicate _list_tools uses, because params are validated before"`.

RISK: `_record_security` is documented as fail-safe at the chokepoint but has NO
`try/except` at that site. It is called from inside `except BoltrigError`, so if
the injected `security` object's `record` ever raised, the new exception would
MASK the original `GrantMissing` or `RateLimited`. The guarantee is delegated to
`SecurityWriter.record`'s own swallow, which the chokepoint does not enforce on an
arbitrary injected writer.
[`boltrig/kernel/dispatch.py:218`](../../../boltrig/kernel/dispatch.py) `"Fail-safe: no writer wired, or a write error, must"`
against [`boltrig/kernel/dispatch.py:223`](../../../boltrig/kernel/dispatch.py) `"await self._security.record("`.

RISK: the `finally` block calls `result_frames(...)` before the audit write, and
that call is NOT inside the try that protects the audit append. `_event_safe`
recurses without a depth bound over an adapter-supplied output, so a pathological
output raising there would skip the audit write entirely and mask the caller's
exception, which is exactly the masquerade the audit guard was written to prevent,
one statement earlier.
[`boltrig/kernel/dispatch.py:435`](../../../boltrig/kernel/dispatch.py) `"for frame in result_frames("`;
[`boltrig/kernel/run_event_projection.py:69`](../../../boltrig/kernel/run_event_projection.py) `"return [_event_safe(item) for item in value]"`.

RISK: `routing.py` writes five routing attribution keys into `meta` and states they
exist "so the audit can attribute it ... (SPEC §8 dispatch step 15)". The audit
write reads only `meta["target_adapter"]`. `capability`, `capability_binding_id`,
`connection`, `source_operation` and `route_selected_by` reach nothing. Bounded:
`rg -n "route_selected_by|capability_binding_id" boltrig/ tests/` on the pinned
tree finds only the writes in `routing.py` and the `ExecutionPlan` field itself.
So a routed call's audit row does not record WHICH capability, binding or
connection decided it.
[`boltrig/kernel/routing.py:228`](../../../boltrig/kernel/routing.py) `"so the audit can attribute it - and,"`
against [`boltrig/kernel/dispatch.py:441`](../../../boltrig/kernel/dispatch.py) `"target_adapter = meta.get(\"target_adapter\")"`.

RISK: `RateLimit.per` is not validated anywhere and an unrecognised value silently
becomes a 60-second window. A manifest or adapter spec writing `per: "day", max: 1000`
gets 1000 per MINUTE, a 1440x widening, with no error and no log line.
[`boltrig/kernel/ratelimit.py:114`](../../../boltrig/kernel/ratelimit.py) `"window_seconds = _WINDOW_SECONDS.get(rl.per, 60)"`;
`RateLimit` has no `__post_init__` at [`boltrig/models/registry.py:72`](../../../boltrig/models/registry.py) `"class RateLimit:"`.

RISK: with `scope: "tenant"` the counter key is the BARE tenant id, so every verb
carrying a tenant-scoped limit shares ONE bucket and whichever call arrives decides
against its own `max`. A chatty low-consequence verb can therefore exhaust the
budget of a high-consequence one, and two verbs with different `max` values on one
tenant produce a limit that depends on arrival order.
[`boltrig/kernel/ratelimit.py:115`](../../../boltrig/kernel/ratelimit.py) `"scope = tenant_id if rl.scope == \"tenant\" else"`.

RISK: the rate-limit key is built from the CALLER'S SPELLING (`verb`), while the
limit itself comes from the source operation's binding. With `scope: "verb"`, the
same binding addressed as `crm.contact.create` and as `hubspot.contact.create` gets
TWO independent buckets, so a caller holding both grants can take double the
configured throughput on one destination.
[`boltrig/kernel/dispatch.py:549`](../../../boltrig/kernel/dispatch.py) `"await self._rate.enforce(tenant, verb, binding.rate_limit)"`
with `verb` the caller's name from [`boltrig/kernel/dispatch.py:490`](../../../boltrig/kernel/dispatch.py) `"verb: str,"`.

RISK: `_validate` short-circuits on a falsy schema, so a verb registered with
`input_schema={}` is not validated at all and SEC-21's protection is vacuous for
it. Nothing at registration refuses an empty schema.
[`boltrig/kernel/dispatch.py:106`](../../../boltrig/kernel/dispatch.py) `"if not schema:"`;
[`boltrig/kernel/registry.py:159`](../../../boltrig/kernel/registry.py) `"input_schema=spec.input_schema,"` (no emptiness check).

RISK: `_require_redeemer` runs BEFORE the request is minted, but `record_held_call`
runs AFTER `PendingHuman` is raised and the request row already exists. A store
fault between the two recreates the exact ground-truth state decision 0018 exists
to prevent: an ANSWERED approval with nothing able to claim it.
[`boltrig/kernel/approval_gate.py:199`](../../../boltrig/kernel/approval_gate.py) `"await _require_redeemer(store, verb, context)"`
then [`boltrig/kernel/dispatch.py:281`](../../../boltrig/kernel/dispatch.py) `"await record_held_call("`.

RISK: on the no-manifest boot branch `approval_timeout_seconds` stays None, so
every gate-minted approval is created with `timeout_at = None` and NEVER expires.
SEC-14's timeout half is silently inert on that path.
[`boltrig/api/bootstrap.py:455`](../../../boltrig/api/bootstrap.py) `"kernel = Kernel(store, counter=counter, event_relay=event_relay)"`;
[`boltrig/kernel/hitl.py:147`](../../../boltrig/kernel/hitl.py) `"if timeout_seconds else None"`.

RISK: `CredentialResolver.sweep_run_scoped` has no production caller. Bounded:
`rg -n "sweep_run_scoped" boltrig/ tests/ apps/ services/ scripts/ tools/` on the
pinned tree finds the definition, four prose mentions, two gate scripts, and two
direct TEST calls. Its replacement is `held_call.sweep_run_credentials_if_settled`.
Its own docstring admits it is unwired.
[`boltrig/kernel/credentials.py:362`](../../../boltrig/kernel/credentials.py) `"async def sweep_run_scoped(self, tenant_id: str, run_id: str) -> int:"`;
[`boltrig/kernel/held_call.py:295`](../../../boltrig/kernel/held_call.py) `"was never wired anywhere"`.

RISK: `CapabilityBinding.input_transform_ref` and `output_transform_ref` are stored,
round-tripped and read back but applied NOWHERE. Doctrine §8 steps 7 and 12
("Transform canonical input into provider input", "Transform and normalise output")
are unimplemented, so a canonical capability call is executed against, and validated
against, the PROVIDER's schema. Bounded:
`rg -n "input_transform_ref|output_transform_ref" boltrig/ tests/` finds only the
model field and the store read/write.
[`boltrig/models/capability_routing.py:144`](../../../boltrig/models/capability_routing.py) `"input_transform_ref: str | None = None"`;
[`docs/SPEC-capability-doctrine.md:627`](../../../docs/SPEC-capability-doctrine.md) `"7. Transform canonical input into provider input."`.

RISK: doctrine §8 step 14 ("Issue provenance references") is likewise absent from
dispatch. `entity_provenance` exists as a table but the chokepoint never writes it.
Bounded: `rg -n "provenance" boltrig/kernel/dispatch.py boltrig/kernel/routing.py`
finds one hit, in an unrelated docstring about schema findings.
[`docs/SPEC-capability-doctrine.md:634`](../../../docs/SPEC-capability-doctrine.md) `"14. Issue provenance references."`.

RISK: `KernelRegistry.discover` returns each verb's `binding.target_type` and
`binding.target_ref`, which names the concrete adapter behind a verb. The registry
docstring for the same file asserts "The agent never learns which concrete system
sits behind a verb (P4, K-2)".
[`boltrig/kernel/registry.py:355`](../../../boltrig/kernel/registry.py) `"\"target_type\": binding.target_type.value, \"target_ref\": binding.target_ref"`
against [`boltrig/models/registry.py:4`](../../../boltrig/models/registry.py) `"The agent never learns which concrete"`.
Whether this reaches an AGENT depends on which surfaces call `discover`, which is
outside this area's bound.

RISK: `GrantChecker.check` returns two DIFFERENT messages for a ceiling denial and
a caller denial, so the refusal text is an oracle telling the caller which layer
said no. The docstring's stated property is narrower ("never returns a reason that
identifies the backend"), so this is not a contradiction, but it is a disclosure
the caller does not need.
[`boltrig/kernel/grants.py:21`](../../../boltrig/kernel/grants.py) `"verb '{verb_id}' is outside the tenant permission ceiling"`
and [`boltrig/kernel/grants.py:23`](../../../boltrig/kernel/grants.py) `"caller is not granted verb '{verb_id}'"`.

RISK: `_summarise_params` puts INSTANCE-CHOSEN top-level key names into the
append-only audit row, capped at 50. The module says so plainly and calls it a
recorded LIMIT rather than a safety proof, but it is still caller-supplied text in
a store nothing can unwrite.
[`boltrig/kernel/run_event_projection.py:31`](../../../boltrig/kernel/run_event_projection.py) `"A key NAME is instance-chosen, so no mechanical check can"`.

RISK: the one-chokepoint claim itself is not a declared invariant. `P2`,
`US-KER-01` and `K-1` are cited in `dispatch.py`'s first line and none is a key in
`tests/invariants.yaml`; nothing in the gate would fail if a second
`adapter.execute` call site appeared outside the kernel.
[`boltrig/kernel/dispatch.py:1`](../../../boltrig/kernel/dispatch.py) `"The dispatch chokepoint (P2, US-KER-01, K-1)"`.

RISK: `boltrig/fleet/browser_executor.py` exposes `POST /v1/execute` which calls an
adapter directly with a `None` credential, guarded only by a fixed header value and
the adapter's own `describe()` verb set, with no grant check, no HITL gate, no rate
limit and no audit row. It is a sidecar behind the kernel-side adapter, but it IS a
network-reachable execute path outside the chokepoint.
[`boltrig/fleet/browser_executor.py:90`](../../../boltrig/fleet/browser_executor.py) `"result = await browser.execute(verb, params, None, context)"`.

## OPEN QUESTIONS

1. Which of the three documented dispatch orders is INTENDED to be canonical:
   `AGENTS.md`'s, `dispatch.py`'s docstring, or `docs/ARCHITECTURE.md`'s? Settled by
   a decision record naming one and amending the other two. I can prove only what
   the code does.
2. Does anything consume the routing attribution keys in `meta` outside the pinned
   tree (a downstream reader, an Opbox client)? Settled by grepping the consuming
   repositories, which are outside this referent.
3. Is the tenant-scoped rate-limit bucket collapse intended? `RateLimit.scope`
   documents `'tenant' | 'verb'` without saying that `tenant` means one bucket for
   ALL verbs. Settled by a test asserting the intended behaviour either way; I found
   none. Bounded: `rg -n "scope=\"tenant\"" tests/` finds fixtures using it, none
   asserting cross-verb sharing.
4. Is the `full_access` posture reachable in any shipped tenant, and by what UI?
   `SEC-197` says changing it requires an interactive self-session with an exact
   confirmation token; whether any production manifest ships that route enabled is
   an ops question this tree cannot answer.
5. What retention applies to `audit_log`, `security_log`, `idempotency_keys` and
   `run_effects` in production? No DDL or janitor in this tree bounds their growth.
   Settled by a deployment runbook or a sweep I did not find (bounded:
   `rg -n "audit_outbox_due|list_orgs" boltrig/api/worker.py` shows only the outbox
   drain).
6. Does `identity_mode: "delegated"` do anything anywhere? It is declared on `Verb`
   and stored, and dispatch does not read it. Settled by finding a consumer; bounded
   `rg -n "identity_mode" boltrig/` shows the model, the DDL and the registry write
   only.
7. Is the browser executor's `/v1/execute` reachable from outside its own host
   network in any shipped deployment? Settled by the compose and Caddy configuration,
   which belongs to the deployment area.

## Requirements

| id | statement | status | evidence | invariant |
| --- | --- | --- | --- | --- |
| BT-REQ-0100 | Every external action reaches an adapter only through `Dispatcher._execute_adapter`, the single `adapter.execute` call site in the kernel. | IMPLEMENTED | `boltrig/kernel/dispatch.py:719` `"result: Result = await adapter.execute(verb_def.id, resolved_params"` | SEC-26 |
| BT-REQ-0101 | `Kernel.invoke` delegates without policy to the dispatcher, and the kernel composes rather than implements policy. | IMPLEMENTED | `boltrig/kernel/__init__.py:175` `"return await self.dispatcher.invoke("` | - |
| BT-REQ-0102 | The executed order is resolve, grant check, validate params, idempotency claim, approval verdict, gate/rate limit, execute, validate output, complete, audit. | IMPLEMENTED | `boltrig/kernel/dispatch.py:499-601` `"# 1. resolve the verb + binding"` | SEC-21 |
| BT-REQ-0103 | The grant check runs BEFORE param validation, diverging from the doctrine sentence in AGENTS.md and from dispatch.py's own docstring. | IMPLEMENTED | `boltrig/kernel/dispatch.py:507` `"# 2. grant check (SEC-07) BEFORE validation"` | SEC-07 |
| BT-REQ-0104 | `docs/ARCHITECTURE.md` documents idempotency replay after the HITL gate and rate limit, which the code contradicts. | IMPLEMENTED-UNTESTED | `docs/ARCHITECTURE.md:55` `"Idempotency replay (return the prior result)"` | - |
| BT-REQ-0105 | An unresolvable verb, an ineligible binding, a missing binding row and an unknown target type all raise `BindingNotFound`. | IMPLEMENTED | `boltrig/kernel/routing.py:158` `"raise BindingNotFound(f\"unknown verb '{name}'\")"`; `boltrig/kernel/dispatch.py:588` `"else:  # fail-closed on an unknown target type"` | K-13 |
| BT-REQ-0106 | Only a name that is not a stored verb reaches the capability router, so routing can add a destination and never move an existing one. | IMPLEMENTED | `boltrig/kernel/routing.py:211` `"A stored verb id resolves exactly as it always did"` | - |
| BT-REQ-0107 | The capability grant is authorised after the capability is known to exist and before any destination is read. | IMPLEMENTED | `boltrig/kernel/routing.py:159` `"if authorize is not None:"` | SEC-07 |
| BT-REQ-0108 | Two or more eligible bindings with no selecting policy raise `RouteRequired` naming the destinations, never a first-match. | IMPLEMENTED | `boltrig/kernel/routing.py:176` `"raise RouteRequired("` | - |
| BT-REQ-0109 | A routing policy naming a disabled or deleted binding is skipped rather than fatal. | IMPLEMENTED | `boltrig/kernel/routing.py:122` `"SKIPPED rather than fatal"` | - |
| BT-REQ-0110 | An unrecognised capability suffix is classed `update`, the write path that never fans out. | IMPLEMENTED | `boltrig/kernel/routing.py:52` `"An unrecognised name must"` | - |
| BT-REQ-0111 | A routed call is grant-checked against BOTH the capability id and the source operation id. | IMPLEMENTED | `boltrig/kernel/routing.py:264` `"return (verb,) if plan is None else (plan.capability_id, verb_def.id)"` | SEC-07 |
| BT-REQ-0112 | A capability grant is matched unversioned so a version move cannot silently stop it matching. | IMPLEMENTED | `boltrig/kernel/routing.py:257` `"The capability is checked UNVERSIONED"` | SEC-07 |
| BT-REQ-0113 | A verb is authorised only when both the tenant ceiling and the caller's grants permit it. | IMPLEMENTED | `boltrig/kernel/grants.py:20` `"if not tenant_perms.grants.permits(verb_id):"` | K-2 |
| BT-REQ-0114 | An active deny beats every allow and is checked first. | IMPLEMENTED | `boltrig/models/grants.py:105` `"return False  # K-5: deny dominates, short-circuit"` | K-5 |
| BT-REQ-0115 | An unmatched, empty or unknown grant set denies. | IMPLEMENTED | `boltrig/models/grants.py:108` `"return False  # K-13: nothing matched -> deny"` | K-13 |
| BT-REQ-0116 | A verb id that is not a safe NFKC identifier can never match any grant pattern. | IMPLEMENTED | `boltrig/models/grants.py:77` `"a non-canonical / confusable id can never be authorised"` | K-9 |
| BT-REQ-0117 | A grant wildcard matches only on a namespace boundary, so `jira.*` never matches `jirax.read`. | IMPLEMENTED | `boltrig/models/grants.py:86` `"``jira.*`` matches ``jira.read`` (next char is a boundary)"` | K-9 |
| BT-REQ-0118 | `GrantSet.intersect` narrows a wildcard against a ceiling rather than dropping it, and unions denies. | IMPLEMENTED | `boltrig/models/grants.py:111` `"Tenant ∩ skill grants. Allows must be permitted by BOTH; denies union."` | K-2 |
| BT-REQ-0119 | Params and output are validated through one seam so the output twin cannot be forgotten. | IMPLEMENTED | `boltrig/kernel/dispatch.py:136` `"ONE seam for input and output"` | SEC-21 |
| BT-REQ-0120 | Schema findings carry only `schema_path` and an allowlisted `keyword`, never an instance-derived path or a schema value. | IMPLEMENTED | `boltrig/kernel/dispatch.py:100` `"Refused, and both look safe: ``json_path`` / ``absolute_path``"` | SEC-21 |
| BT-REQ-0121 | Schema findings are bounded at 10 errors, depth 10 and 64-character segments before the row is written. | IMPLEMENTED | `boltrig/kernel/schema_diagnosis.py:67` `"MAX_SCHEMA_ERRORS = 10"` | SEC-21 |
| BT-REQ-0122 | A verb whose registered schema is empty is not validated at all, on input or output. | IMPLEMENTED-UNTESTED | `boltrig/kernel/dispatch.py:106` `"if not schema:"` | - |
| BT-REQ-0123 | A schema failure records the schema digest so a later read is told the schema moved rather than diffed against the wrong one. | IMPLEMENTED | `boltrig/kernel/schema_diagnosis.py:107` `"if recorded != current:"` | SEC-21 |
| BT-REQ-0124 | Caller-facing schema hints are returned but never audited. | IMPLEMENTED | `boltrig/models/errors.py:65` `"``hints`` is deliberately ABSENT here"` | SEC-21 |
| BT-REQ-0125 | An idempotency key is bound to tenant, actor, delegation, workspace, noun, verb and the canonical request hash. | IMPLEMENTED | `boltrig/kernel/idempotency.py:141` `"claim = await self._store.idempotency_claim("` | SEC-15 |
| BT-REQ-0126 | A completed idempotent result replays before the approval gate and the rate limit. | IMPLEMENTED | `boltrig/kernel/dispatch.py:519` `"if isinstance(idempotency, IdempotencyReplay):"` | SEC-15 |
| BT-REQ-0127 | A key supplied for an `idempotency_mode: disabled` verb is refused with `IdempotencyConflict`. | IMPLEMENTED | `boltrig/kernel/idempotency.py:139` `"verb '{verb}' does not support replay caching"` | SEC-15 |
| BT-REQ-0128 | Secret-shaped output is completed UNCACHEABLE without persisting bearer material. | IMPLEMENTED | `boltrig/kernel/idempotency.py:181` `"if secret_shaped(output):"` | SEC-15 |
| BT-REQ-0129 | Any raise between the claim and completion releases the claim rather than parking it until lease expiry. | IMPLEMENTED | `boltrig/kernel/dispatch.py:597` `"await self._idempotency.release(run)"` | SEC-15 |
| BT-REQ-0130 | An expired executing lease becomes UNCERTAIN and demands reconciliation instead of silently re-running. | IMPLEMENTED | `boltrig/store/idempotency.py:77` `"record[\"status\"] = \"uncertain\""` | SEC-15 |
| BT-REQ-0131 | The sensitive-key normaliser uses zero-width regexes so an adapter-chosen key cannot cause polynomial backtracking. | IMPLEMENTED | `boltrig/kernel/idempotency.py:67` `"BOTH PATTERNS ARE ZERO-WIDTH ON PURPOSE"` | - |
| BT-REQ-0132 | The approval verdict is the operator block list, then stored-binding capabilities, then a binding override, then the posture gate. | IMPLEMENTED | `boltrig/kernel/approval_posture.py:98` `"blocked = unpinned(blocking_verbs)"` | SEC-14 |
| BT-REQ-0133 | The operator block list is matched against the typed name, the capability and the source operation. | IMPLEMENTED | `boltrig/kernel/routing.py:268` `"The names available WITHOUT a store read"` | SEC-14 |
| BT-REQ-0134 | A version-pinned block-list entry is read as the capability it names. | IMPLEMENTED | `boltrig/kernel/routing.py:317` `"An operator's always-ask entries with any version pin removed"` | SEC-14 |
| BT-REQ-0135 | Blocking a capability gates the source operation it routes to, resolved from approved stored bindings. | IMPLEMENTED | `boltrig/kernel/routing.py:332` `"The capabilities this call answers to"` | SEC-14 |
| BT-REQ-0136 | A binding `consequence_override` may only raise the gate; a `low` override is inert. | IMPLEMENTED | `boltrig/kernel/approval_posture.py:106` `"if override == \"high\":"` | SEC-14 |
| BT-REQ-0137 | The approval posture applies only to delegated agent calls on adapter bindings, never to control verbs, agent bindings or direct human calls. | IMPLEMENTED | `boltrig/kernel/approval_posture.py:124` `"if not is_delegated_agent_call(context):"` | SEC-197 |
| BT-REQ-0138 | A missing or malformed stored posture falls back to `risk_based`. | IMPLEMENTED | `boltrig/kernel/approval_posture.py:33` `"except (TypeError, ValueError):"` | SEC-197 |
| BT-REQ-0139 | An approval is fingerprinted over tenant, noun, verb, verbatim params, the authenticated initiator and the resource snapshot. | IMPLEMENTED | `boltrig/kernel/hitl_fingerprint.py:50` `"Bind one approval to one canonical action and authenticated initiator"` | SEC-14 |
| BT-REQ-0140 | An approval is consumed only after an exact type, verb, timeout and constant-time fingerprint match plus a winning CAS. | IMPLEMENTED | `boltrig/kernel/hitl.py:309` `"or not hmac.compare_digest(req.request_fingerprint"` | SEC-14 |
| BT-REQ-0141 | Replaying a CONSUMED approval raises a typed 409 rather than silently re-pending. | IMPLEMENTED | `boltrig/kernel/approval_gate.py:195` `"raise HITLStateConflict("` | SEC-14 |
| BT-REQ-0142 | An answered approval past its deadline can never authorise an execution; the gate re-pends. | IMPLEMENTED | `boltrig/kernel/hitl.py:300` `"A stale approval can never execute (SEC-14)"` | SEC-14 |
| BT-REQ-0143 | An answer arriving after `timeout_at` expires the request and is refused with a typed 409. | IMPLEMENTED | `boltrig/kernel/hitl.py:215` `"Lazy timeout enforcement (SEC-14)"` | SEC-14 |
| BT-REQ-0144 | An escalation or clarification request cannot be laundered into authorisation on a gated verb. | IMPLEMENTED | `boltrig/kernel/hitl.py:326` `"H1 hardening: require ``type == APPROVAL``"` | SEC-14 |
| BT-REQ-0145 | No approval is minted unless a redeeming lane can be named from the record; on refusal nothing is created. | IMPLEMENTED | `boltrig/kernel/approval_gate.py:132` `"Refuse to MINT an approval no lane could ever redeem"` | SEC-14 |
| BT-REQ-0146 | On a leg carrying an approval id the rate limit is enforced before the gate consumes it. | IMPLEMENTED | `boltrig/kernel/dispatch.py:548` `"if carries_approval:"` | SEC-14 |
| BT-REQ-0147 | A verb with no configured `rate_limit` is not throttled at all. | IMPLEMENTED-UNTESTED | `boltrig/kernel/ratelimit.py:112` `"if rl is None:"` | FR-KER-05 |
| BT-REQ-0148 | An unrecognised `RateLimit.per` silently becomes a 60-second window with no validation anywhere. | IMPLEMENTED-UNTESTED | `boltrig/kernel/ratelimit.py:114` `"window_seconds = _WINDOW_SECONDS.get(rl.per, 60)"` | - |
| BT-REQ-0149 | A tenant-scoped rate limit keys on the bare tenant id, so all such verbs share one counter bucket. | IMPLEMENTED-UNTESTED | `boltrig/kernel/ratelimit.py:115` `"scope = tenant_id if rl.scope == \"tenant\" else"` | - |
| BT-REQ-0150 | The rate-limit key uses the caller's spelling, so one binding addressed by two names gets two buckets. | IMPLEMENTED-UNTESTED | `boltrig/kernel/dispatch.py:549` `"await self._rate.enforce(tenant, verb, binding.rate_limit)"` | - |
| BT-REQ-0151 | The shipped rate-limit counter is Redis when `REDIS_URL` is set and the in-memory counter otherwise. | IMPLEMENTED | `boltrig/kernel/ratelimit.py:90` `"if not redis_url or not redis_url.strip():"` | FR-KER-05 |
| BT-REQ-0152 | The rate-limit window is a fixed calendar window, so a configured max admits up to 2x across a boundary. | IMPLEMENTED | `boltrig/models/registry.py:75` `"``max`` is per FIXED CALENDAR window, not per sliding one"` | FR-KER-05 |
| BT-REQ-0153 | No credential is resolved for a call that dies at the grant check, the HITL gate or the rate limit. | IMPLEMENTED | `tests/kernel/test_chokepoint_order.py::test_credential_never_resolved_when_rate_limited` | SEC-05 |
| BT-REQ-0154 | The adapter credential is resolved for `on_behalf_of` when present and otherwise for `actor`. | IMPLEMENTED | `boltrig/kernel/credentials.py:144` `"``owner`` is the acting identity"` | SEC-05 |
| BT-REQ-0155 | Conflicting configured and durable credential references raise `CredentialResolution`, except where a user-level connection deliberately overrides the org. | IMPLEMENTED | `boltrig/kernel/credentials.py:174` `"adapter '{adapter_id}' has conflicting credential references"` | SEC-05 |
| BT-REQ-0156 | A sealed per-run adapter bearer overrides the static credential only for the same run, adapter and owner, and is minted straight into the credential argument. | IMPLEMENTED | `boltrig/kernel/dispatch.py:705` `"override = await self._creds.resolve_run_scoped_credential("` | SEC-181 |
| BT-REQ-0157 | A verb param carrying a run-scoped credential reference is resolved to material inside the kernel on a copy; another run, purpose or owner fails closed. | IMPLEMENTED | `boltrig/kernel/credentials.py:239` `"Resolve one parsed reference to its material, FAIL CLOSED"` | SEC-181 |
| BT-REQ-0158 | A sealed row without an owner resolves for nobody. | IMPLEMENTED | `boltrig/kernel/run_scoped_credentials.py:34` `"Records created before the owner fence carry no owner"` | SEC-181 |
| BT-REQ-0159 | `Credential.material` is repr-suppressed and `__str__` never renders it. | IMPLEMENTED | `boltrig/adapters/base.py:26` `"material: dict[str, Any] = field(default_factory=dict, repr=False)"` | SEC-05 |
| BT-REQ-0160 | A missing adapter record is authoritative absence: the loader is unloaded and the credential binding cleared. | IMPLEMENTED | `boltrig/kernel/adapter_provider.py:20` `"Absence is authoritative"` | - |
| BT-REQ-0161 | A generated adapter serves only when activated and an MCP consumer only when its lifecycle row is active. | IMPLEMENTED | `boltrig/kernel/adapter_provider.py:54` `"if lifecycle is not None and lifecycle.state == \"active\""` | - |
| BT-REQ-0162 | `chat.ask_user` is intercepted in-kernel after the full gate order, creates a QUESTION HITL and always raises `PendingHuman`. | IMPLEMENTED | `boltrig/kernel/dispatch.py:580` `"if verb == QUESTIONS_VERB:"` | SEC-181 |
| BT-REQ-0163 | An adapter re-registration never replaces an existing AGENT binding, so a native or re-pointed verb survives restart. | IMPLEMENTED | `boltrig/kernel/registry.py:172` `"AN AGENT BINDING IS NEVER AN ADAPTER'S TO REPLACE"` | - |
| BT-REQ-0164 | Adapter-over-adapter binding replacement is allowed so manifest order picks the provider. | IMPLEMENTED | `boltrig/kernel/registry.py:181` `"ADAPTER-over-ADAPTER is deliberately still allowed"` | - |
| BT-REQ-0165 | Adapter error classes map to 404, 403, 400, 409 and 502 with a bounded reason code, and a detail-free failure maps to 502. | IMPLEMENTED | `boltrig/kernel/adapter_errors.py:8` `"_TRANSPORT_ERRORS = {"` | NFR-REL-04 |
| BT-REQ-0166 | An adapter `UNAVAILABLE` result degrades when the verb declares a degraded mode and otherwise fails. | IMPLEMENTED | `boltrig/kernel/dispatch.py:744` `"Produce a degraded result if the verb defines one, else fail (P9)"` | P9 |
| BT-REQ-0167 | Exactly one audit row is written in the `finally` block on every outcome, allowed or denied. | IMPLEMENTED | `boltrig/kernel/dispatch.py:445` `"await self._audit.write("` | SEC-16 |
| BT-REQ-0168 | An audit append fault defers the scrubbed payload to the outbox rather than dropping it. | IMPLEMENTED | `boltrig/kernel/audit.py:337` `"DURABLE DEFERRAL (SEC-16 audit-always, 2026-08-16)"` | SEC-16 |
| BT-REQ-0169 | When the outbox write also fails the action stands effectful and unaudited, logged as a governance incident rather than masking the caller's exception. | IMPLEMENTED-UNTESTED | `boltrig/kernel/dispatch.py:474` `"SEC-16's audit-always, honestly stated"` | SEC-16 |
| BT-REQ-0170 | The outbox janitor re-derives seq, prev_hash and hash at drain time so the chain stays contiguous, preserving the action `ts` and marking the late admission. | IMPLEMENTED | `boltrig/kernel/audit_outbox.py:9` `"CHAIN-SAFETY IS THE DESIGN CONSTRAINT"` | SEC-16 |
| BT-REQ-0171 | The outbox drain backs off `attempts * 30s` capped at 10 minutes and quarantines a non-dict payload. | IMPLEMENTED | `boltrig/kernel/audit_outbox.py:80` `"backoff = min(_BACKOFF_BASE_SECONDS * attempts, _BACKOFF_CAP_SECONDS)"` | SEC-16 |
| BT-REQ-0172 | Each audit row is HMAC-chained to its predecessor per tenant, serialised by a per-tenant lock and backstopped by `UNIQUE (tenant_id, seq)`. | IMPLEMENTED | `boltrig/kernel/audit.py:318` `"SEC-16: serialise the read-head -> append per tenant"` | K-19 |
| BT-REQ-0173 | Exactly one HMAC key verifies each row, bounded by the seq at which a retired key was retired. | IMPLEMENTED | `boltrig/kernel/audit.py:76` `"The ONE key a row at ``seq`` is allowed to verify under"` | K-19 |
| BT-REQ-0174 | The live audit HMAC key is read once at module import, so rotating it requires a process restart. | IMPLEMENTED-UNTESTED | `boltrig/kernel/audit.py:28` `"_HMAC_KEY = os.environ.get(\"BOLTRIG_AUDIT_HMAC_KEY\""` | K-19 |
| BT-REQ-0175 | Audit `detail` is scrubbed on both keys and values, recursing through nested dicts and lists, and `user_agent` is scrubbed as a chain field. | IMPLEMENTED | `boltrig/kernel/audit.py:180` `"Bring the KEY within the scrub"` | K-20 |
| BT-REQ-0176 | Chain verification re-derives the entire per-tenant chain from seq 1 ascending and cannot loop on a non-advancing page. | IMPLEMENTED | `boltrig/kernel/audit.py:272` `"a misbehaving scan page must never loop forever"` | SEC-168 |
| BT-REQ-0177 | The Opbox-depth audit fields are folded into the hash only when non-None, so pre-enrichment rows still verify. | IMPLEMENTED | `boltrig/kernel/audit.py:111` `"canonicalises byte-for-byte identically to before"` | K-19 |
| BT-REQ-0178 | A denied grant and a throttle trip are recorded on the distinct security stream at the same field depth as the audit row. | IMPLEMENTED | `boltrig/kernel/dispatch.py:413` `"if isinstance(e, GrantMissing):"` | - |
| BT-REQ-0179 | The chokepoint's security-event call has no guard of its own, so its fail-safety depends entirely on the injected writer swallowing. | IMPLEMENTED-UNTESTED | `boltrig/kernel/dispatch.py:223` `"await self._security.record("` | - |
| BT-REQ-0180 | Run events are published to this run and to the delegating parent run, and a publish failure is swallowed. | IMPLEMENTED | `boltrig/kernel/dispatch.py:288` `"Publish to THIS run and to the run that delegated to it"` | - |
| BT-REQ-0181 | The `tool_call` and `tool_result` frames carry a redacted input/output plus a value-free key summary, never raw params on the chat stream. | IMPLEMENTED | `boltrig/kernel/run_event_projection.py:19` `"A bounded, VALUE-FREE description of a verb's params"` | K-20 |
| BT-REQ-0182 | A `voice_tone` frame is emitted only for an ok result carrying a well-formed tone block, otherwise no event rather than a partial one. | IMPLEMENTED | `boltrig/kernel/run_event_projection.py:113` `"A ``voice_tone`` event, when the verb reported one and only then"` | - |
| BT-REQ-0183 | An approval pause is recorded durably as a reserved `held:` checkpoint on the root run plus the verbatim call sealed under a distinct credential kind. | IMPLEMENTED | `boltrig/kernel/held_call.py:174` `"await store.set_credential_ref("` | SEC-14 |
| BT-REQ-0184 | Only an APPROVAL pause is held; a QUESTION pause seals nothing. | IMPLEMENTED | `boltrig/kernel/dispatch.py:272` `"Only an APPROVAL is held"` | SEC-181 |
| BT-REQ-0185 | A held-call record failure is not swallowed, unlike the event relay. | IMPLEMENTED-UNTESTED | `boltrig/kernel/dispatch.py:269` `"a failure here is NOT swallowed"` | - |
| BT-REQ-0186 | A run-terminal credential sweep is skipped while any held call is still paused on that run. | IMPLEMENTED | `boltrig/kernel/held_call.py:310` `"if await any_held_call_paused(store, tenant_id, run_id):"` | SEC-181 |
| BT-REQ-0187 | `CredentialResolver.sweep_run_scoped` has no production call site; the wired lifecycle seam is `held_call.sweep_run_credentials_if_settled`. | DEAD | `boltrig/kernel/credentials.py:362` `"async def sweep_run_scoped(self, tenant_id: str, run_id: str) -> int:"` | - |
| BT-REQ-0188 | A successful consequential invocation appends a run-effect ledger row with its inverse or an honest not-undoable row. | IMPLEMENTED | `boltrig/kernel/run_effect_recorder.py:36` `"async def record_run_effect("` | FR-REV-01 |
| BT-REQ-0189 | The inverse registry ships empty and an unregistered or raising builder yields not-undoable. | IMPLEMENTED | `boltrig/kernel/effect_inverses.py:53` `"Fail-closed twice over"` | FR-REV-01 |
| BT-REQ-0190 | A revert run records nothing, so an undo cannot re-enter the ledger. | IMPLEMENTED | `boltrig/kernel/run_effect_recorder.py:46` `"(context.extra or {}).get(\"effect_revert\")"` | FR-REV-01 |
| BT-REQ-0191 | Crossing the one-to-two active-author boundary via a `control.` verb writes its own audit row, measured by counting rather than by a verb list. | IMPLEMENTED | `boltrig/kernel/dispatch.py:646` `"measured by COUNTING rather than by knowing which verbs touch"` | - |
| BT-REQ-0192 | Cost accounting is not on the dispatch path; `tokens_used` and `cost_micros` are never set by the chokepoint. | IMPLEMENTED-UNTESTED | `boltrig/kernel/dispatch.py:445` `"await self._audit.write("` (no cost fields passed) | - |
| BT-REQ-0193 | An unknown model price falls back to the cost tier and unattributed tokens are billed at the input rate, never free. | IMPLEMENTED | `boltrig/kernel/cost.py:125` `"A silent zero is worse than an imprecise charge"` | - |
| BT-REQ-0194 | A hard-stop budget reservation debits every scope or none, re-checked under lock. | IMPLEMENTED | `boltrig/kernel/cost.py:322` `"if windows is None:"` | - |
| BT-REQ-0195 | `boltrig/kernel/**` may not import `boltrig.fleet` or `services`, enforced by a deny-list scan that fails when the kernel root is missing. | IMPLEMENTED | `scripts/check_architecture.py:58` `"_KERNEL_FORBIDDEN = (\"boltrig.fleet\", \"services\")"` | - |
| BT-REQ-0196 | `RecordingDispatcher` delegates both attribute reads and writes so collaborators swapped by assignment reach the real dispatcher. | IMPLEMENTED | `boltrig/kernel/trajectory.py:175` `"WRITES GO THROUGH TOO, or the proxy is only half transparent"` | - |
| BT-REQ-0197 | The routing attribution keys `capability`, `capability_binding_id`, `connection`, `source_operation` and `route_selected_by` are written into `meta` and read by nothing. | DEAD | `boltrig/kernel/routing.py:233` `"meta[\"capability\"] = plan.ref"` | - |
| BT-REQ-0198 | Capability input and output transforms are declared on the binding and applied nowhere; a routed call executes and validates against the provider schema. | SCAFFOLDED | `boltrig/models/capability_routing.py:144` `"input_transform_ref: str | None = None"` | - |
| BT-REQ-0199 | The one-chokepoint claim (`P2`, `US-KER-01`, `K-1`) is cited in the code but declared in no invariant, so nothing in the gate would fail on a second execute path. | IMPLEMENTED-UNTESTED | `boltrig/kernel/dispatch.py:1` `"The dispatch chokepoint (P2, US-KER-01, K-1)"` | - |
