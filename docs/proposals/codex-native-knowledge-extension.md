# Codex-native Boltrig Knowledge extension

- Status: accepted architecture; Phase 1 extension slice implemented
- Date: 2026-07-21
- Runtime boundary: decision 0012, Codex is the only target agent runtime
- Decision: 0015 supersedes decision 0011's Mem0-primary deployment default
- Accepted amendment: Cognee ships enabled; other projections are one-click add-ons
- ADR: `docs/decisions/0015-codex-native-knowledge-extension.md`

## 1. Decision in one page

Boltrig should add Knowledge as a first-party governed extension, not as policy
inside the kernel and not as another agent framework.

The extension should present one logical knowledge service while using two
mandatory physical storage roles:

1. An object vault stores immutable original bytes and large derived artefacts.
   It has a local-filesystem implementation for personal deployments and an
   S3-compatible implementation for cloud and customer-hosted deployments.
2. PostgreSQL stores authoritative identity, catalogue, permissions,
   provenance, processing state, structured facts, memory records, lexical
   indexes, and pgvector embeddings.

Everything beyond the canonical storage pair is rebuildable. Cognee is the
shipped default projection; the other engines are optional:

- Cognee ships enabled to compile entities and relationships as an enrichment
  projection, while remaining rebuildable from Boltrig's canonical records.
- Supermemory is available as a one-click managed connector or retrieval
  projection.
- Mem0 is available as a one-click compatibility projection.
- OpenSearch, Qdrant, Neo4j, and Iceberg are scale-triggered projections, not
  day-one dependencies.
- GitHub remains authoritative for code and selected reviewed text, and is a
  source/publishing connector for the wider knowledge system.

Codex is the agent. It receives governed Knowledge tools and resources through
Boltrig MCP. Hatchet may execute durable ingestion jobs but is not an agent and
does not own knowledge state. Bifrost may route model requests made by Codex but
is not an agent. Pi, Hermes, OpenCode, Mastra, Rivet, and other agent runtimes
are outside this target architecture.

```text
Human, app, or Codex
        |
        v
Boltrig API / MCP / file experience
        |
        v
Kernel dispatcher
  identity -> schema -> grant -> approval -> rate -> idempotency
  -> credential -> execute -> output schema -> audit
        |
        v
Knowledge extension
  catalogue | ingestion | retrieval | claims | context | memory links
        |
        +--------------------------+
        |                          |
        v                          v
PostgreSQL + pgvector         Object vault
canonical control data        canonical bytes
        |
        v
Rebuildable projections
Cognee | Supermemory | OpenSearch | Qdrant | graph engine
```

There is therefore no honest single-database answer. There is one Boltrig
contract and one user experience over a small, durable storage pair.

## 2. Why this is an extension, not kernel core

Boltrig's doctrine says integrations and capabilities load as data and every
external action crosses one dispatcher. Knowledge fits that doctrine without
adding knowledge policy to `boltrig/kernel/`.

The first-party extension package should provide:

- the `knowledge` nouns and verb schemas;
- an adapter registered by manifest `module_ref`;
- repository and object-store ports;
- Postgres, local-filesystem, and S3-compatible implementations;
- extraction and indexing tasks;
- Knowledge workflows loaded as data;
- one Codex skill describing how to retrieve, cite, propose memory, and request
  confirmation;
- ordinary HTTP routes that only authenticate, stream bytes where necessary,
  and dispatch the same verbs;
- MCP tools and resources generated from the registered verb catalogue.

This follows the existing extension contract. The kernel remains the authority
and audit boundary. Knowledge code is a governed capability behind it.

Suggested package boundary:

```text
boltrig/knowledge/
  models.py                 domain records, no infrastructure imports
  ports.py                  KnowledgeRepository and ObjectVault protocols
  adapter.py                knowledge.* VerbSpec declarations and execution
  service.py                transaction and lifecycle orchestration
  retrieval.py              permission-first hybrid retrieval
  context.py                typed evidence package construction
  provenance.py             source and derivation lineage
  filesystem_vault.py       local managed-vault implementation
  s3_vault.py               optional S3-compatible implementation
  postgres_repository.py    durable catalogue and index implementation
  extraction.py             extractor protocol and representation contracts
  projections.py            rebuildable enrichment/index fanout
```

`boltrig/knowledge` must not import Codex. Codex consumes the extension through
MCP like any other governed caller. The extension must not import the kernel
dispatcher to create nested side doors.

## 3. Baseline at decision time and current status

At decision time Boltrig already had important parts of the governance layer:

- `MemoryFact`, ingestion, erasure, and projection-status records;
- scoped `memory.remember`, `memory.recall`, `memory.improve`, and
  `memory.forget` verbs behind the dispatcher;
- a native Postgres/pgvector engine;
- optional Cognee, Mem0, and projection fanout adapters;
- tenant-scoped Postgres persistence and RLS support;
- an MCP server exposing granted verbs;
- inline chat attachments capped at 256 KiB each and 1 MiB per turn;
- a Codex App Server client, execution ledger, cell boundary, and rollout work.

It did not yet have:

- a canonical object vault;
- durable logical assets and immutable revisions;
- source occurrences and connector cursors;
- representation and segment records with stable citations;
- document-level or asset-level permission predicates;
- a general lexical plus vector document search contract;
- typed context packages joining source evidence and memories;
- a rebuild ledger proving every projection can be regenerated;
- a Finder-like or cross-platform knowledge experience.

As of 2026-07-21 the Phase 1 extension implements the object-vault protocol,
filesystem and S3-compatible vaults, canonical asset/revision/source-occurrence
records, representations, stable segments, versioned embedding records,
Postgres full-text plus pgvector retrieval, typed context, governed HTTP/MCP
tools and resources, the Codex retrieval skill, the Knowledge console panel,
provider state, projection status, and reference-safe erasure. The Finder-like
desktop experience, source connectors, additional datatypes, durable projection
worker, and credential-backed Supermemory/Mem0 Knowledge adapters remain later
phases.

The existing memory surface correctly says it is an evidence shelf, not a
document database. Knowledge should add the missing document and corpus plane
rather than stretching `MemoryFact` until it becomes one.

There are also two recorded memory defaults in conflict:

- decision 0008 selected native pgvector by default with optional Cognee;
- decision 0011 later selected Mem0 as primary with Cognee secondary.

The code implements both seams, but the universal Knowledge requirement changes
the choice. Boltrig now needs a complete canonical catalogue and evidence model.
Once that exists, making an external memory product the primary recall source
adds another authority-shaped dependency without filling the object/catalogue
gap. ADR 0015 restores the native ledger and index as canonical, ships Cognee
as the enabled enrichment compiler, and demotes Mem0 and Supermemory to
governed add-on projections.

The Codex target is also not fully live yet. Decision 0012 is accepted, but the
current rollout stack remains flag-gated and defaults to legacy execution. This
proposal describes the target architecture and must not be read as a claim that
the Codex production cutover is complete.

## 4. Ownership laws

### 4.1 Source systems and original bytes are authoritative

For a managed asset, Boltrig retains the immutable original bytes. For a live
business system, Boltrig retains the authoritative external identity, source
version, observed metadata, and optionally a governed snapshot.

An AI summary never replaces a PDF. An extracted CRM fact never silently
updates the CRM. A memory never edits either.

### 4.2 Every derived layer is rebuildable

Representations, segments, embeddings, entities, relationships, summaries, and
retrieval indexes are projections. Their generating code, model, configuration,
input revision, and output digest must be recorded.

Deleting all vectors or all Cognee data must not destroy authoritative
knowledge. A replay from revisions and provenance must reconstruct them.

### 4.3 Permission filtering happens before ranking

Every exact, lexical, vector, graph, and memory candidate query must include the
tenant, workspace, principal, and asset-access predicates before the result can
be ranked or returned. Retrieving broadly and asking Codex to ignore forbidden
results is a security defect.

PostgreSQL row-level security is defence in depth. The application query still
expresses the same scope so correctness does not depend on one database setting.

### 4.4 A citation names an immutable location

A citation must resolve to an asset revision and a stable segment locator. A
current asset id alone is insufficient because the asset can later change.

The locator may be a page region, heading path, cell range, transcript interval,
message id, code symbol, record key, or source URL capture. Anonymous chunk
numbers are not durable citations.

### 4.5 Memory is governed interpretation, not truth

Memory is a versioned claim useful to an agent. It can be candidate, inferred,
confirmed, disputed, superseded, expired, or erased. It may link to evidence but
does not outrank the evidence.

Recall order should normally prefer:

1. authorised live structured data;
2. original source revisions;
3. confirmed claims;
4. confirmed memories;
5. inferred memories;
6. ungrounded semantic similarity.

### 4.6 Retrieved content is untrusted data

Documents, messages, web pages, metadata, OCR, and memories cannot change a
Codex phase's model, sandbox, approval policy, skills, grants, or instructions.
The context package labels them as evidence, not instructions.

### 4.7 One identity survives moves and re-indexing

Paths, folders, object keys, vector ids, and provider ids are locations or
projection references. They are not the identity of the human-recognisable
asset. Renaming a file does not create a new asset; changing its bytes creates a
new revision.

## 5. Canonical data model

All identifiers are Boltrig-issued, tenant-scoped, opaque identifiers. Every
mutable record carries timestamps and an audit correlation. Immutable records
are append-only.

### 5.1 Blob

One byte sequence addressed by digest:

```text
blob
  id
  tenant_id
  sha256
  byte_size
  media_type
  vault_backend
  vault_key
  provider_version_id
  encryption_key_ref
  integrity_status
  created_at
```

The object key should be tenant-namespaced and derived from the digest, for
example `tenants/org_123/blobs/sha256/4f/4fdb...e21`. The database owns the
mapping and access policy.
Object-store ACLs are not the product permission model.

### 5.2 Asset

The logical object a human recognises:

```text
asset
  id
  tenant_id
  workspace_id
  kind
  title
  current_revision_id
  owner_subject
  data_class
  lifecycle_status
  metadata_json
  created_at
  deleted_at
```

Kinds include document, image, audio, video, email thread, chat thread, web
capture, code repository, dataset, database object, decision, and generic file.

### 5.3 Revision

An immutable version:

```text
revision
  id
  asset_id
  blob_id
  source_version
  content_sha256
  authored_at
  observed_at
  ingested_at
  supersedes_revision_id
  retention_policy
```

For records that remain live in a source database, `blob_id` may be null only
when the source occurrence is authoritative and repeatably addressable. A
governed snapshot creates a blob-backed revision.

### 5.4 Source occurrence

An asset can occur in Finder, Drive, email, GitHub, S3, or another system:

```text
source_occurrence
  id
  asset_id
  connector_id
  external_id
  external_parent_id
  external_path
  external_url
  etag_or_cursor
  source_acl_snapshot
  authority_mode
  first_seen_at
  last_seen_at
```

`authority_mode` is `managed`, `source_authoritative`, or `snapshot`. This avoids
pretending that every copied business-system row is the live truth.

### 5.5 Representation

A machine-usable view derived from one immutable revision:

```text
representation
  id
  revision_id
  kind
  format
  blob_id
  generator_id
  generator_version
  model_provider
  model_name
  config_digest
  status
  provenance_id
```

Kinds include plain text, structured Markdown, layout JSON, page image, OCR,
table, transcript, speaker turns, keyframe, thumbnail, email headers,
spreadsheet cells, code AST, and database schema.

### 5.6 Segment

The smallest retrievable and independently citable unit:

```text
segment
  id
  representation_id
  parent_segment_id
  sequence
  content
  structural_path
  page_region
  time_range_ms
  cell_range
  record_key
  code_symbol
  token_count
  content_sha256
  search_vector
```

Segment boundaries follow source structure first and token budgets second.

### 5.7 Embedding

Embeddings are versioned records, never a single mutable column on an asset:

```text
embedding
  id
  subject_type
  subject_id
  model_provider
  model_name
  model_version
  dimensions
  distance_metric
  vector
  generated_at
  superseded_at
```

This permits model changes, multimodal embeddings, retrieval evaluations, and
complete rebuilds without changing the segment identity.

The current fixed `vector(256)` native memory table is suitable for its hashing
engine but is not a universal document-embedding schema. Knowledge embeddings
need a model/dimension strategy before their first migration. Options are a
small set of typed per-model tables, `halfvec` where quality permits, or a
dimension-normalised embedding model selected per deployment. Arbitrary mixed
dimensions in one ungoverned table are not acceptable.

### 5.8 Entity, claim, and evidence

Entities are identities. Claims are versioned assertions about them. Evidence
links assertions to immutable segments.

```text
entity
  id | type | canonical_name | identifiers_json

claim
  id | subject | predicate | object_json | status | confidence
  valid_from | valid_until | asserted_by | supersedes_claim_id

claim_evidence
  claim_id | revision_id | segment_id | extraction_run_id
  evidence_strength | quotation_sha256
```

A knowledge graph is a projection of these explicit records. It is not the only
copy of an opaque graph generated by an external product.

### 5.9 Memory linkage

Keep the existing memory ledger, then evolve it additively:

- make source evidence a typed link to revision/segment where available;
- add status, confidence, validity, expiry, and supersession;
- keep `source_kind` and legacy `source_ref` for compatibility;
- never require every memory to have a document source, because user-confirmed
  preferences and operational decisions can originate in conversation;
- retain erasure and per-projection status ledgers.

Knowledge assets and memories remain distinct even when they cite one another.

## 6. Storage choices

### 6.1 Object vault

Use an `ObjectVault` protocol with these minimum operations:

```text
put_verified(stream, expected_sha256, size, media_type)
open(blob_ref, byte_range?)
head(blob_ref)
delete_version(blob_ref, erasure_authority)
verify(blob_ref)
```

Implementations:

- `FilesystemObjectVault`: managed content-addressed directory, atomic rename,
  file permissions, checksum verification, and no user-controlled traversal.
- `S3ObjectVault`: S3-compatible API, explicit bucket versioning check, optional
  Object Lock policy, checksums, encryption, and short-lived scoped upload URLs.

S3 versioning is recovery protection, not the revision model. Boltrig revisions
are portable and authoritative even when a provider lacks S3 versioning.

Large uploads should use a governed two-step capability:

1. `knowledge.upload.begin` validates authority, expected size/type/digest, and
   returns a short-lived token or presigned request for exactly one staging key.
2. `knowledge.upload.commit` verifies the stored byte count and digest, creates
   the revision transactionally, and emits the processing event.

An uncommitted staging object has no asset identity and is garbage-collected
after a grace period. A client never chooses a canonical object key.

### 6.2 PostgreSQL control plane

Keep one production PostgreSQL cluster initially. Use relational columns for
identity, scope, lifecycle, and join keys; JSONB for bounded format-specific
metadata; `tsvector` for lexical search; pgvector for embeddings; and RLS as
defence in depth.

Do not put large original bytes or large extracted representations in Postgres.
Do not put every field into JSONB. Fields used for identity, access, joins,
retention, provenance, and common filters stay typed.

Use ordered Alembic migrations. The knowledge schema is too material for
boot-time `CREATE TABLE IF NOT EXISTS` alone.

### 6.3 Native retrieval first

The default search stack is:

```text
exact id/path/title lookup
  + metadata and structured filters
  + PostgreSQL full-text ranking
  + pgvector similarity
  + optional explicit relationship expansion
  -> fusion and reranking
  -> citation packaging
```

Permission predicates must be present inside each candidate query. At higher
vector scale, tenant/workspace partitioning must be measured because pgvector's
own guidance notes that approximate indexes shared across tenants can affect
recall and speed.

### 6.4 Rebuildable projections

Every projection consumes immutable, scoped events from a projection outbox and
reports `pending`, `written`, `failed`, `deleted`, or `delete_failed` using the
existing projection-status pattern.

| Product | Boltrig role | Default |
| --- | --- | --- |
| Native Postgres/pgvector | exact, lexical, structured, and configured vector retrieval | on |
| Cognee | bundled entity/relationship extraction and deep corpus enrichment | on |
| Supermemory | one-click managed connector/retrieval accelerator | off |
| Mem0 | one-click compatibility memory projection only | off |
| OpenSearch | high-scale lexical/hybrid index when measured need appears | absent |
| Qdrant | high-scale vector projection when measured need appears | absent |
| Neo4j or equivalent | complex recurring multi-hop analysis | absent |
| Parquet/Iceberg | large analytical snapshots and lake interoperability | absent |

Cognee's current documentation itself uses relational, vector, and graph stores.
That validates the separation of roles but is also why Cognee should not become
Boltrig's canonical store. Its current permissions are dataset-centred, while
Boltrig needs tenant, workspace, collection, asset, source occurrence, and
delegated-principal checks.

Supermemory is a useful hosted context product with connectors and multimodal
processing. That makes it a good optional accelerator. It does not remove the
need for Boltrig-owned revisions, source ACLs, citations, provenance, erasure,
and rebuildability.

## 7. Every data category

| Category | Canonical form | Important derived forms | Exact access path |
| --- | --- | --- | --- |
| PDF/Office/text | original revision | text, layout, tables, page images, segments | asset/revision/segment |
| Image | original image | EXIF, OCR, regions, caption, visual embedding | image region |
| Audio/video | original stream | transcript, speakers, time segments, keyframes | time interval/frame |
| Email | original MIME message | headers, body parts, thread links, attachments | message and MIME part |
| Chat | source message/event versions | thread structure, reactions, edits, summaries | message id and timestamp |
| Calendar | structured source event | recurrence expansion, people/entity links | source event id/version |
| Code/Git | Git remains authoritative | symbols, commits, PRs, dependency metadata | repository/commit/path/symbol |
| Database | live source or governed snapshot | schema, selected rows, semantic text fields | source/table/key/snapshot |
| CSV/Parquet | original or snapshot revision | typed table, statistics, selected semantic fields | row group/record key |
| Web | captured response and metadata | cleaned text, screenshot, segments | URL, capture time, revision |
| Agent work | Boltrig ledger and artefacts | summaries, decisions, evaluations | run/phase/event/artefact |

Never flatten every datatype into text. Use structured queries for exact facts,
semantic retrieval for language, and source-specific locators for evidence.

## 8. Ingestion and rebuild pipeline

The pipeline is durable, idempotent, and stateful in Boltrig:

```text
authorise capture
  -> stream, hash, and validate bytes
  -> malware/type/archive-bomb screening
  -> commit asset revision
  -> emit transactional outbox event
  -> extract representations
  -> create source-anchored segments
  -> lexical index
  -> embed
  -> optional entity and claim proposals
  -> optional projection fanout
  -> evaluate completeness and publish
```

Hatchet may execute each durable job and retry it. PostgreSQL owns the job,
revision, outbox, and projection state. A Hatchet id is correlation, not truth.

Each stage records:

- exact input revision and representation ids;
- code/extractor version;
- model/provider/version when a model was used;
- configuration digest;
- started/completed timestamps;
- output ids and digests;
- error class and retry state;
- data residency route;
- initiating principal and audit correlation.

Rebuild is a first-class operation over a selected projection and scope. It
never re-ingests originals from an unverified derived copy.

## 9. Governed verbs

The initial verb surface should stay small and composable:

| Verb | Purpose | Consequence |
| --- | --- | --- |
| `knowledge.upload.begin` | authorise one bounded byte upload | low, grant checked |
| `knowledge.upload.commit` | verify bytes and create an immutable revision | low, idempotent |
| `knowledge.asset.get` | read authorised metadata and revision list | low |
| `knowledge.asset.read` | read an authorised original or representation | low, audited |
| `knowledge.search` | permission-first exact/lexical/semantic search | low, audited |
| `knowledge.context.build` | produce a bounded typed evidence package | low, audited |
| `knowledge.claim.propose` | store a non-authoritative claim proposal | low |
| `knowledge.claim.decide` | confirm, dispute, or supersede a claim | high or role-gated |
| `knowledge.source.sync` | run one configured source synchronisation | low, idempotent |
| `knowledge.asset.export` | release bytes outside the governed boundary | high |
| `knowledge.asset.erase` | erase asset revisions and every projection | destructive, ledgered |
| `knowledge.projection.rebuild` | rebuild one projection from canonical data | control-plane high |

Connector creation, credentials, retention changes, and workspace-wide policy
belong under existing `control.*` governance, not ordinary knowledge verbs.

The HTTP API must dispatch these verbs. A bulk byte stream may use a token
minted by `upload.begin`, but final admission still requires `upload.commit`.
MCP exposes the bounded control operations, not an unbounded raw object-store
credential.

## 10. Permission model

Start with Boltrig's existing organisation and workspace identities. Add an
asset access model only where the current role/scope records are insufficient.

Effective read authority is the intersection of:

```text
authenticated principal and delegated identity
  intersect tenant
  intersect active workspace
  intersect source-system ACL mapping
  intersect collection/asset policy
  intersect data classification and residency policy
  intersect current run/phase grant
```

The retrieval SQL applies this predicate before full-text or vector ranking.
The object vault only serves a blob after the catalogue authorises the exact
revision.

Do not add OpenFGA or OPA on day one. The kernel grant model, source ACL
snapshot, typed asset policy, and Postgres RLS are sufficient for the first
implementation. Add a relationship policy service only when measured customer
permission graphs cannot be expressed or operated safely in this model.

Connector service accounts must not widen source access. Each source occurrence
retains its source ACL and mapped principals. An item visible to a connector but
not to the asking user is not a retrieval candidate.

## 11. Retrieval and the context package

`knowledge.search` should select retrieval channels by query intent rather than
always running vector search:

1. exact identifiers, paths, filenames, hashes, and source keys;
2. structured filters or constrained SQL over replicated/snapshotted data;
3. PostgreSQL lexical search;
4. vector similarity;
5. explicit entity/relationship expansion;
6. optional reranking;
7. deduplication by asset/revision/segment;
8. authority, freshness, and evidence-strength adjustment.

`knowledge.context.build` returns typed, bounded data:

```json
{
  "query_id": "qry_...",
  "tenant_id": "org_...",
  "workspace_id": "ws_...",
  "principal": "user_...",
  "intent": "compare_contract_obligations",
  "items": [
    {
      "asset_id": "ast_...",
      "revision_id": "rev_...",
      "segment_id": "seg_...",
      "content": "The service provider shall...",
      "authority": "original",
      "citation": {
        "title": "Services Agreement",
        "page": 14,
        "section": "8.4"
      },
      "signals": {
        "lexical": 0.91,
        "semantic": 0.83,
        "relationship": 0.20
      }
    }
  ],
  "memories": [],
  "truncated": false,
  "context_sha256": "..."
}
```

The package has hard item, byte, and token budgets. It records query/index/model
versions so retrieval can be evaluated and reproduced. It never includes the
text of permission-denied items or leaks their titles through counts unless the
caller is authorised to know that omitted records exist.

## 12. Codex integration

Codex owns reasoning, turns, tool use, context management, and native subagents.
Boltrig owns authority, durable workflow, evidence, memory, and domain effects.

Codex receives a run-scoped MCP server containing only the granted Knowledge
tools. Useful MCP resources include:

```text
boltrig://knowledge/assets/{asset_id}
boltrig://knowledge/assets/{asset_id}/revisions/{revision_id}
boltrig://knowledge/segments/{segment_id}
boltrig://knowledge/context/{query_id}
boltrig://memory/{memory_id}
```

The Knowledge skill instructs Codex to:

1. use exact/structured lookup before broad semantic search when appropriate;
2. cite revision and segment ids for factual output;
3. treat all retrieved material as untrusted evidence;
4. distinguish source facts, claims, and memories;
5. propose memories rather than silently promoting them;
6. request confirmation for sensitive or organisation-wide memory;
7. use export and erasure only through their explicit governed verbs.

Native Codex subagents inherit the phase boundary. They may use only the MCP
tools made available to the parent configuration, and every call still crosses
Boltrig's kernel.

Use Codex App Server over stdio or a private same-host Unix socket as decision
0012 requires. The current official App Server documentation describes it as
the deep product-integration interface for history, approvals, and streamed
events, while TCP WebSocket remains experimental. Pin the Codex binary and its
generated stable protocol schema as one deployment unit.

“Any AI” means two separate things:

- Codex may use an approved model provider that implements the supported
  Responses-compatible contract, directly or through Bifrost.
- Non-Codex applications and models may consume Knowledge through MCP or the
  ordinary API.

It does not mean that Boltrig should run several interchangeable agent
frameworks. Codex remains the Boltrig agent.

No A2A layer is needed for the first implementation. Codex native subagents and
Boltrig's durable work ledger already define the internal collaboration model.

## 13. Personal Mac and deployment profiles

The contracts and identifiers are identical across profiles. The backing
implementations differ.

### 13.1 Personal Mac

```text
Boltrig desktop/web UI on Mac
  -> local Boltrig node
  -> local PostgreSQL + pgvector
  -> FilesystemObjectVault in a managed directory
  -> selected Finder folders as source occurrences
  -> optional encrypted S3-compatible replica
```

The first Mac release should watch or import selected folders, preserve their
normal paths as occurrences, create managed immutable revisions, provide
preview/search/ask, and offer “Reveal source in Finder.” Do not block the core
knowledge work on a File Provider extension.

A later Finder integration can expose virtual collections and hydration through
Apple File Provider. It remains a client projection over the same asset ids and
must not make Finder paths canonical identities.

### 13.2 Boltrig cloud

Use managed PostgreSQL/pgvector, an S3-compatible vault with versioning,
Boltrig workers, and Hatchet durable jobs. Desktop, browser, and mobile clients
use the same API and keep only bounded caches.

### 13.3 Hybrid or regulated

Run a Knowledge node beside customer data. It performs connector access,
extraction, indexing, and authorised retrieval locally. The cloud control plane
receives policy, health, audit metadata, or an approved context package, not
unrestricted source bytes.

### 13.4 Fully customer-hosted

Deploy the same Boltrig services against customer PostgreSQL, customer object
storage, customer identity, customer keys, and customer-approved Codex/model
routes. Cognee remains rebuildable, and add-on projections remain optional.

Local-first conflict-free collaborative editing is a separate product. Immutable
files, signed documents, source-system records, and memory claims should not be
turned into CRDTs merely to claim local-first support.

## 14. Product experience

Knowledge should feel like one information workspace, not a database console.

Initial views:

- Files: familiar collections, folders/source paths, previews, revisions, and
  “Reveal source.”
- Search: filename, exact text, semantic meaning, people, project, dates, type,
  source, and classification.
- Ask: this asset, collection, project, workspace, or all accessible knowledge.
- Evidence: claims, citations, contradictions, source strength, and history.
- Memory: what Codex remembers, why, scope, confirmation, correction, expiry,
  and erasure.
- Processing: extraction/index state, failures, projection lag, and rebuild.

Folders remain useful but become one view. An asset can retain a source path and
also belong to virtual collections, projects, people, jurisdictions, lifecycles,
and access policies.

## 15. Phased implementation

### Phase 0: ratify the boundary — complete

- Accept ADR 0015 based on this proposal.
- Supersede decision 0011's Mem0-primary default.
- Preserve decision 0012's Codex-only target.
- Name Postgres/pgvector plus ObjectVault as mandatory.
- Ship Cognee enabled as a rebuildable compiler; expose Mem0, Supermemory, and
  future engines through the governed add-on catalogue.

Exit: no active architecture document gives an external memory product or a
legacy runtime ownership of Knowledge.

### Phase 1: one complete extension vertical slice - complete

Support text, Markdown, and PDF originals through one workspace:

- domain models and repository/vault protocols;
- filesystem vault and Postgres repository;
- Alembic migrations for blob, asset, revision, occurrence, representation,
  segment, embedding, job, outbox, and access records;
- upload begin/commit, asset read, search, context build, and erase verbs;
- safe text/PDF extraction adapter;
- PostgreSQL full-text plus exact vector retrieval;
- MCP tools/resources and a Codex Knowledge skill;
- minimal Files/Search/Ask UI;
- complete provenance, permission, rebuild, and erasure tests.

Exit: local mode can ingest a PDF, find it by filename/keyword/vector overlap,
deliver it to Codex through governed MCP tools/resources, return a page citation,
inspect source and embedding provenance, and erase the source and derived
projections. The production Codex App Server identity/cutover remains decision
0012 work and is not claimed complete by this extension milestone.

### Phase 2: multimodal and structured representations

- Office documents and spreadsheets;
- images and OCR;
- audio/video transcript and time citations;
- email/MIME;
- web captures;
- CSV/Parquet and constrained live database queries;
- retrieval evaluation corpus and rank-quality gates.

Exit: each supported type has an immutable original, stable locator, rebuild
test, and permission test. “Supported” cannot mean only that arbitrary bytes can
be uploaded.

### Phase 3: connectors and personal experience

- local filesystem watcher;
- GitHub;
- generic S3;
- Google Drive/Gmail/Calendar or customer-priority equivalents;
- connector cursors, source ACL mapping, deletion/edit handling;
- Mac desktop packaging and off-site backup/restore drill.

Exit: sync does not duplicate identical bytes, moves preserve asset identity,
source permissions cannot widen, and connector replay is idempotent.

### Phase 4: advanced knowledge compilation and governed memory

- entities, claims, evidence, contradiction and supersession;
- deeper Cognee entity, relationship, and corpus enrichment;
- memory status/validity/evidence evolution;
- human confirmation and correction experience;
- organisation-wide memory policy and evaluation.

Exit: deleting Cognee and rebuilding yields the same canonical claims/evidence
set, subject to explicitly versioned extraction-model differences.

### Phase 5: measured scale additions

Add a specialist projection only after a benchmark demonstrates a failing
service-level or quality requirement and proves the replacement index can be
rebuilt.

- OpenSearch for lexical/facet/highlight load;
- Qdrant for vector-dominant scale;
- graph database for recurring complex multi-hop analysis;
- Iceberg for very large analytical snapshots;
- platform file-provider integrations for virtual-drive experience.

## 16. First-slice invariants

Implementation must declare and bind invariants before advertising the feature:

1. An accepted revision's computed digest and byte count match its blob record.
2. A revision is immutable; a changed byte sequence creates a new revision.
3. No search backend receives or returns a candidate outside effective access.
4. Every context item resolves to an authorised immutable revision and segment.
5. Retrieved content cannot alter grants, skills, sandbox, model, or approvals.
6. Every derived representation records exact generator provenance.
7. Projection failure cannot roll back an accepted canonical revision.
8. Rebuild can recreate lexical/vector projections from canonical records.
9. Erasure removes or tombstones canonical data according to policy and records
   every projection deletion failure without claiming completion.
10. Connector replay and upload commit are idempotent.
11. Object keys and external paths cannot escape the configured vault root.
12. Cross-tenant deduplication never creates cross-tenant visibility or a
    shared encryption/erasure dependency.
13. Sensitive content uses only permitted extraction and embedding routes.
14. Audit logs contain ids, scopes, counts, and digests but not source content.
15. A Codex subagent cannot obtain a Knowledge tool wider than the parent phase
    grant.

Service-gated tests must cover real Postgres/pgvector and both vault backends.
The offline suite uses in-memory repositories and a temporary filesystem vault,
not a fake that skips digest, traversal, scope, or erasure rules.

## 17. What not to build now

- Do not create a separate microservice per model noun.
- Do not store originals only inside Cognee, Supermemory, Mem0, or a vector DB.
- Do not add OpenSearch, Qdrant, Neo4j, Iceberg, OpenFGA, OPA, or A2A before a
  concrete requirement needs them.
- Do not make GitHub the binary document store.
- Do not reuse inline chat attachment rows as a document vault.
- Do not expose an object-store credential to Codex.
- Do not let a connector service account widen user access.
- Do not make folders or object keys canonical identity.
- Do not call every uploaded format supported before extraction, citation,
  permission, rebuild, and erasure are proven.
- Do not wire another agent runtime. Codex is the agent.

## 18. Acceptance decision

The accepted decision is:

```text
ADOPT
  Boltrig Knowledge as a first-party governed extension
  PostgreSQL + pgvector as the canonical catalogue/index/memory baseline
  ObjectVault with filesystem and S3-compatible implementations
  Codex as the only Boltrig agent, consuming Knowledge through MCP
  Cognee bundled and enabled as non-authoritative knowledge compilation
  Supermemory and Mem0 as one-click, non-authoritative projections

DEFER
  specialist vector/search/graph/lake databases
  virtual-drive platform integrations
  A2A and alternative agent frameworks
```

This is one-size-fits-all at the correct boundary: one information model, one
authority model, one provenance model, one verb/API surface, and several
replaceable storage implementations. It is not one physical database pretending
that files, structured facts, vectors, relationships, and human browsing have
identical storage needs.

## 19. Primary references

- [Codex App Server](https://learn.chatgpt.com/docs/app-server.md)
- [Codex custom model providers](https://learn.chatgpt.com/docs/config-file/config-advanced#custom-model-providers)
- [Codex MCP](https://learn.chatgpt.com/docs/extend/mcp)
- [PostgreSQL row security](https://www.postgresql.org/docs/current/ddl-rowsecurity.html)
- [PostgreSQL JSON types](https://www.postgresql.org/docs/current/datatype-json.html)
- [PostgreSQL full-text search](https://www.postgresql.org/docs/current/textsearch.html)
- [pgvector](https://github.com/pgvector/pgvector)
- [Amazon S3 Versioning](https://docs.aws.amazon.com/AmazonS3/latest/userguide/Versioning.html)
- [Cognee storage architecture](https://docs.cognee.ai/core-concepts/architecture)
- [Cognee permissions](https://docs.cognee.ai/core-concepts/multi-user-mode/permissions-system/overview)
- [Supermemory overview](https://supermemory.ai/docs/intro)
- [Supermemory connectors](https://supermemory.ai/docs/connectors/overview)
