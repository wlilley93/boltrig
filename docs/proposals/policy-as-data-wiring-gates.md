# Policy-as-data wiring gates

Status: implementation gap record, 2026-07-29.

This note distinguishes fields that are merely parsed and revisioned from policy
that changes serving behaviour. A saved field is not evidence of enforcement.
The symbols below are the stable code anchors; line numbers are intentionally
omitted because this repository is under active refactoring.

## Exact wiring matrix

| Policy | Parse / author path | Runtime consumer | Effective boundary today | Gate still required |
| --- | --- | --- | --- | --- |
| `spawn_rules` | `parse_spawn_rules()` enforces a closed schema for manifest load and Operator update/rollback; explicit `priority` is required | `Spawner._resolve_spawn_request()` reads the latest governed section revision (or manifest base) exactly once, then `apply_spawn_rule()` evaluates the all-of `prefer.intent_tags` predicate before skill/capability resolution | Live for any governed spawn that supplies intent tags. The unique highest priority wins; ties, malformed revisions, conflicting capability/runtime/tier pins and stale/incompatible targets fail closed. Rule skills are added before capability selection but their tool grants remain intersected with parent/caller authority; rule depth only tightens the capability ceiling. The bounded selected-rule receipt is copied into child context, audit, subagent-open event and public result; the shared SDK preserves it and Worker labels the delegated activity with the selected policy id | Ordinary Chat, evaluation and personal-agent calls currently supply no intent tags, so they retain their existing skill/capability selection. Define a canonical server-owned intent-classification/tagging source before applying rules automatically to those lanes; never treat caller tags as authority |
| `hitl.escalation_chain` | `HitlConfig` and `_parse_hitl`; Operator config revisions can replace the section | None. Kernel boot threads only `blocking_verbs` and `approval_timeout_seconds` into `Kernel`/`HITLManager` | Stored and round-tripped only. Timed-out approvals are settled by the expiry janitor, but no chain target is contacted or assigned | Give targets canonical user/channel identities, persist an escalation cursor and attempts, advance it transactionally on timeout, deliver through verified notification routes, and audit success/failure without reopening an expired approval |
| `privacy.pii_redaction` | `PrivacyConfig` and `_parse_privacy`; Operator config revisions can replace the section | None. `boltrig.kernel.pii.redact()` is a tested primitive with no production caller | Does not redact model prompts, tool params/results or adapter payloads. Audit identity scrubbing is separately live; memory secret blocking is separately live | Choose explicit model and adapter boundary hooks, define whether redaction changes schema-bearing fields or instead forces local routing, carry redaction provenance, and bind tests proving secrets/PII cannot escape through chat, workflow, voice tools or direct invoke |
| `privacy.redact_fields` | Same privacy parse / revision path | None | Stored tuple only; no JSON field/path is removed anywhere | Define path syntax, nesting/array semantics and schema-validation order; apply at the same explicit boundaries as PII redaction; record field names but never removed values in audit |
| `privacy.data_residency` | Same privacy parse / revision path | None | Stored label only. The live sensitive-to-local model rule uses `InvocationContext.extra.data_class`, `models.sensitive_endpoint` and endpoint `data_class`; it does not read this privacy field and does not constrain adapters, storage, summaries or memory | Introduce canonical region/boundary identifiers on every processing and storage target; reject incompatible model, adapter, memory, Knowledge, relay and persistence routes before data crosses the boundary; test derived data as well as source data |
| `privacy.retention_days` | Same privacy parse / revision path | `retention_days_from_manifest()` -> worker `_start_retention_janitor()` -> `run_retention_forever()` | Live only for hard-erasing CLOSED conversations and their messages. The janitor can be disabled by `BOLTRIG_RETENTION_INTERVAL <= 0`. A missing/falsy value uses 30 days. Open conversations, work, memory and the audit chain are outside this field | Decide and implement lifecycle-specific retention/hold rules for work, memory, Knowledge, artifacts, call events/transcripts and derived summaries; expose janitor health; reject zero instead of silently mapping it to the default; prove erasure in the deployed worker with Postgres |
| Tenant budget | Hierarchy tier-1 seed or governed `control.budget.upsert` | `Spawner.spawn()` and agent-bound verb invocation call `CostAccountant.reserve()` then true up actual runtime usage | Enforced for model-backed agent runs. Chat uses `Spawner`, so it is covered at tenant scope. A missing budget row means unmetered | Make the intended unmetered state explicit; derive every scope from trusted context; publish coverage/last-charge state |
| Department budget | Hierarchy tier-2 seed or governed budget upsert | `Spawner.spawn()` includes a department only when `prefer.department` is present; `DepartmentHead` supplies its own name | Enforced for fleet-delegated department spawns. Plain Chat and agent-bound verbs use tenant scope only. Direct spawn preferences are not a canonical membership binding | Derive department scope from the authorised work item/principal, not caller preference; bind cross-department bypass tests |
| Workflow budget | Governed budget routes accept and persist `scope_type="workflow"` | None passes a workflow id to `CostAccountant` | Stored policy only. Workflow steps enter `kernel.invoke`; agent-bound steps may consume the tenant budget, while adapter steps are not cost-metered | Stamp trusted workflow id into execution context; reserve/reconcile workflow plus tenant/department scopes for every priced step; define partial-run behaviour and checkpoint-safe reconciliation |
| Budget `window` (`run`, `daily`, `monthly`) | Manifest, governed routes, fleet reservation/true-up, both stores, SDK and Worker | Exact hashed run buckets; durable UTC daily/monthly buckets; automatic selection/rollover; exact reservation receipts and reset generations | Enforced for tenant/department model-backed fleet work; Worker shows current calendar evidence and refuses to invent an aggregate for per-run policy | Remaining coverage is workflow-scoped execution, realtime voice provider usage and direct paid adapters |
| Realtime voice spend | Gateway accepts bounded provider `usage` events and stores usage receipts | No `CostAccountant.reserve()` or `reconcile()` call in call creation, media claim or usage ingestion | Observable estimated/unpriced usage only; tenant/department budget hard stops do not prevent or end provider spend | Reserve before mint/claim, reconcile signed provider usage monotonically, cap session duration/tokens/audio, terminate at hard stop, and prevent replayed/decreasing usage counters |
| Direct paid adapter/provider call | Dispatcher runs schema, grants, idempotency, HITL, rate limit, credential, execute, output validation and audit | Dispatcher has no general cost quote/reservation hook | No general cost-budget enforcement. `voice.speak` is a paid high-consequence adapter example. Agent model calls are covered only because the surrounding `Spawner` reserves first | Add policy-as-data price/quote metadata to priced verbs or adapters; reserve before credential resolution/execution; reconcile from validated usage; preserve the fixed dispatcher order and avoid a second execution path |
| Codex/model provider call | Agent capability resolves a runtime/model route inside `Spawner`; the runtime reports token usage and `_true_up_cost()` prices it | `CostAccountant` before/after the run; trusted model-proxy grants add a separate bounded cell allowance | Covered when reached through `Spawner` or an agent-bound verb. A provider path outside those compositions is not covered by tenant budgets | Make all model execution compositions prove they carry a reservation id; reconcile once across retries/cancellation; join proxy-grant usage to the tenant ledger instead of treating the two ceilings as interchangeable |

Spawn-rule migration is intentionally fail-closed. Before upgrading a tenant
that already has rules, add an explicit `priority` to every manifest rule and
supersede any older stored `spawn_rules` revision that lacks it. The tracked
example shows the required shape; an old or partial policy is not silently
assigned list-order precedence.

## Presentation rule

Worker is the primary task surface, so it authors only tenant and department
budget scopes that have a real enforcement consumer. It may display an existing
workflow-scope row, but must label it stored and unenforced. Window values are
shown as tags with manual reset, not automatic periods.

Operator remains the advanced manifest/revision surface. Its Spawn Rules editor
describes the live matcher and required priority; parsed-only fields still say
“stored” and name the missing consumer. A typed schema is proof of authoring
shape only; the matrix above names the actual runtime consumer.

## Recommended implementation order

1. Close the paid-call budget boundary: trusted scope derivation, workflow scope,
   voice, and priced adapters, followed by durable window rollover.
2. Wire privacy at explicit outbound and persistence boundaries, with residency
   applying to derived data too.
3. Turn escalation into a durable notification state machine.

Each new security or correctness guarantee needs a declared invariant and a
bound test before the UI may remove its “stored only” wording.
