# The Boltrig extension contract

How a consuming app (Bill&Ben first) PINS a vanilla Boltrig version and extends it
from the OUTSIDE with a per-project bundle - no core edits. Everything a project
adds is DATA the engine loads; the engine provides the mechanism, the project
provides the content.

This is the deliverable of the extension-contract round: the bundle layout, the
on-demand skill shelf, and how a project declares an external MCP server.

## 1. The bundle - what a project ships

A project's bundle is data the kernel loads at boot; none of it is a core edit:

| Bundle piece | How the kernel loads it | Where it lives |
| --- | --- | --- |
| **Manifest** (`manifest.yaml`) | `$BOLTRIG_MANIFEST` / `/app/manifest.yaml` / `manifest.yaml`; `${ENV}` interpolated | the project repo, mounted at the kernel |
| **Adapters** (new verbs) | a manifest `adapters:` entry with `module_ref` (an importable `pkg.mod:factory`) - imported + `build()` + registered | the project's importable package |
| **Skills** (the shelf) | YAML under `libraries/skills/`, scanned at boot (`load_skills_dir`) | the project's `libraries/skills/` |
| **Workflows** | YAML under `libraries/workflows/`, registered as `WorkflowDefinition` data | the project's `libraries/workflows/` |
| **Capabilities / models / budgets / grants** | manifest sections, seeded by `apply_manifest` | the manifest |
| **External MCP servers** | manifest `mcp.consume:` entries, registered inert pending review | the manifest |

The kernel binary is unchanged between projects; only the manifest + the mounted
`libraries/` + the project's importable adapter package differ (P7, one image many
tenants).

### 1.1 Adapters from the bundle (no core edit)

Before, a manifest adapter was only loadable if its id was in the kernel's
hardcoded `_BUILTIN_MODULES`. Now `apply_manifest` honours the adapter's own
`module_ref`, so a project ships its adapter as an importable module:

```yaml
# manifest.yaml (project bundle)
adapters:
  - id: trello
    module_ref: billandben.adapters.trello:build   # the project's own package
    credential:
      id: trello-api
      env: TRELLO_API_KEY            # ${ENV}-interpolated, held kernel-side
```

The kernel imports `billandben.adapters.trello`, calls `build()`, and registers its
`describe()` verbs - a new integration with zero core change (FR-EXT-01).

## 2. The skill shelf - browse and pull on demand

Skills load TWO ways now:

- **Eager (unchanged):** a spawn names skill ids; the spawner loads their bodies
  (with `extends` inheritance) into the agent's prompt. Right for an always-on
  agent with a fixed skill (e.g. the Bill&Ben companion).
- **On demand (new):** an agent BROWSES the project's shelf by description and
  pulls one off it only when a job matches - progressive disclosure, not every
  body in context. Right for task/worker flows ("do an ADGM renewal workup").

The shelf is three governed verbs (the `skill` noun), registered automatically -
generic engine mechanism, project content:

- `skill.search {query?, limit?}` - the shelf: `[{id, version, description,
  tool_grant_count, extends}]`, **descriptions only, never the body** (FR-SKILL-01).
- `skill.describe {id}` - one skill's selection metadata: its description, the
  `tool_grants` it wants, and its `context_requirements` (the JSON Schema the job
  must satisfy). Still no body.
- `skill.load {id, context?}` - resolves the skill (inheritance merged), validates
  the per-job `context` against `context_requirements`, and returns the composed
  body bound to that context: the customised instance for this run (FR-SKILL-02).

A skill carries a `description:` (the shelf label, the "when to use"). Loading
returns the skill's `tool_grants` as DATA (what it wants); it does NOT grant them -
the caller still only holds its own grants, so a loaded skill cannot escalate
(SEC-57, the same data-not-authority rule as recalled memory). Every shelf call
runs the chokepoint (grant-checked, audited, tenant-scoped).

```yaml
# libraries/skills/renewal/adgm.yaml (project content)
id: renewal/adgm
version: 1.0.0
extends: renewal/base
description: Do an ADGM company renewal workup.   # the shelf label
prompt_fragment: |
  ...the procedure...
tool_grants: [ matter.read, ticket.create ]
context_requirements:
  type: object
  properties: { entity_id: { type: string } }
  required: [entity_id]
```

## 3. MCP - both directions

- **Outbound (vanilla):** the kernel exposes the caller's scoped verbs as MCP tools
  at `POST /v1/mcp`, run-scoped, every `tools/call` through the chokepoint. A
  project's verbs become MCP tools automatically; nothing to wire.
- **Inbound (declare in the bundle):** an external MCP server becomes kernel verbs
  via the MCP-consumer adapter. Declare it in the manifest:

```yaml
# manifest.yaml (project bundle)
mcp:
  server:
    enabled: true
  consume:
    - id: linear-mcp
      url: https://linear-mcp.internal
      credential: ${LINEAR_MCP_TOKEN}    # ${ENV}-interpolated, held kernel-side
```

At boot each entry registers an **inert** MCP-consumer adapter (it exposes no
verbs yet); an admin activates it via the review/activate route (SEC-22), after
which its tools become governed kernel verbs. The credential is held kernel-side
and never handed to an agent (FR-EXT-02). The runtime route `POST /v1/mcp/servers`
still works for ad-hoc registration.

## 4. Constraints honoured

Everything added here is a generic substrate primitive (no Bill&Ben specifics in
core); credentials resolve inside the kernel only; everything registers as data;
and each guarantee is pinned to an invariant at binding-debt 0 (FR-SKILL-01/02,
SEC-57, FR-EXT-01/02). Per-project adapters / skills / workflows / MCP config live
in the consuming app's bundle, never in Boltrig.

## 5. So Bill&Ben can

Pin a Boltrig version, then ship a bundle: its Trello/Postgres/Linear adapters
(`module_ref`), its companion + task skills (`libraries/skills/`, the shelf), and
its external MCP servers (`mcp.consume`) - plugging into the engine without
touching it. The companion is one eager skill; the task shelf is what a spawned
worker pulls from.
