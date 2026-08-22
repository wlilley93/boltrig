# 0034 - Files/tiptap extraction is deferred, and the plan is split

- Status: accepted
- Date: 2026-08-18
- Related: `docs/PLAN-opbox-boltrig-merge-2026-08-17.md` (§2 point 010, §5 push-back 010)

## Context

The unification plan wants "Files + tiptap editor as a microservice" so
Boltrig-only deployments can include a Files tab. The two halves have wildly
different extraction costs:

- **Files browser**: `FilecloudShell` sits behind a `StorageAdapter`
  interface with exactly one implementation — a second adapter against a
  standalone backend is a contained change. But every file byte today moves
  through Opbox kernel verbs sealed into the kernel's MinIO, so a
  Boltrig-only Files tab needs its own storage backend behind a new adapter,
  not a lift of the current one.
- **tiptap editor**: documents are not a model, they are TableRow rows in a
  system table written via kernel table verbs; the editor carries ~40 custom
  extensions (DOCX round-trip, track changes, entity mentions, inline AI) and
  hundreds of `components/ui` imports. It is the expensive half by an order
  of magnitude.

The only Boltrig-only audience today is the app.boltrig.io canary.

## Decision

The plan is split: no Boltrig-only Files tab and no tiptap extraction are
scheduled. The `StorageAdapter` seam is noted as the extraction point if a
real requirement appears. Revisit trigger: a paying Boltrig-only deployment
that needs files. Until then the combined product uses Opbox's existing Files
surface, unchanged.

## Consequences

- The merge scope shrinks by its single most expensive frontend item.
- No document-format parity regime (DOCX round-trip, track changes) has to be
  duplicated or cross-tested.
- If the trigger fires, the Files half is bounded work; the editor half
  should still be resisted on these numbers.

## Correction (2026-08-22)

The Context above says documents are "written via kernel table verbs". Verified
against the opbox kernel: the SoR write goes through the kernel `tables.*`
(plural) verb family in `verbs/table_ext.rs`, reached from the frontend's
`src/lib/tables/table-kernel-writes.ts`. The kernel's `table.*`/`row.*`/`cell.*`
verbs are a different, fact-per-cell data plane the frontend never reads. There
is no verb named `table.write`; that string is a capability on the `tables.*`
family. The decision itself is unchanged.
