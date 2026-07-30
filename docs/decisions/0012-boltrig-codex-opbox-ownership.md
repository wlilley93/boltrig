# 0012 - Boltrig, Codex, and Opbox ownership

> Amended by decision 0021: Codex remains the only general target agent runtime.
> A narrowly scoped `realtime_voice` dialogue/media exception may request only
> kernel-generated tools that re-enter the dispatcher; it owns no authority,
> workflow, connector, memory, or durable credential.

- Status: accepted
- Date: 2026-07-15
- Supersedes: the runtime and workflow-ownership decision in 0010
- Preserves: 0010's single-engine, whole-domain cutover, audit, and rollback
  conditions

## Context

Boltrig currently has several overlapping execution concepts. OpenCode is a
one-shot coding-agent runtime, Ultracode and its Hatchet tasks schedule phase
agents, Mastra compiles another orchestration shape into Ultracode, and Herdr
provides host-terminal control. Opbox separately owns customer data, domain
actions, authorization, and workflow behavior.

That shape is too thick. It duplicates agent scheduling, spreads workflow truth
across products, and makes it difficult to prove which system controls
authority, durable state, cancellation, and real-world effects.

Codex now provides the execution surface Boltrig needs: App Server threads and
turns, streamed execution events, approvals, interruption, and native
subagents. Boltrig should integrate that surface without recreating Codex's
internal agent scheduler and without allowing Codex to become an authority or
domain-system boundary.

Decision 0010 correctly prohibited two engines from owning one workflow run.
It assigned Opbox workflow ownership during the earlier pinned-runtime
transition and required a later explicit decision before moving that ownership.
This decision is that explicit change. It supersedes only 0010's runtime and
workflow-ownership assignment. It does not rewrite history or weaken 0010's
single-engine and whole-domain migration rules.

## Decision

The governing boundary is:

```text
Boltrig controls authority and workflow.
Codex controls execution.
Opbox controls real-world domain effects.
```

### Boltrig owns

- root runs and their durable lifecycle
- phases and meaningful work items
- the canonical work ledger and durable work queue
- agent profiles and versioned skill selection
- effective grants and approval state
- retries, leases, replacement workers, cancellation, and verification
- mapping Boltrig run identifiers to Codex thread, turn, and item identifiers
- normalized event history, audit correlation, and final synthesis
- the human-facing projection of work, including Kanban-style views

Hatchet may execute durable Boltrig tasks, but it is not the canonical workflow
state. A board is also a projection, not a source of truth.

### Codex owns

- one bounded phase thread and the turns within it
- reasoning, local tool use, streamed execution, and context management
- native subagent creation, coordination, and result collection inside a phase
- execution-level command, file-change, and permission requests

Boltrig creates and governs a Codex phase. It does not create a competing
child-agent scheduler. Native subagent activity may be observed and audited,
but it does not become a separate Boltrig assignment unless a later product
decision explicitly promotes a meaningful handoff into the work ledger.

### Opbox owns

- customer and domain data
- domain invariants and server-side authorization
- governed domain tools and their schemas
- execution of real-world domain effects
- domain-side audit evidence

Codex never receives durable Opbox credentials. Every Opbox tool call enters
through a short-lived Boltrig MCP grant, the Boltrig kernel chokepoint, and
Opbox's own authorization and audit controls.

## Final production stack

```text
Boltrig UI and API
    -> Boltrig control plane and canonical work ledger
    -> Hatchet phase-job execution
    -> Codex supervisor
    -> Codex App Server
    -> Codex root phase thread and native subagents
    -> short-lived, revocable Boltrig MCP grant
    -> Boltrig kernel authorization chokepoint
    -> governed Opbox domain adapter
    -> Opbox data and real-world effects
```

Postgres remains the canonical store for workflow, audit, approval, and ledger
state. Redis provides ephemeral coordination, event delivery, and immediate
grant revocation. Hatchet provides durable job execution. Codex App Server is
the production integration interface. Codex CLI remains a developer and
operator surface and may connect to App Server when useful.

OpenCode and Herdr are removed after staged parity. Mastra and Ultracode cease
to be active orchestration engines. Historical records keep their original
labels.

## Runtime and transport rules

1. Production integrates with Codex App Server, not by scraping or automating
   the Codex terminal UI.
2. Each App Server is supervised and reachable only through stdio or a private
   same-host Unix socket.
3. Boltrig does not expose an unauthenticated remote WebSocket listener.
4. The Codex CLI version and its generated stable protocol schema are pinned as
   one release unit. A binary/schema mismatch fails closed.
5. Experimental App Server methods or fields are disabled in v1 unless a later
   decision identifies a required capability and gives it its own compatibility
   and rollback gate.
6. User-supplied text cannot override the model, sandbox, approval mode,
   runtime identity, or App Server configuration selected by Boltrig policy.

The first verified integration target is `codex-cli 0.144.3`. This is a target,
not a claim that production packaging is already complete. The Beelink host had
that release in its Codex cache, not on the service `PATH`; the integration must
still package and checksum-pin it.

## Agents, profiles, and skills

- Every native subagent instance is ephemeral.
- A reusable role is static birth configuration: instructions, model policy,
  tool and sandbox defaults, and the skills it may select.
- A Boltrig profile selects a versioned skill catalogue for a run. It does not
  inject every skill body into every context.
- Selecting a skill requests or narrows capabilities. It never grants
  authority.
- Prompts, messages, memory, skills, and model output are data. None may alter a
  worker's authority, sandbox, model policy, or approval state.

Effective authority is always deny-dominant and no wider than:

```text
current parent grant
  intersect profile ceiling
  intersect selected-skill requirements
  intersect current workspace and data policy
  intersect current approval state
```

The intersection is evaluated when a phase starts, when it resumes, and again
for every governed tool call. Queued grant snapshots are not authoritative.

## Security rules

1. Codex workers receive no durable Opbox or parent-control credentials.
   Upstream Codex authentication is supervisor-managed and is never treated as
   a Boltrig or domain grant.
2. Boltrig mints opaque, short-lived, run-and-phase-scoped MCP grants with an
   expiry, unique identifier, and immediate revocation.
3. Every tool call still passes Boltrig authorization, autonomy policy, rate
   limit, approval, idempotency, credential resolution, validation, and audit.
4. Opbox repeats its own domain authorization and emits correlated domain audit
   evidence.
5. Cancellation first prevents new tool admission, revokes the MCP grant, then
   interrupts the Codex turn and reconciles any call already accepted.
6. App Server event payloads are untrusted execution data. They cannot drive an
   authority or approval transition without a validated Boltrig command.
7. Codex runtime homes and workspaces are stack-owned and tenant/workspace
   isolated. Production never reads a developer's personal `.codex` state.
   A private `CODEX_HOME` is necessary but not sufficient: Codex also discovers
   repository skills from `.agents/skills` between the working directory and
   repository root, and project trust does not disable that discovery. A cell
   therefore runs from a sanitized workspace projection with an isolated
   `HOME`, materializes only digest-pinned selected skills, disables unselected
   bundled skills, and must pass a pre-thread `skills/list` allowlist check.
8. No unrestricted peer chat exists in v1. If sibling messaging is added later,
   it must be a typed, audited, expiring Boltrig mailbox with no
   authority-changing message types.

## Work and messaging model

The canonical hierarchy is:

```text
root run -> phase -> work item -> assignment -> result -> verification
```

Workers return structured findings, evidence, blockers, handoffs, and
completion events to Boltrig. Root-mediated communication is the v1 model.
Boltrig does not create a card for every thought, token, tool call, or native
subagent event.

## Identity

Boltrig's existing Organisation, User, OrgMember, and WorkspaceMember records
remain the product identity boundary. An organisation user may have an internal
Codex execution-principal mapping, but Boltrig must not claim that it can mint an
upstream ChatGPT account.

The verified 0.144.3 App Server schema can report programmatic Agent Identity as
an account mode, but its stable login-start request does not provision one.
Production must therefore choose and document a supported service API identity,
per-organisation identity, or interactive user-login model before write phases
are enabled.

## Migration and rollback

The move follows whole boundaries:

1. Add the Codex adapter behind the existing runtime seam.
2. Prove read-only thread, turn, event, resume, steer, and interrupt behavior.
3. Add expiring grants, profiles, skills, and the canonical work ledger.
4. Enable bounded native Codex subagents only in read-only phases.
5. Enable approval-gated writes and Opbox effects.
6. Cut over selected complete workflow domains, then make Codex the default.
7. Remove OpenCode, Herdr, Mastra orchestration, and Ultracode scheduling only
   after parity, observation, and rollback gates pass.

An in-flight root run never changes engine. Rollback routes new root runs to the
previous release while existing runs finish, fail safely, or are explicitly
cancelled under their original ownership. Immutable audit and historical
execution records are never rewritten.

Legacy code remains deployable until the agreed observation window has passed,
there are no unexplained ledger or audit divergences, cancellation has been
proven under load and failure, and a previous signed release plus database
backup has passed a restore drill. After legacy deletion, rollback is a release
and data-recovery operation rather than a feature-flag switch.

## Consequences

- Boltrig becomes thinner at the agent-execution layer while becoming the clear
  durable workflow and governance authority.
- Codex supplies mature reasoning, tool use, context handling, and native
  subagents without Boltrig duplicating those systems.
- Opbox remains the final server-side authority and only executor for its
  domain effects.
- Existing HTTP compatibility can remain while internal execution changes.
- The integration requires a durable grant broker, canonical ledger, normalized
  event history, and genuine interruption before writes are safe.
- The currently active OpenCode, Herdr, Mastra, and Ultracode paths remain in
  place until the staged cutover proves parity; this ADR does not claim that the
  migration has already been implemented.
