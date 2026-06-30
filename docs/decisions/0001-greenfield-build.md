# 0001 - Boltrig is a greenfield build from the SRS

- Status: accepted
- Date: 2026-06-28

## Context

Boltrig implements the "Hermes Fleet" SRS: a self-hostable agent-orchestration
platform built around a thin kernel and a permanent fleet that spawns ephemeral
workers. The same doctrine (one dispatch chokepoint, stable nouns and verbs,
everything-as-data, credentials resolved only inside the kernel) already appears
in sibling estate work: the Hermes runtime, the Phoenix matter stack, and the
Opbox kernel all enforce a single chokepoint with a noun/verb registry and a
capability/grant model. Those codebases carry vertical concerns (matters,
documents, tenants-as-system-of-record) entangled with the doctrine.

## Decision

Build Boltrig greenfield, directly from the SRS, as a clean-room reference
implementation of the chokepoint + noun/verb doctrine, rather than forking a
sibling.

- The kernel implements policy in composable components and nothing in the
  transport. Integrations, skills, workflows, the agent org chart, and
  credentials are data loaded from the manifest and `libraries/` (P1, P7).
- The guarantees are pinned as binding invariants with a machine-checked gate
  (`scripts/check_invariants.py`, `tests/invariants.yaml`), so the doctrine is
  enforced mechanically, not by convention.
- The store, inference back ends, durable execution, and identity providers are
  Protocol seams; the in-memory store and the self-contained `memory-tickets`
  adapter let the whole kernel run and be tested with no external services.

## Consequences

- A small, dependency-light core that runs and is fully tested offline, with the
  same images running every environment (config differs via env + manifest).
- Some external legs are seams (live Hatchet, live OIDC, live MS Graph / Jira /
  CRM, on-box inference) that need their services or credentials to exercise;
  this is recorded honestly in `docs/DEFINITION-OF-DONE.md`.
- Relationship to the estate: Boltrig does not depend on Hermes, Phoenix, or
  Opbox. It is the consolidation reference for the shared doctrine - the place
  to read (and test) the chokepoint + noun/verb + grant model in isolation,
  free of any one vertical. Where a sibling needs to converge on the doctrine,
  Boltrig is the yardstick, not a runtime dependency.
