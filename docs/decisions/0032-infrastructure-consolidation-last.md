# 0032 - Shared infrastructure consolidates last, instance-first

- Status: accepted
- Date: 2026-08-18
- Related: `docs/PLAN-opbox-boltrig-merge-2026-08-17.md` (§2 point 005, §5 push-back 003, Phase 5)

## Context

The unification plan says both sides "share the same pgvector, MinIO etc."
Nothing is shared today, and the deltas are structural:

- Postgres: Opbox runs pgvector pg18; Boltrig stacks run pg16.
- Hatchet: different builds (hatchet-lite v0.91.2 vs a digest-pinned build
  whose version is unrecorded), zero multi-tenant configuration on either
  side, client tokens embedding the gRPC address of their engine.
- Bifrost: Opbox stores config in Postgres; Boltrig manages it in a UI-owned
  volume — merging means shared global provider keys with no namespaces, a
  cross-product blast radius.
- MinIO: Boltrig runs none at all (filesystem vault + Postgres blobs +
  optional S3-compatible code).
- Capacity: the production VPS is 3GB/2vCPU running ~40 containers; "always
  ship together" must fit a measured minimal combined profile or the density
  math fails on the second client.

Consolidation is also the lowest-user-value item in the plan — no user sees
which Postgres engine serves which database.

## Decision

Infrastructure consolidation is scheduled **last** (Phase 5, after the
product integration is proven), and only as far as it pays:

- Share the Postgres **instance** (pg18), keep **separate databases**; migrate
  Boltrig tenant DBs pg16→pg18 by dump/restore per stack, back-to-back with
  that stack's deploy.
- One MinIO per box, Opbox-owned; Boltrig adopts it only if it grows object
  needs.
- Hatchet: pin ONE build first; a single engine is evaluated only after
  multi-tenancy is proven on the demo box with canary workloads.
- Bifrost: stays per-side until a namespace plan exists.
- The minimal combined profile is measured on demo before any second client
  lands on the production box.

## Consequences

- Duplicated stateful services persist through the integration phases — an
  accepted carrying cost, cheaper than a premature migration under load.
- The pre-existing defect (production Boltrig tenants missing the
  hatchet-worker their compose now requires) is fixed in Phase 5, not
  silently by a merge.
- Embedding-model choice (which "shared pgvector" quietly presumes) remains
  the Principal's decision and gates only this phase.
