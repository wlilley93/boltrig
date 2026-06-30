# Nankle control plane spec (Round Seven)

Live administration of models, agent profiles, and workflows - and what closes
the gap to a durable, portable agent box.

- **Status:** Draft, grounded against wlilley93/Nankle (main) as provided.
- **Scope:** the administration / control-plane layer - amending model-gateway
  config, permanent agent profiles, and Hatchet workflows without a redeploy,
  plus the kernel-governance requirement any amendment carries.
- **Companion to:** the Pi runtime spec (`requirements-pi-runtime.md`). That spec
  covers the runtime path; this one the authoring/administration path.

## 1. Summary

One place to amend model-gateway config, permanent agent profiles, and Hatchet
workflows live, without a code deploy, while everything an amendment touches
stays inside the kernel's existing governance (audited, grant-checked,
HITL-gated). Most of this is already true. The one real blocker: **nothing today
walks a stored workflow definition and executes it against Hatchet** - two
hand-coded demo workflows are registered; nothing generic interprets the rest.
Closing that one gap turns "edit YAML and redeploy" into "amend the box while it
runs" for workflows. The destination is P7: a durable agent box, deployable
anywhere - one image, many tenants, everything org-specific as manifest + env.

## 2. What is already data (store-backed, upsertable - not code)

- **2.1 Agent profiles.** `config/manifest.py` `apply_manifest` converts every
  `HierarchyTier` (permanent org chart) and `EphemeralRuntime` (child profiles)
  into an `AgentCapability` via `store.upsert_capability` - real upserts.
  **Gap:** `fleet/chief_of_staff.py` `ChiefOfStaff` takes `departments` once at
  construction and routes against that in-memory list; it does not re-read the
  store per call, so a department edit needs the object reconstructed.
- **2.2 Model endpoints.** Upserted the same way (`store.upsert_model_endpoint`);
  `PiRuntime` resolves its endpoint per run from what the spawner hands it, so a
  gateway base_url is just another upsertable record.
- **2.3 Workflow selection.** `workflows/library.py` `WorkflowLibrary.register`
  persists a `WorkflowDefinition` via `store.upsert_workflow`; `match()` picks the
  best-overlapping definition by intent tag, against store records.
- **2.4 Workflow definitions are already a small generic shape, not code.** The
  `definition` field is a small JSON dict: name, version, trigger, and a list of
  steps, each with id, parent ids, an action string, a description.
  `workflows/generator.py` builds this shape two ways - a deterministic
  five-stage pipeline (understand, plan, execute, verify, report) with no
  reasoning, or `generate_workflow_reasoned` (a runtime proposes steps, validated,
  falling back to the deterministic pipeline on any failure). A human authoring
  visually and an agent generating one converge on the identical stored shape.

## 3. The one real gap: no generic interpreter

`fleet/hatchet_app.py` registers exactly two workflows: `ping` and `hitl_demo`.
Nothing walks a `WorkflowDefinition`'s steps and dispatches them as real,
individually durable Hatchet tasks. `WorkflowLibrary.trigger` gets a workflow as
far as a queued run descriptor; it does not execute the steps.

Proposed: a single generic Hatchet task that looks up a `WorkflowDefinition` by
id, walks steps in dependency order honoring each step's parents, and dispatches
each step's action as its own Hatchet step (so each step gets Hatchet's
retry/durability, not one opaque enqueue). Then a new/changed workflow is purely
a data change.

**Gap (design first):** how a step's `action` string resolves to a dispatch
target is not designed. The pipeline stage names read as agent-reasoning stages,
suggesting some actions route to the Pi runtime rather than a kernel verb - so
the interpreter most likely needs two dispatch kinds. Design this explicitly
before building.

## 4. Authoring surface: native, not n8n

The real question is what a human uses to author/edit a `WorkflowDefinition`.
- **Recommended:** a minimal native visual editor against the existing schema -
  nodes are steps, edges are parent links, and the node palette is populated live
  from the kernel's own scoped verb registry (`kernel/registry.py` returns only
  the verbs a caller is scoped to see). No second trust boundary to bridge.
- **n8n** is NOT recommended as the runtime (a second engine, its own node
  vocabulary + execution model; bridging its connectors back to grant-checked
  kernel verbs is ongoing translation work). Its nodes-and-wires UX is a fine
  reference for feel only.
- **Claude Code's role** narrows to teaching the interpreter a new action kind
  when a genuinely new capability must exist; thereafter every workflow is data.

## 5. The control plane surface

| Surface | Attaches at | Status |
| --- | --- | --- |
| Model gateway (Bifrost) | `ModelEndpoint` records + the conversation-binding store | Mostly ready - UI only |
| Agent profiles | `HierarchyTier`/`EphemeralRuntime` -> `AgentCapability` via `apply_manifest` | Ready, except ChiefOfStaff live-reload (2.1) |
| Hatchet workflows | `WorkflowDefinition` records via the generic interpreter (S3) | Blocked on the interpreter |
| Kernel config | registry/grants/budgets/blocking-verb tables, all store-backed | Ready - see 5.1 |

### 5.1 The governance requirement

P2 (one dispatch chokepoint) is binding. A second ungoverned write path for
amending config - even a well-intentioned admin console - is exactly what P2
rules out. Control-plane writes should be dispatched as **kernel verbs**, not
direct `store.upsert_*` from an unguarded admin endpoint, so every amendment
inherits audit + grant-checking + HITL-gating for free.
**Gap:** `apply_manifest` writes several record types in one batch pass outside a
verb call; whether it can cleanly retrofit through kernel verbs is unconfirmed.

## 6. The durable agent box

P7 is the destination: one image, many tenants, everything org-specific as
manifest + env. True today for identity/models/agents/adapters (all
`load_manifest` + `apply_manifest`). Not yet true for workflows: new behavior
requires the deployment to hand-wire Hatchet defs (`fleet/workers.py` describes
this as layered on by the deployment, outside the core). The interpreter (S3) is
the one piece that finishes the picture. Caveats: the admin/authoring UI is a new
surface this spec proposes (not in `ui/` today), and Bifrost is external (point
at or bundle, not inside the image).

## 7. Sequencing

1. Fix ChiefOfStaff's live-reload gap (2.1).
2. Design the action-to-dispatch-target mapping (kernel verb vs Pi runtime)
   explicitly, before writing the interpreter.
3. Build the generic Hatchet interpreter (S3). The core unlock.
4. Build the native low-code workflow editor (S4), palette from the scoped verb
   registry.
5. Route all control-plane writes through kernel verbs (5.1), resolving the
   apply_manifest retrofit question first.
6. Validate "ship one image, point at a manifest + tenant data" end to end,
   including a workflow defined purely as data.

## 8. Open items (verify against code before relying on)

- Whether Hatchet itself offers a visual workflow-authoring product.
- Whether `apply_manifest`'s batch-upsert can cleanly route through kernel verbs.
- The action-to-dispatch-target mapping is not yet designed; the stage names are
  suggestive, not confirmed.
- Whether the admin/authoring UI belongs in the existing `ui/` console or a
  separate surface.

## Note (build-time): account for Round Three

Round Three already shipped Config Revisions + Admin Console, Skill/Adapter/
Workflow Studios, observability, and `FR-WFS-04` ("a registered workflow becomes
a live durable run"). Ground what actually exists before building so this round
adds the genuinely missing interpreter + governance, not a duplicate console.
