# 0011 - Boltrig v2 memory topology

- Status: accepted
- Date: 2026-07-09
- Supersedes: 0008 for Boltrig v2 deployment defaults

## Context

Boltrig v2 has selected Mem0 as the primary memory product in the stack, while
the repository already contains native memory engines and a Cognee integration
path. The question is whether Cognee still has a role and whether a deployment
may write to more than one memory backend.

The governing rail remains unchanged: all memory operations enter through
`memory.*` kernel verbs. A memory backend is never an authority boundary.

## Decision

Boltrig v2 will use a kernel-led memory fanout topology:

- Boltrig's memory ledger is the source of truth.
- Mem0 is the primary operational memory projection for ordinary agent recall.
- Cognee remains as a secondary graph/enrichment projection for corpus cognition,
  relationship extraction, and explicit deep-recall workflows.
- The native/local engines remain development, offline, test, and fallback
  implementations.
- Agents do not write directly to Mem0 or Cognee. They call `memory.remember`
  through MCP -> Kernel.
- The kernel commits the governed memory event once, then a projection/fanout
  worker writes to configured backends.

The example manifest may keep `memory.engine: local` and disabled Mem0/Cognee
projections until their adapters are installed. That is a runnable compatibility
default, not the v2 production topology.

This is dual projection, not active-active memory.

## Rules

1. **One source of truth.** The Boltrig memory event/ledger owns provenance,
   scope, erasure, audit, and poisoning decisions.
2. **Primary recall defaults to Mem0.** Agent prompts use Mem0 unless a workflow
   explicitly asks for graph/deep recall.
3. **Cognee is secondary.** Cognee may enrich and index the same governed events,
   but it must not independently create authority-bearing memory.
4. **No dual authority.** Mem0 and Cognee cannot independently mutate, correct,
   summarise, or delete canonical facts.
5. **Backend status is per projection.** Each projection records `pending`,
   `written`, `failed`, `deleted`, or `delete_failed`.
6. **Erasure fans out.** A forget/delete action first marks the canonical memory
   event erased, then attempts deletion from every projection and reports any
   failed backend.
7. **Reads are labelled.** Returned memory identifies its projection source and
   remains untrusted prompt data.
8. **Projection execution is swappable.** Deployments can keep projection writes
   inline for development or set `memory.fanout.execution: queued` so Hatchet/the
   local executor runs one pure-data projection task per backend operation.

## Consequences

- Cognee still has a clear place: slower, deeper graph/corpus enrichment.
- Mem0 becomes the day-to-day recall path for agents.
- The system can write to both without split-brain because only the kernel ledger
  is authoritative.
- The v2 implementation now has Mem0/Cognee projection adapters, a
  projection-status/fanout seam, optional queued projection tasks, and a primary
  projection recall seam. Reads are labelled, and the compatibility engine path
  is labelled when a primary projection is unavailable. The existing
  local/Cognee/native memory tests remain valuable because they bind the
  kernel-side invariants that every projection must obey.
