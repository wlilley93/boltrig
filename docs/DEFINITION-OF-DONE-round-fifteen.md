# Definition of Done - Round Fifteen (the extension contract)

Brief: pin a vanilla Boltrig and extend it from a per-project bundle, never editing
core; add the missing generic primitives as substrate. Full deliverable:
`docs/extension-contract.md`.

The code was read first (per `AGENTS.md`). Grounding gave three verdicts: no single
bundle loader (adapters loaded only via a hardcoded `_BUILTIN_MODULES`, ignoring
`AdapterConfig.module_ref`); no agent-callable skill shelf (skills load eagerly by
id; `GET /v1/skills` is human-only and even reads the InMemoryStore's private dict,
returning `[]` on Postgres - there is no `list_skills`); MCP outbound complete,
inbound works at runtime but `mcp.consume` is parsed-and-inert.

## What shipped (all generic substrate, content stays per-project)

### The on-demand skill shelf (the substantive gap)

- `boltrig/skills/shelf.py` (new): `SkillShelfAdapter` exposing the `skill` noun -
  `skill.search` / `skill.describe` / `skill.load` - as governed verbs (the
  MemoryAdapter/ControlPlaneAdapter pattern), so the shelf runs the chokepoint
  (grant + audit + tenant scope). Progressive disclosure: `search` returns
  descriptions only (never bodies), `load` resolves inheritance + validates the
  per-job context against `context_requirements` + returns the bound body. A
  loaded skill is data, not authority (SEC-57).
- A `description` shelf-label added to the `Skill` model + the YAML schema +
  `resolve_skill` carry-through + `schema.sql` + migration `0004`.
- `list_skills(tenant)` added to the Store Protocol + both backends (the shelf
  needs real enumeration; Postgres returns the latest version per id). This also
  fixes `GET /v1/skills` being Postgres-blind.
- Registered automatically in bootstrap (manifest + dev-seed paths).

### Bundle loading (extend from outside, no core edit)

- `apply_manifest` now honours an adapter's `module_ref` (`pkg.mod:factory`) when
  the id is not a builtin - a project ships its own adapter as an importable module
  + a manifest entry (FR-EXT-01).
- `_register_consumed_mcp` wires `manifest.mcp.consume` at boot: each external MCP
  server registers an inert MCP-consumer adapter (no verbs until the review gate,
  SEC-22), credential held kernel-side via `${ENV}` interpolation (FR-EXT-02).

## Decision recorded (substrate inclusion, no court)

Adding the `skill.*` verb namespace + the bundle loaders is normal substrate
development - the same shape as the R5 `memory.*` and R7 `control.*` namespaces,
which were built directly per spec. It is additive, generic (no app specifics in
core), data-driven, weakens no guarantee, and adds no new external dependency, so
it does not trip the `AGENTS.md` "stop and surface" trigger (which is for a new
core concept / new external dependency / weakening a guarantee, e.g. the repo
split, which WAS routed). Inclusion-gate verdict: substrate primitive (the engine
owns the shelf mechanism + the loaders; projects own the content).

## Invariants (binding-debt 0)

Five new, all bound: FR-SKILL-01 (descriptions-only shelf), FR-SKILL-02 (load
composes + binds context), SEC-57 (governed + data-not-authority), FR-EXT-01
(adapter by module_ref), FR-EXT-02 (mcp.consume inert at boot).

## Gate (green)

- `pytest`: **141 passed, 14 skipped**.
- `check_invariants.py`: **declared=87, bound_tests=115, binding_debt=0, PASS**.
- `ruff`: clean. Alembic: single head `0004_extension_contract`.

## Honest seams / not done

- The eager spawn path is unchanged; the shelf is the additional on-demand mode.
- The skill `prompt_fragment` body is not templated with the bound context - the
  context is returned alongside the body (validated + bound), not interpolated into
  it; templating is a follow-on if wanted.
- A consumed MCP server still needs the human review/activate step to expose its
  verbs (by design, SEC-22); the bundle only pre-registers it inert.
- `libraries/` is the fixed skills home; a project mounts its skills there. A
  configurable extra skills path is a small follow-on if a project needs to keep
  its shelf outside the mounted tree.
