# 0036 - Multiple bindings land beside verb_bindings, not through it

- Status: accepted
- Date: 2026-08-18
- Related: `docs/SPEC-capability-doctrine.md` (§8, §10 step 2, §11.1-§11.3),
  migration `0079_capability_routing_shard`, decision 0031

## Context

SPEC §11.1 measured the single-binding contract at six enforcement sites and
recorded that a multi-binding change "must land at all six together". Read
literally that means widening `verb_bindings` itself: dropping its
`(verb_id, tenant_id)` primary key, making `get_binding` plural, and reworking
every one of its ~20 call sites and the dispatcher with them.

That reading conflates the two things §1 of the same document separates. A
**source operation** is executed by exactly one adapter — `hubspot.contact.search`
runs on the HubSpot adapter and nothing else. A **capability** is the plural
one: `crm.contact.search@1` may be implemented by three CRMs at once. The
constraint §11.1 found is only wrong if `verb_bindings` is asked to carry the
capability layer, which it never was.

## Decision

The plural layer is a NEW table, and `verb_bindings` narrows in meaning:

- `capability_bindings` carries `binding_id` as its own identity, so a second
  binding for one capability coexists with the first. `provider_connections`,
  `source_operations` and `routing_policies` complete the shard.
- `verb_bindings` keeps `(verb_id, tenant_id)` and now means "which adapter
  executes this source operation" — 1:1, and correct.
- The dispatcher resolves a stored verb id exactly as before. Only a name that
  is NOT a stored verb reaches the router, so routing can add a destination
  where there was a 404 and can never move an existing one.

The six sites are therefore disposed of as follows, and SPEC §11.1 is amended
to record it rather than left to be read the old way:

1. **PK `(verb_id, tenant_id)`** — kept; capability identity is `binding_id`.
2. **`ON CONFLICT` replace** — `upsert_capability_binding` conflicts on
   `binding_id`, so a sibling binding is never overwritten.
3. **`get_binding` singular** — kept; `list_capability_bindings` is the plural
   read and `resolve_execution_plan` collapses it to one target.
4. **`bind_verb_to_agent`** — unchanged; it re-points one source operation.
5. **`ensure_activation_safe`** — unchanged, and deliberately: raw verb
   ownership stays exclusive. Two adapters may implement one capability; they
   may not both claim one verb id.
6. **`_enabled_tools`** — joined by `_enabled_capabilities` in the connection
   projection, because "12 verbs" stops being the honest answer once a
   capability layer exists (SPEC §6).

§11.2's one-live-connection-per-adapter index is likewise not reshaped: the
routing identity moved to `provider_connections`, which carries no such
uniqueness, and `integration_connections` keeps its rule as the catalogue
setup flow's own constraint. That flow still cannot provision a second live
connection for one adapter — a real limit, recorded as SPEC §11.9 rather than
papered over, because the credential model (one credential reference per
adapter) is what actually binds there, not the index.

## Consequences

- The shard is additive: no existing table altered, no existing call site
  changed, and the parity fence is a test asserting a stored verb id still
  resolves the way it always did.
- Two mechanisms exist where one might be expected. The end state is that
  `verb_bindings` keeps only its execution role while every model-facing name
  becomes a capability; until then, an operator reads two tables.
- Fan-out reads and canonical transforms are NOT in this shard (doctrine
  step 3). Two eligible bindings for a read therefore refuse with
  `route_required` rather than merging — honest, and the marker test says so.
