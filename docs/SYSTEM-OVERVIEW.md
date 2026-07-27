# Boltrig - system overview (the whole picture)

> **Runtime currency (2026-07-21):** this is a historical whole-system view of
> the Round Six/Seven implementation. Its Pi, Hermes, and runtime-selection
> sections do not describe the target product architecture. Accepted decision
> 0012 makes Codex the target agent runtime; `docs/PATH-TO-10.md` records the
> incomplete cutover and the still-live legacy residue. Historical labels remain
> below so the implementation it documented can still be understood.

Addendum, not a replacement. The whole-system view that the Pi runtime spec
(`requirements-pi-runtime.md`, Round Six) and the control plane spec
(`requirements-control-plane.md`, Round Seven) sit inside. It does not repeat
their proposals; it gives the layer-by-layer walkthrough, the extension points,
the corrected request-flow model, and the consolidated gap list.

> **Build status (as of Round Seven).** The four gaps this addendum consolidates
> in Section 5 have since been built (Rounds Six and Seven). The original gap
> text is kept below for context; each is reconciled against what shipped in
> Section 6. The honest residue is environmental (Bifrost + live Hatchet are
> external services), not code.

## 1. What Boltrig is

Boltrig is a thin, policy-owning kernel between every action an organisation's AI
agents take and the outside world, forcing every action - chat message, webhook,
or scheduled job - through one fixed, audited path that checks who is asking, what
they may do, and whether a human must approve first, before anything happens.
Everything organisation-specific (agents, integrations, models, rules) is data fed
into that kernel rather than separate code, which is what makes it portable as a
single deployable unit rather than a bespoke build per customer.

## 2. The layers, as a request's journey

### 2.1 Foundation
- **Store** - the single persistence seam; one Protocol satisfied identically by
  an in-memory impl and a Postgres schema. Nothing talks to a database directly.
- **Identity** - resolves who is asking first: token verification, IdP-group ->
  role mapping, delegation.
- **Models** - the domain vocabulary: nouns, verbs (input/output schema +
  consequence level), and verb bindings (adapter vs agent).

### 2.2 The chokepoint
Every side-effecting action runs the same ten-step ordered path regardless of
origin: resolve, validate, check grants, HITL gate, rate-limit, idempotency
replay, resolve credentials, execute, validate output, audit. No second path.
- **Adapters** - how a verb does something deterministic; credentials resolve only
  inside the kernel, never handed to the caller.

### 2.3 Intake and routing
- **Work intake** (`work/normalise.py`) - source-agnostic normalisation to one
  `WorkItem` shape.
- **Chief of staff** - tier-one router; reasoning call with a clean deterministic
  fallback.
- **Department heads** - tier-two, each owning a domain.
- **The spawner** - routing becomes execution: composes skills, picks the cheapest
  capable runtime, enforces depth + budget, runs.

### 2.4 Execution
Four runtime kinds, one agentic. **Script** = deterministic no-LLM fallback.
**Hermes** / **Claude-API** = single-shot, non-tool model calls. **Pi** = the only
multi-step, tool-calling lane, in a severed process reached over HTTP, no
filesystem/process/credential access, given only a model key + a run-scoped MCP
token, every tool call back through the chokepoint.
- **Chat** - a thin conversational layer (persists messages, streams events).
- **Skills** - composable capability fragments, parent-first inheritance, resolved
  at spawn time.

### 2.5 Orchestration
- **Workflows** - selection + generation: stored records matched by intent tag,
  synthesised deterministically or by a runtime proposing steps.
- **Hatchet** - the durability backbone wrapping individual steps; a non-durable
  local fallback stands in when it is not installed.

### 2.6 What makes it portable
- **The manifest** - one typed, env-interpolated document per tenant that the
  kernel and fleet seed from. No core code change to add an org/model/agent/
  integration. The literal mechanism behind "one image, many tenants."
- **Observability** - reconstructs an execution tree from the audit log.
- **UI** - routing, kanban, approvals, the Round Three studios, plus the Round
  Seven Workflow Studio interpreter view + verb palette.
- **The doctrine repository** - the K-1..K-30 invariants live in a separate
  `agent-kernel-doctrine` repo this one conforms to (local guarantees use
  P*/SEC*/FR*).

## 3. Edges - where new things attach

- **3.1 Getting work in** - `work/normalise.py` (a new source = a normaliser to
  the `WorkItem` shape); `SpawnRule` records in the manifest (a declared match
  pattern -> runtime + skills).
- **3.2 New capability, three weights** - Adapters (deterministic actions;
  `AdapterConfig.module_ref` means any importable module, not just builtins);
  Runtimes (reasoning backends; where Pi/Hermes/Claude-API/Script live, and where
  a gateway-fronted call attaches); Skills (pure data, no code).
- **3.3 New judgment** - Verbs + verb bindings (registered data; the agent reasons
  in noun/verb vocabulary, never the backend); Workflows (selection + sequencing).
- **3.4 Constraining what is allowed in** - Identity / Network / Privacy / HITL
  config, each its own governance dimension.
- **3.5 New front doors** - `kernel/app.py`'s HTTP surface reads no policy; it
  authenticates, builds a context, and calls the same `kernel.invoke`. An internal
  kernel MCP face exists (built for the retired Pi sidecar, now serving the Codex
  lane); a broader MCP front door is a future
  surface.
- **3.6 The flywheel edge** - `learn_from_success` re-saves a succeeded generated
  workflow as `source='learned'`, feeding `match()` next time. The one place
  output becomes input.
- **3.7 Watching / editing the edges** - Observability (read edge); the control
  plane (the meta-edge: live amendment dispatched as kernel verbs).

## 4. How a request actually moves (corrected)

- Chat and other sources do **not** converge into one intake flow.
  `ChatService.handle_turn` mints a `WorkItem` and calls the spawner directly; a
  cron/webhook source goes through `normalise.py` then is routed by chief-of-staff
  to a department first. Same destination, different hops.
- Hatchet is **not** where cron/webhooks land - it is downstream, durably wrapping
  an execution that has already been routed. It pulls nothing in.
- (Original) Bifrost is **not** wired in; the runtime resolves a `ModelEndpoint`
  and calls it directly. See Section 6: Round Six added the gateway seam (point the
  endpoint `base_url` at the gateway), but the Bifrost service itself stays
  external.

## 5. What's missing, consolidated (original) and 6. as built

- **5.1 A conversation doesn't remember itself** - the most foundational gap; no
  prior turns threaded into the prompt.
- **5.2 Bifrost isn't wired in** - every Pi-lane call goes straight to a provider.
- **5.3 Workflows are data with nothing reading them** - only two demo workflows
  registered; nothing walks a stored definition's steps.
- **5.4 No live way to change any of this** - departments built once at startup; no
  governed admin surface for models/profiles/workflows.

Recommended order (original): conversation memory -> the workflow interpreter ->
Bifrost + the live control plane.

## 6. Reconciliation - what shipped (Rounds Six and Seven)

| Gap | Status | Where |
| --- | --- | --- |
| **5.1 Conversation memory** | **Built** (Round Six) | `fleet/continuity.py` threads the owner-scoped transcript into the prompt before spawn, deterministic + append-only (SEC-46/49). |
| **5.2 Model gateway / Bifrost** | **Seam built** (Round Six); Bifrost external | `fleet/model_gateway.py` - conversation-keyed binding, `base_url` re-pointed at the gateway, sensitive never re-routed (SEC-47). Bifrost is a service to point at, not in the image. |
| **5.3 Workflow interpreter** | **Built** (Round Seven, the core unlock) | `workflows/interpreter.py` + `WorkflowLibrary.execute` walk a stored definition's steps in dependency order, dispatching each as its own durable boundary through `kernel.invoke` (FR-CTL-02, SEC-50). A workflow defined as data now runs. |
| **5.4 Live, governed control plane** | **Built** (Round Seven) | `ChiefOfStaff` live-reload via `departments_provider` (FR-CTL-01); `config/control_plane.py` makes config amendment governed `control.*` verbs (SEC-51); Workflow Studio gains an Execute view + scoped-verb palette. |

The recommended order was followed: continuity first (Round Six), then the
interpreter and the governed control plane (Round Seven). The remaining residue is
environmental, not code: Bifrost (the cost gateway) and a live Hatchet engine are
external services the box points at; the hard Pi sandbox substrate (agentOS) is
deferred until a real third-party Pi loop replaces the first-party stand-in. The
durable, portable agent box (P7) is now complete for workflows: ship one image,
point it at a manifest plus tenant data, and a data-defined workflow executes.
