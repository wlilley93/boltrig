# Flat named agents, ephemeral delegation, and peer communication

Programme decision updated 2026-08-20. This supersedes the earlier proposed
Chief/Department/Tier-3 serving topology. The implementation is a clean-room
Boltrig design: external systems were used as behavioural evidence, not as code
or a protocol specification.

## 1. The serving model

There are two kinds of agent:

- A **named agent** is a durable identity and address. Every named agent is a
  tier-1 peer. The configured `agents.default` receives unaddressed intake but
  has no structural authority over the other names.
- An **ephemeral agent** exists for one bounded delegated task. It returns
  evidence to its named parent and disappears. It has no mailbox, durable
  persona, peer address, or right to send peer messages.

There is no live tier 2 or tier 3. `HierarchyConfig`, `ChiefOfStaff`, and
`DepartmentHead` remain only where required to read an old manifest or reuse
already-proven bounded fan-out mechanics. `build_org` never constructs that
hierarchy: it normalises old input into the same flat named roster.

This supports both coordination styles the product needs:

1. **Peer dialogue**: a named agent asynchronously sends ASK or TELL to another
   named peer; an ASK may produce exactly one REPLY.
2. **Direct delegation**: a named agent splits work into bounded tasks and
   spawns one-task ephemeral children, then remains responsible for synthesis.

Peer dialogue is not delegation. A peer keeps its own identity and authority;
an ephemeral child receives a narrowed task contract from its parent.

## 2. Long-lived means logical, not resident

A named agent is not a model process kept alive forever. Its durable state is:

- a manifest-owned profile and address in `named_agents`;
- ordinary user conversation state for direct chat;
- an immutable peer-message log and per-agent logical session;
- append-only summary checkpoints plus a recent verbatim tail;
- current policy, memory, budgets, and model route resolved again per turn.

The runtime can be started for a turn and discarded afterwards. On the next
wake, Boltrig reconstructs the trusted frame from the current profile and policy,
then injects prior authored messages and derived summaries only inside untrusted
data envelopes. Compaction reduces model context; it never rewrites or deletes
the source message log.

## 3. The switchboard, not a socket

`agent.send` is a governed kernel verb. It is deliberately absent from the
sandbox shell and from ephemeral children. A named runtime receives it as a
named tool only when its kernel-stamped invocation context proves that it is a
registered tier-1 address.

The sender submits:

```json
{
  "to": "engineering",
  "kind": "ask",
  "content": "Can you review the migration boundary?",
  "conversation_id": "optional-existing-dialogue"
}
```

There is no caller-controlled `from` field. The kernel derives the sender from
the invocation context, captures the effective authority envelope, persists the
message and delivery row, and only then publishes a sent event. The immediate
result is a delivery receipt, not the recipient's answer. A later mailbox wake
runs the recipient; a resulting REPLY is another persisted message and later
wake for the original sender.

ASK, TELL, and REPLY are closed message kinds:

- ASK may atomically create one deterministic REPLY when delivery completes.
- TELL is information or a request for governed action and never auto-replies.
- REPLY closes the automatic response edge and cannot trigger a reply loop.

There is no model-to-model network connection, cross-tenant address, broadcast
primitive, or hidden bash command. Future rooms can fan one room message out to
bounded individual deliveries at the switchboard boundary without changing the
one-recipient delivery contract.

## 4. One identity, one active turn

All products that can wake a named identity share `AgentTurnCoordinator`. The
source is reduced to a transport-neutral lane:

1. `interactive` - a user is waiting;
2. `peer` - persisted agent mail;
3. `background` - filed work, routines, channels, and other asynchronous jobs.

Only one turn for an address may hold the fenced distributed lease at a time.
Interactive waiters outrank peer mail, and peer mail outranks background work;
FIFO breaks ties within a lane. Waiters expire so an abandoned request cannot
block the identity indefinitely. Active turns heartbeat their lease. Completion,
failure, and automatic reply insertion require the exact unguessable lease token,
so a stale worker cannot publish a second answer after another worker takes over.

This coordinator is intentionally independent of chat, the work pump, and the
mailbox. A future cron host, group orchestrator, external channel, or different
model runtime must join the same seam rather than inventing another notion of
whether an agent is busy.

## 5. Authority and tool surfaces

Identity does not grant ambient power. A turn's usable tool surface is the
intersection of the captured principal ceiling, current tenant ceiling, adapter
policy, explicit denies, workspace/scope policy, and the lane's trusted runtime
profile.

Peer delivery preserves that rule across time:

- enqueue validates that both endpoints are enabled named agents in one tenant;
- the immutable message stores the sender's authority envelope;
- delivery validates the envelope again and seats the recipient as the actor;
- explicit denies remain deny-dominant;
- `agent.send` is added only after the tier-1 identity check;
- an ephemeral child receives an explicit `agent.send` deny, even if its parent
  had a broad wildcard grant;
- mailbox read APIs never expose the stored authority envelope.

The model sees named tools, not implementation handles. Shell/filesystem tools,
external MCP tools, peer messaging, and future room posting can therefore be
different per-turn hands over one kernel dispatcher without becoming separate
security systems.

## 6. Persistence and observability

Migration `0084_named_agent_mailboxes` adds:

- `named_agents` - durable profiles and the intake-default flag;
- `agent_turn_leases` / `agent_turn_waiters` - cross-worker serialization and
  lane scheduling;
- `agent_messages` - immutable authored envelopes;
- `agent_message_deliveries` - retry, lease, and terminal delivery state;
- `agent_sessions` / `agent_session_summaries` - logical continuity and
  append-only compaction checkpoints.

Every table is tenant-keyed and RLS-fenced. Message events distinguish sent,
received, delivered, replied, and failed. Failure is visible and bounded;
undeliverable mail is never silently dropped. Human-facing inbox projections
return content and delivery status but not captured grants.

## 7. Serving paths

- Direct chat runs the configured default named agent as a tier-1 identity and
  uses ordinary conversation continuity.
- Addressed work goes straight to the named address. Unaddressed work goes to
  `agents.default`. Unknown addresses park for a human instead of being inferred.
- The work pump alternates peer and filed-work opportunities for throughput;
  the per-agent coordinator then applies identity-local wake priority.
- Named work owners may use governed peer messaging during synthesis and may
  delegate bounded tasks to ephemerals. Ephemerals cannot become peers by
  choosing a colliding actor string.

## 8. Library boundary

Actor frameworks, durable workflow engines, and message brokers each solve a
piece of this problem, but none replaces Boltrig's combined tenant/RLS,
deny-dominant authority, kernel tool mediation, work tree, HITL, event stream,
and model-runtime contracts. Boltrig therefore keeps a small domain-level
switchboard over its existing store and Hatchet seam rather than importing a
second orchestration kernel. A broker can later carry wake notifications and an
actor runtime can host workers, provided the database remains the delivery and
lease authority.

## Standing risks

- Message compaction is derived state. Any future learned/model-generated
  summarizer must remain untrusted and reproducible from the immutable log.
- A room or subscription fan-out needs an explicit recipient cap and one
  delivery per member; it must not introduce an unbounded broadcast verb.
- A new wake source must use `AgentTurnCoordinator` and the kernel dispatcher;
  direct runtime calls would reintroduce concurrent selves or authority drift.
- The masking-gate chain stops at its first failure; run the full local quality,
  migration parity, RLS, and store parity gates before deployment.
