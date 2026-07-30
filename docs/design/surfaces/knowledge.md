# Knowledge surface: ratified first-slice specification

Status: **ratified and implemented 2026-07-21**. Route: `#/knowledge`.
Architecture authority: decision 0015.

## 1. Mental model

Knowledge is the source library shared by a person and Codex. It owns original
bytes, immutable revisions, stable passages, source occurrences, embedding
provenance, access predicates, and citations. It does not turn a document into
memory or make Cognee authoritative.

The three task modes are fixed:

1. **Library** adds and manages canonical source documents. This is the default.
2. **Search** finds authorised passages and exposes their immutable citation.
3. **Providers** shows the bundled compiler and governed add-on catalogue.

These are in-slide tasks, not new deck rows.

## 2. The 80% path

Choose a text, Markdown, or PDF file, confirm its title, and press **Add to
Knowledge**. The original is capped, hashed, committed to ObjectVault, catalogued
in Postgres, extracted into stable passages, and then offered to Cognee. A Cognee
failure is shown on the provider and projection records but never rolls back the
canonical source.

## 3. Library contract

- The first slice accepts text, Markdown, and PDF up to 25 MiB.
- The list shows human title, filename, and passage count.
- **Original** reads through `knowledge.asset.original` and downloads the exact
  managed bytes. Object-store keys and credentials never reach the browser.
- **Erase** uses an in-frame arm and confirm. The governed verb is high
  consequence and may pause again for kernel approval.
- Deduplicated bytes remain until the last canonical revision reference is gone.
- Empty, denied, error, loading, and ready states remain distinct.

## 4. Search and citation contract

Search combines exact title matching, lexical ranking, and the active pgvector
embedding projection after tenant, workspace, and asset-scope filtering.

Every result exposes:

- asset, revision, and segment identifiers;
- title and filename;
- page, paragraph, or structural locator;
- passage content hash;
- source kind and source reference when present;
- ranking score.

The Ask handoff instructs Codex to use Knowledge and cite each material claim.
The `knowledge/retrieval` skill is read-only and labels retrieved material
`untrusted source content`.

## 5. Provider contract

| Provider | Shipped state | Authority |
|---|---|---|
| Cognee | Bundled and enabled | Rebuildable compiler only |
| Supermemory | Visible, unavailable | External projection only |
| Mem0 | Visible, unavailable | Compatibility projection only |

Cognee enable and disable actions run through high-consequence governed verbs.
The action changes provider state, not canonical storage. Supermemory and Mem0
have no credential-backed projection adapter in this build, so their controls
are disabled and the service refuses enablement. Older persisted enabled rows
are reconciled to unavailable rather than permitted to fail every compile.

## 6. Codex and MCP contract

Granted Knowledge verbs appear as MCP tools. Accessible originals also appear
as `boltrig://knowledge/assets/{asset_id}` resources. Resource listing and reading
invoke `knowledge.asset.list` and `knowledge.asset.original` through the normal
dispatcher, so they retain grant checks, workspace scope, rate limits, output
validation, and audit.

Codex is the agent runtime. Cognee, Hatchet, Bifrost, Mem0, and Supermemory are
processors or infrastructure, never agents and never policy authorities.

## 7. Current boundary

Office documents, spreadsheets, images and OCR, audio/video, email, web captures,
large structured datasets, filesystem watching, and external source connectors
belong to later phases. The provider catalogue does not claim those connections
are already installed.

## 8. Acceptance

- Library is the default and has one primary action at rest.
- Canonical commit succeeds when Cognee is unavailable.
- Search and original access filter permissions before returning a candidate.
- Every passage retains an immutable revision citation.
- Source occurrence and embedding model provenance are inspectable.
- Erasure is deliberate and reference-safe.
- Cognee is visibly bundled; add-ons are visibly non-authoritative.
- Browser, HTTP, MCP tool, and MCP resource paths reuse governed verbs.
