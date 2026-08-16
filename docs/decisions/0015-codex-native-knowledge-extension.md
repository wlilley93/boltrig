# 0015 - Codex-native Boltrig Knowledge extension

- Status: accepted
- Date: 2026-07-21
- Extends: 0012's Codex execution ownership
- Supersedes: 0011's Mem0-primary deployment default
- Detailed design: `docs/proposals/codex-native-knowledge-extension.md`

## Context

Boltrig has a governed memory ledger, native pgvector memory, and optional Mem0
and Cognee projections. It does not have a canonical object vault, asset and
revision identities, stable document segments, source permissions, or a general
evidence retrieval contract. Those are required for personal documents and for
Boltrig tenants to share one durable knowledge base with Codex.

Decision 0011 made Mem0 the primary operational memory projection before this
broader document and knowledge requirement was defined. The resulting topology
still needs Boltrig to own the catalogue, provenance, permissions, evidence,
erasure, and context contract. Making an external memory product primary does
not remove that work and adds another operational dependency.

Decision 0012 already fixes the agent boundary:

```text
Boltrig controls authority and durable workflow.
Codex controls agent execution.
Source systems control their authoritative domain data and effects.
```

Knowledge must preserve that boundary. It cannot introduce another agent
runtime or give a storage product authority.

## Decision

Create Knowledge as a first-party Boltrig extension loaded through the existing
adapter, workflow, skill, and MCP mechanisms. It is not new policy in the kernel
core. All Knowledge operations cross the existing dispatcher.

Adopt two mandatory storage roles behind Boltrig-owned protocols:

1. PostgreSQL with pgvector is canonical for asset identity, revisions,
   metadata, permissions, provenance, structured claims, memory records,
   processing state, lexical search, and the default vector index.
2. ObjectVault stores immutable original bytes and large derived artefacts. It
   has a filesystem implementation for personal/local deployments and an
   S3-compatible implementation for cloud and customer-hosted deployments.

Ship Cognee as the enabled-by-default knowledge compiler while keeping it a
rebuildable projection rather than an authority:

- Cognee is bundled and enabled for knowledge compilation and relationship
  enrichment. If its model configuration is unavailable, canonical ingest stays
  healthy and its projection reports a visible degraded state.
- specialist search, vector, graph, and lake stores are added only after a
  measured scale or query requirement.

Codex consumes Knowledge through run-scoped Boltrig MCP tools and resources.
Hatchet may execute durable ingestion jobs. Bifrost may route Codex model
requests. Neither is an agent or an authority over Knowledge.

## Canonical hierarchy

```text
source occurrence or managed original
  -> immutable asset revision
  -> derived representation
  -> stable citable segment
  -> embedding/entity/claim projection
  -> governed memory
  -> Codex context and conclusion
```

Lower layers may be rebuilt or disputed. They never overwrite a higher source
layer silently.

## Consequences

- One Boltrig information model works for Mac, cloud, hybrid, and
  customer-hosted deployments.
- There is one API/MCP/permission/provenance surface without pretending one
  physical database is ideal for large bytes and transactional metadata.
- Original documents remain portable if Cognee or a vector model is replaced.
- Search begins with PostgreSQL exact, structured, full-text, and pgvector
  retrieval. More infrastructure requires benchmark evidence.
- Memory remains distinct from documents and structured facts.
- Source-system ACLs must filter retrieval candidates before ranking.
- The first implementation needs ordered migrations, object-vault contracts,
  stable citation locators, and new security/correctness invariants.
- Decision 0011 is superseded. Cognee becomes the shipped compiler; the native
  governed memory ledger remains the ordinary memory path.

## Acceptance record

Accepted with agreement on these points:

1. Codex is the only target Boltrig agent runtime.
2. Postgres/pgvector plus ObjectVault are mandatory and canonical; Cognee ships
   enabled as a rebuildable compiler, not an authority.
3. The first vertical slice is text, Markdown, and PDF for one workspace, not a
   claim of immediate support for every datatype and connector.
4. Filesystem and S3-compatible vaults implement the same digest, revision,
   traversal, erasure, and audit contract.
5. Future projections require a complete governed adapter before they may enter
   the provider catalogue; no placeholder provider is shown to users.

## 2026-08-15 amendment: retire unimplemented providers

Mem0 and Supermemory are removed from the shipped catalogue. Neither had a
complete Knowledge compile, erase, health, credential, and recovery lifecycle,
so presenting them as choices created UI without capability. Upgrades disable
old persisted rows and public reads hide them. The optional Mem0 package and
compatibility adapter are also removed.

This does not make Cognee canonical and does not make it the nightly trainer.
Postgres/pgvector plus ObjectVault remain authoritative; Cognee is a rebuildable
knowledge compiler. Nightly LoRA distillation remains a separate, optional,
disabled-by-default sidecar governed by decision 0023.

## 2026-08-15 amendment: reuse the ordinary AI connection

Cognee must not introduce a second provider-key setup. Knowledge operations
resolve the caller's normal tenant/workspace/user chat connection, ensure its
server-side Bifrost binding, and give Cognee only the exact model route plus a
scoped virtual key. Provider plaintext remains sealed in the kernel. Embeddings
run locally through bundled FastEmbed and require no credential. Per-operation
Cognee configs are request-local so concurrent tenants cannot overwrite a
process-global model or key.
