# 0031 - Opbox ships as a first-party plugin, not ported verbs

- Status: accepted
- Date: 2026-08-18
- Related: `docs/SPEC-capability-doctrine.md` (§4.4, §10), decision 0035

## Context

The unification plan's original wording: "port the Opbox kernel verbs to ship
with Boltrig, and flag them off on Boltrig-only deployments." The Opbox kernel
is a Rust service whose ~913 verbs are const registry rows fused to that
crate's own Postgres, RLS, hash-chained audit and actor model, dispatched
through a single function (opbox-kernel `registry/dispatch.rs`); tests pin
registrations to court determinations and require repo-root docs, so the crate
does not even build cleanly outside its tree. There is no extractable verb
library — only a deployable service behind `/v/:verb` and `/mcp` doors. The
port already happened: the MCP consumer adapter publishes 600+ `opbox.*`
verbs from the Opbox kernel's MCP door, live on the cv tenant.

The capability doctrine supplies the correct shape: SDK plugins publish a
manifest of source operations declaring which canonical capability each
implements (`implements:`), and providers become connections.

## Decision

Opbox integrates as a **first-party SDK plugin plus a Connection**:

- The plugin publishes a manifest v2 (`operationId`, `implements`,
  capability version, input/output schemas, transforms, consequence,
  idempotency, provenance fields).
- Today's namespaced verb ids (`opbox.list_contacts`) remain the internal
  source-operation identifiers; they stop being the AI-facing verbs.
- Canonical capabilities for Opbox's domain are named by domain semantics
  (`matter.open`, `corporate_entity.incorporate`, `beneficial_owner.verify`,
  `filing.prepare`) — never `opbox.*`.
- "Flagged off on Boltrig-only deployments" becomes **zero bindings → the
  capability is not projected** (decision 0035). No verb ships inside the
  Boltrig image.
- The public repo hosts third-party mapping packs only; the Opbox pack ships
  signed inside the plugin, so no Opbox schema becomes public.

## Consequences

- Opbox stays sovereign behind its own doors; integration is at the service
  boundary, which already exists and is exercised in production.
- The 128-tool cliff (`MAX_KERNEL_TOOLS = 128` vs 600+ Opbox source
  operations) makes per-run capability projection load-bearing for the merge
  (SPEC §11.8).
- Boltrig's canonical vocabulary gains corporate-services terms early; the
  plugin is a Level-1 `implements:` mapping, dogfooded alongside CRM in SPEC
  §10 step 2.
