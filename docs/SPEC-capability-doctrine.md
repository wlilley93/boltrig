# SPEC — The capability doctrine: Boltrig as a semantic capability operating system

- Status: accepted (canonical spec)
- Date: supplied 2026-08-17 by the Principal; codified into the repo 2026-08-18
- Verification: the nine current-code claims embedded in the doctrine were
  checked against this tree on 2026-08-17 — all confirmed; the gaps that
  verification surfaced are recorded in §11 and must be read as part of this
  spec, not as an appendix (the graphon lesson: gaps that live only in a
  handover rot invisibly)
- Related: `docs/PLAN-opbox-boltrig-merge-2026-08-17.md` (the unification plan
  this spec governs), decisions 0030–0035 (ratified push-backs),
  `docs/proposals/opbox-pinned-boltrig-agent-runtime.md` (superseded framing)

---

## 0. The central product decision

The kernel should not be a bag of endpoints and it should not be an MCP proxy
with nicer permissions. It should be a **semantic capability operating
system**:

- Providers supply operations.
- Plugins supply implementations.
- Boltrig supplies meaning, authority and routing.
- The user supplies connections and preferences.
- The model sees stable capabilities.

That lets HubSpot account 1, HubSpot account 2, Pipedrive and Opbox coexist
behind one verb without pretending they are the same account, without forcing
provider prefixes into the model, and without asking the user to become an API
designer.

The right model for Boltrig:

> Users should manage connections, destinations and rules — not verbs.
> Agents should see canonical business capabilities — not providers, accounts,
> MCP servers or endpoints.
> The kernel should manage the translation between the two.

Conceptually:

```
Connection
   ↓
Source operation
   ↓
Canonical capability binding
   ↓
Routing policy
   ↓
One deterministic execution plan
```

For example, the AI sees `crm.contact.search`, `crm.contact.create`,
`crm.contact.update`. Internally, Boltrig may satisfy those through
HubSpot — UK Sales, HubSpot — US Sales, Pipedrive — Partnerships, Opbox, or a
generic MCP server.

This is already consistent with Boltrig's underlying doctrine: stable nouns
and verbs, with the concrete implementation hidden behind the kernel. The
present problem is that the registry supports one VerbBinding per tenant and
verb, while MCP-discovered and SDK-published tools are exposed using
`<adapter-id>.<tool>` names. That makes each provider instance a separate
model-facing capability rather than another implementation of the same
capability.

---

## 1. Four concepts that are currently conflated

### 1.A Connection

A connection represents an authenticated instance that can actually perform
work:

- HubSpot — UK Sales
- HubSpot — US Sales
- Pipedrive — Partnerships
- Opbox — Acme workspace
- Finance MCP — Production

A connection has:

- A human-readable label.
- Provider and account metadata.
- Credential reference.
- Tenant and workspace scope.
- Health state.
- Allowed permissions.
- Source type: Nango, MCP, OpenAPI, SDK plugin or native adapter.

This is the level users should normally manage.

### 1.B Source operation

A source operation is what a provider actually exposes:

- `hubspot_uk.crm.objects.contacts.search`
- `hubspot_us.crm.objects.contacts.search`
- `pipedrive.searchPersons`
- `opbox.list_contacts`
- `custom_mcp.find_customer`

These identifiers must remain globally unique and provider-prefixed internally,
but they should not normally be presented to the model. They are
implementation details, like function symbols behind an interface.

### 1.C Canonical capability

This is the stable contract seen by the model:

- `crm.contact.search@1`
- `crm.contact.create@1`
- `crm.contact.update@1`
- `crm.company.search@1`
- `crm.deal.move_stage@1`

A canonical capability owns:

- A stable semantic name.
- A versioned input schema.
- A versioned output schema.
- Consequence classification.
- Idempotency requirements.
- Expected provenance behaviour.
- Whether multiple sources may be queried.
- Whether a single destination must be selected.

This should become the meaning of a Boltrig verb.

### 1.D Binding and route

A **binding** says: this particular source operation, through this particular
connection, implements this canonical capability.

A **route** says: under these circumstances, select this binding or
deterministic set of bindings.

That is the missing middle layer.

---

## 2. Multiple bindings must not violate the deterministic principle

Boltrig currently states that a verb resolves to a concrete adapter or agent.
Preserve that principle, but express it more precisely:

> A verb may have multiple eligible implementations, but every invocation must
> produce one deterministic execution plan.

An execution plan may contain:

- One target for a write.
- One target for a provenance-based update.
- Several targets for an authorised fan-out read.
- No target, resulting in a structured request for clarification.

The model does not choose arbitrary adapters. The kernel resolves the route
according to stored policy and invocation context.

This is not probabilistic model routing. It is normal deterministic
application routing.

---

## 3. How the three-CRM example should work

Suppose the user connects:

| Connection label | Provider | Intended purpose |
| --- | --- | --- |
| HubSpot — UK Sales | HubSpot account 1 | UK sales records |
| HubSpot — US Sales | HubSpot account 2 | US sales records |
| Pipedrive — Partnerships | Pipedrive | Partnership pipeline |

The model receives only: `crm.contact.search`, `crm.contact.get`,
`crm.contact.create`, `crm.contact.update`, `crm.contact.archive`.

### Searching

The user asks: *Find the contact details for Alice at Acme.* The model calls
`crm.contact.search` with `{"query": "Alice Acme"}`.

Boltrig's route for `crm.contact.search` may be:

```yaml
mode: fan_out
connections:
  - HubSpot — UK Sales
  - HubSpot — US Sales
  - Pipedrive — Partnerships
```

Boltrig normalises and merges the results:

```json
{
  "contacts": [
    {
      "ref": "brref_contact_7fk29",
      "name": "Alice Morgan",
      "email": "alice@acme.com",
      "company": "Acme",
      "origins": [
        { "connection_label": "HubSpot — UK Sales" }
      ]
    }
  ]
}
```

`ref` is an opaque, kernel-issued record reference. It resolves internally to:

- connection_id
- provider
- remote object type
- remote record ID
- binding version
- tenant and workspace scope

The model does not need to carry a HubSpot ID, Pipedrive ID or provider
prefix.

### Updating

The user then says: *Change her job title to General Counsel.* The model calls
with `{"ref": "brref_contact_7fk29", "patch": {"job_title": "General
Counsel"}}`. The reference provides provenance, so Boltrig routes the update
back to HubSpot — UK Sales automatically.

**This should be the default rule: updates follow the record's origin.**

### Creating

There is no existing record provenance, so Boltrig uses this precedence:

1. An explicit destination in the user's request.
2. The active workspace's routing rule.
3. A tenant-level default for `crm.contact.create`.
4. The only eligible healthy connection, where exactly one exists.
5. Otherwise, return `route_required` and ask the user to choose.

For example: *for the Sales UK workspace: `crm.contact.create` → HubSpot — UK
Sales*. The agent can therefore act without asking every time.

### Deleting or archiving

Destructive operations should never fan out and should not silently fall back
to another CRM. The route must come from:

- Record provenance.
- An explicit destination.
- An approved deterministic rule.

The confirmation should say: *Archive Alice Morgan in HubSpot — UK Sales?* —
the provider is hidden from tool naming but visible where it matters for user
trust.

---

## 4. Build a capability compiler, not an endpoint browser

Boltrig needs an ingestion process that converts raw operations into canonical
capability bindings:

```
discover → normalise → classify → match → validate → publish → monitor
```

### 4.1 Discover source operations automatically

**Generic MCP.** Boltrig already calls `tools/list`, captures schemas and
produces a tool snapshot. At present it turns each result into
`<adapter-id>.<tool-name>`. That discovery mechanism is correct; only the
publication model needs changing. The updated MCP ingestion should:

1. Initialise and negotiate protocol capabilities.
2. Follow all pages of `tools/list`.
3. Save name, title, description, input schema, output schema and annotations.
4. Compute a stable schema digest.
5. Store these as SourceOperation records.
6. Compile them into canonical capability candidates.
7. Publish only approved canonical capabilities.

The latest MCP specification (dated 28 July 2026) supports paginated and
cacheable tool lists, deterministic ordering and tool-list change
notifications, so Boltrig should add cursor traversal, revision caching and
catalogue reconciliation. The specification also says tool annotations from an
untrusted server must be treated as untrusted: a server calling something
`readOnly` is evidence for classification, but not sufficient authority to
bypass Boltrig's own consequence analysis.

Boltrig's own MCP face currently negotiates protocol version 2024-11-05 and
advertises `listChanged: false`. This is separate from the canonicalisation
work, but it is worth modernising so that a changing Boltrig capability
projection can be refreshed by compatible clients.

**OpenAPI.** Boltrig already has most of the first half of this compiler. Its
OpenAPI generator deterministically derives operations, schemas and raw verb
IDs from operationId or HTTP method and path, and keeps generated adapters
inert until reviewed. Change its output from:

```
OpenAPI operation → published verb
```

to:

```
OpenAPI operation → source operation → proposed capability binding
```

The source operation remains usable as an advanced escape hatch, but it should
not automatically become a default model-facing tool.

**Nango.** A successful Nango authorisation creates a connection for one user
and one external API. Nango handles credential storage, refresh and validity,
which makes it an excellent connection and authentication layer. Its unified
APIs are deliberately optional and code-first: the product still defines the
stable model and provider-specific translation logic.

So Nango should supply: authentication, connection lifecycle, credential
custody, provider execution, selected actions and syncs.

Boltrig should still own: canonical capability vocabulary, capability
versions, mapping approval, routing across accounts, grants, HITL, audit,
model-facing projection.

That is a strong separation of responsibilities.

**SDK plugins such as Opbox.** An SDK plugin should publish a manifest of
source operations and optionally declare which canonical capability each
implements. For example:

```json
{
  "operationId": "contacts.search",
  "title": "Search contacts",
  "implements": "crm.contact.search@1",
  "inputSchema": "providerInputSchema",
  "outputSchema": "providerOutputSchema",
  "consequence": "read",
  "idempotency": "safe",
  "inputTransform": "contactSearchV1ToOpbox",
  "outputTransform": "opboxContactToContactV1"
}
```

The current Node SDK exposes an app as an MCP server and publishes namespaced
verb IDs such as `opbox-acme.orders.list`. Keep that as the internal
source-operation identifier, but no longer treat it as the final AI-facing
verb.

Where Opbox implements an existing capability, it becomes another binding.
Where Opbox introduces a genuinely new business capability, name it by domain
semantics:

```
corporate_entity.incorporate
matter.open
beneficial_owner.verify
filing.prepare
```

rather than `opbox.incorporate` / `opbox.open_matter`. The internal
implementation can still be identified as Opbox for execution and audit.

---

## 5. How automatic capability matching should work

Do not ask the user to map every operation. Use a precedence hierarchy.

### Level 1: Explicit implementation declaration

A trusted plugin declares `implements: crm.contact.search@1`. This is the
strongest signal. For first-party or signed plugins, Boltrig can normally
accept the mapping automatically, subject to schema and policy validation.

### Level 2: Curated mapping packs

Boltrig maintains open, versioned provider mappings:

```
hubspot.search_contacts  → crm.contact.search@1
pipedrive.searchPersons  → crm.contact.search@1
salesforce.query_contacts → crm.contact.search@1
```

These should live as data in the public repository rather than kernel code. A
community contributor can add a mapping pack without altering dispatch.
(First-party packs for private products — e.g. the Opbox pack — ship signed
inside the plugin instead; see decision 0031.)

### Level 3: Structural matching

For an unknown MCP tool, Boltrig compares:

- Tool name and title.
- Description.
- Required input properties.
- Output object shape.
- Read/write annotations.
- Object vocabulary such as contact, company, deal or ticket.
- Compatible canonical schemas.

This produces a candidate, not immediate authority. Example:

```
custom_mcp.find_customer
  Candidate:    crm.contact.search@1
  Confidence:   0.91
  Reason:
    - read-only
    - accepts query/email
    - returns person records
    - output contains name and email
```

### Level 4: AI-assisted mapping

An LLM can interpret unusual operation descriptions and propose: canonical
capability, input transformation, output transformation, consequence,
potential information loss, and whether the match is genuinely equivalent.

It should not silently approve its own high-consequence mapping. Use the model
as a compiler assistant, not as the policy authority.

### Approval policy

| Source and operation | Default treatment |
| --- | --- |
| First-party signed plugin, known mapping | Bind automatically |
| Curated provider mapping | Bind automatically |
| Unknown read-only MCP tool, very high confidence | Bind but mark as newly inferred |
| Unknown write operation | Require review |
| Destructive or financially consequential operation | Require review |
| Partial semantic match | Keep as specialised capability or leave unmapped |
| Incompatible schemas | Leave quarantined |

Do not force every source operation into the common vocabulary. A misleading
common verb is worse than a clearly specialised one.

---

## 6. The user-facing UX

The current Worker UI already has a useful Connections inventory with health,
credentials, MCP servers and enabled verb counts. Keep that foundation, but
stop making "verbs" the primary user concept. The integrations area is
organised into four views.

**Connections** — *what have I connected?* Each account is a separate row
(HubSpot — UK Sales / Healthy … Research MCP / Needs review). Connection
onboarding asks for a meaningful label, with an intelligent default based on
account metadata. After connecting, show a summary like:

```
HubSpot — UK Sales connected
  54 operations discovered
  14 existing capabilities enabled
   2 specialised capabilities added
   1 write capability needs review
```

That is more comprehensible than presenting 54 verb identifiers.

**Capabilities** — *what can Boltrig do?* Grouped by business concepts
(customer records: contacts/companies/deals; conversation: email/chat/meetings;
work: tasks/tickets/projects; corporate services: entities/matters/filings). A
contact capability card shows availability and defaults ("Search: available
through 3 connections, default search all"; "Create: default HubSpot — UK
Sales"; "Update: original source"; "Archive: approval required"). The user
manages behaviour, not schemas.

**Rules** — *which system should be used when more than one can perform the
action?* Sentence-like controls that compile into deterministic routing
policies ("For UK Sales, create contacts in HubSpot — UK Sales"; "Search
contacts across every connected CRM"; "Update records in the system they came
from"; "Never write to Pipedrive without approval"; "Do not fall back to
another CRM when a write fails"). The UI offers dropdowns and toggles rather
than literally requiring natural-language rules; the sentence is the readable
summary.

**Review** — the exception inbox (a new operation with a proposed capability,
consequence, compatibility, and Approve-mapping / Keep-separate / Disable).
Review should be needed only for: new risky operations, ambiguous mappings,
breaking schema changes, removed source operations, permission expansion, and
provider behaviour that differs materially from the canonical contract.
Normal users should almost never see a schema editor — keep that under an
Advanced section.

---

## 7. The AI-facing experience

### 7.A Never make the model select provider-prefixed verbs

Do not expose `hubspot-uk.contact.create`, `hubspot-us.contact.create`,
`pipedrive.contact.create`, `opbox.contact.create`. That forces the model to
understand infrastructure, increases tool-choice errors and embeds deployment
details into plans. Expose `crm.contact.create`. The destination is an
execution concern.

### 7.B Keep route information outside the business arguments

The canonical input remains `{"name": "Charlie Green", "email":
"charlie@newco.com"}` — never `{"provider": "hubspot", "account_id": "..."}`.
Route using an invocation context (tenant, workspace, acting user, explicit
connection mentions, record provenance, routing policy, available grants). An
optional internal route envelope (`{"mode": "auto", "target_alias": "UK
Sales"}`) may exist, but it remains separate from the versioned business
contract.

### 7.C Return structured ambiguity

When Boltrig cannot select a safe destination:

```json
{
  "error": "route_required",
  "capability": "crm.contact.create@1",
  "choices": [
    { "label": "HubSpot — UK Sales", "reason": "Default CRM for UK Sales" },
    { "label": "HubSpot — US Sales", "reason": "Default CRM for US Sales" },
    { "label": "Pipedrive — Partnerships", "reason": "Partnership records" }
  ]
}
```

The agent then asks one useful question ("Should I add Charlie to UK Sales, US
Sales or Partnerships?"). Once answered, the route can be retained for the
current task and optionally saved as a rule.

### 7.D Make provenance first-class

Every normalised object returned from an external system carries an opaque
reference and human-readable origin metadata. The model uses the opaque
reference; the user sees the origin label. This enables safe follow-up
updates, correct deletions, cross-system deduplication, audit, link-back to
the original application, and conflict detection where two systems hold
different versions.

### 7.E Project only relevant capabilities into each run

Do not give every agent every canonical capability. Before a run, select a
small capability projection based on: agent role and skill, user request,
active workspace, grants, connected systems, consequence limits. An accounting
agent may see invoices and payments; a sales agent may see contacts and deals.

This follows the Agent libOS distinction that tool visibility and actual
authority are separate concerns: seeing a tool does not itself grant
permission to access the underlying resource. Boltrig preserves its own
grant, credential and HITL checks even after selecting a smaller model-facing
tool set.

For long-tail discovery, expose one retrieval tool —
`kernel.capabilities.search` — which searches canonical capabilities, not raw
endpoints, and can then add the relevant capability to the current worker's
tool table. A raw generic tool such as `mcp.call(server, tool, arguments)`
remains an administrative bootstrap or diagnostic escape hatch; it should not
be the normal model interface because it loses stable schemas, semantic
contracts, fine-grained grants and predictable planning.

---

## 8. Required kernel data-model change

The current model is effectively:

```
Verb └── one VerbBinding └── adapter or agent
```

Change it to:

```
CanonicalVerb
  ├── CapabilityBinding A
  ├── CapabilityBinding B
  └── CapabilityBinding C
RoutingPolicy └── selects an ExecutionPlan
```

A binding should have roughly:

```
binding_id
tenant_id
capability_id
capability_version
source_operation_id
connection_id
status
trust_level
priority
workspace_predicate
input_transform_ref
output_transform_ref
source_schema_digest
consequence_override
health
fallback_policy
created_from
reviewed_by
```

Additional records: `SourceOperation`, `Connection`, `CapabilityContract`,
`RoutingPolicy`, `CatalogueRevision`, `EntityProvenance`.

Most importantly, `binding_id` becomes its own identity. A binding should no
longer be uniquely identified only by tenant and verb.

### Revised dispatch flow

The current dispatcher resolves the verb and binding first, then validates,
checks grants, applies HITL, resolves credentials and executes. The new
routing layer requires separating canonical resolution from target selection.
The revised sequence:

1. Resolve the canonical capability and version.
2. Validate canonical input.
3. Check the caller's grant for that capability.
4. Resolve a deterministic execution plan.
5. Calculate effective consequence from both capability and selected binding.
6. Present HITL with the actual destination where required.
7. Transform canonical input into provider input.
8. Validate provider-specific input.
9. Apply rate and idempotency policy.
10. Resolve the selected connection's credential.
11. Execute.
12. Transform and normalise output.
13. Validate canonical output.
14. Issue provenance references.
15. Audit capability, route, binding, connection and result.

The existing security property remains intact: **credentials are resolved at
the last possible point and never escape the kernel.**

For an incremental implementation, each canonical verb could initially bind to
a special routing adapter, avoiding an immediate dispatcher rewrite. However,
first-class multiple bindings is the cleaner destination because routing,
health and account identity remain inspectable data rather than opaque
adapter logic.

---

## 9. Connector and catalogue sources

| Source | Best use in Boltrig | Main limitation |
| --- | --- | --- |
| Nango | OAuth, API keys, connection lifecycle, credentials, code-first provider actions | Does not remove the need for Boltrig's semantic capability layer |
| Merge | Pre-normalised CRM, HRIS, ATS, accounting, ticketing, file storage, knowledge base and chat domains | Narrower domain coverage and more opinionated common models |
| Pipedream Connect | Long-tail breadth and large prebuilt operation catalogue | Operations are mostly provider-shaped rather than a Boltrig-wide ontology |
| Composio | Agent-oriented toolkits, connected accounts, tool search, framework formatting | Still represents provider toolkits and connected accounts; Boltrig retains routing authority |
| Official MCP Registry | Discovering publicly published MCP servers | Metadata catalogue only; no trust, semantic equivalence or routing policy |

Use:

```
Nango          primary managed authentication
Native SDK     first-party products such as Opbox
Generic MCP    arbitrary and specialist tools
OpenAPI        bring-your-own API
Pipedream      optional long-tail fallback
Merge          optional pre-unified domain accelerator
MCP Registry   server discovery
```

All of them implement the same Boltrig `SourceConnector` interface. This
prevents the public architecture becoming dependent on one integration vendor.

---

## 10. Practical implementation order

**First: hide infrastructure names without breaking storage.** Add separate
fields for `internal_source_operation_id`, `canonical_capability_id`,
`model_display_name`, `connection_label`. Continue storing namespaced raw
operation IDs, but stop exposing them directly through Boltrig's MCP face once
a canonical mapping exists. This delivers immediate AIX improvement while
retaining backwards compatibility.
*(Landed as migration 0078 — the columns exist; population and MCP-face
suppression follow.)*

**Second: introduce multiple capability bindings.** Modify
`boltrig/models/registry.py`, `boltrig/store/schema.sql`, and the kernel
registry. Replace the single-binding assumption with a list of eligible
bindings and a deterministic route resolver. Start with one domain only — CRM
(contact, company, deal). Do not try to design a universal enterprise ontology
at once.

**Third: add canonical transforms and provenance.** Input mapping, output
mapping, opaque entity references, origin tracking, fan-out result merging.
This makes multi-account reads and follow-up writes reliable.

**Fourth: convert MCP discovery into source-operation ingestion.** Update the
MCP consumer to handle pagination, record catalogue versions and digests,
reconcile additions/removals/schema changes, consume change notifications
where available, store raw tools as source operations, run the capability
compiler, and publish only approved canonical verbs.

**Fifth: release SDK manifest v2.** Update the Node SDK so plugins can declare
`operationId`, `implements`, capability version, input/output schemas,
transforms, consequence, idempotency and provenance fields. Maintain
compatibility with current plugin verbs by importing them as unmapped source
operations.

**Sixth: evolve the Worker UI.** Turn the current Connections page into
Connections / Capabilities / Rules / Review. Replace "12 verbs" with "12
capabilities, 2 need review". Keep raw identifiers under Advanced details.

### Sequencing amendment (ratified 2026-08-18)

The unification plan forces one improvement to this order: the Opbox
first-party plugin is a **Level-1 `implements:` mapping** — easier than CRM
structural matching — so Opbox is dogfooded alongside CRM in step 2 rather
than after the whole ladder. The merge initially exercises only
single-binding paths (one Opbox connection per tenant); multi-binding remains
Boltrig's own roadmap, not a merge prerequisite.

---

## 11. Known gaps against the current code [verified 2026-08-17]

Verification of this doctrine's nine embedded current-code claims (all
confirmed) also surfaced the following. These are part of the spec: work that
contradicts a gap below is work against the spec.

### 11.1 The single-binding contract is enforced at six sites, not one

A multi-binding change must land at all six together:

1. The `verb_bindings` primary key `(verb_id, tenant_id)`
   (`boltrig/store/schema.sql`).
2. The `ON CONFLICT … DO UPDATE` upsert — a second binding silently *replaces*
   (`boltrig/store/authored_definitions_postgres.py`, `upsert_binding`).
3. `get_binding`'s singular contract (one row or None).
4. `bind_verb_to_agent` (re-points the one binding).
5. `control_safety.ensure_activation_safe` — refuses registration when a verb
   is already owned by another target; ownership is exclusive at the control
   plane too.
6. `_enabled_tools` (counts enabled verbs by `binding.target_ref ==
   adapter_id`).

Authoritative for dispatch is `boltrig/kernel/dispatch.py` reading the store
directly — neither registry file.

### 11.2 A second structural blocker: one live connection per adapter

`integration_connections_one_active_adapter_idx` is
`UNIQUE (tenant_id, adapter_id) WHERE health <> 'revoked'` — one live
connection per adapter. The three-CRM worked example collides with this index
exactly as it collides with the single-binding PK. The multi-binding shard
must reshape both.

### 11.3 Live name collisions — the doctrine's new names must dodge them

`SourceOperation`, `CapabilityBinding`, `CanonicalVerb`, `RoutingPolicy` are
free. But `integration_connections` already exists (catalogue connection
rows: health, credential_ref, accounts — not a routing connection),
`agent_capabilities` means agent runtime profiles (codex|script,
model_endpoint, cost_tier), and `capability_attestation_sets` is codex-lane
tool-ceiling attestations. Chosen names for the new tables:
`provider_connections`, `capability_bindings`, `source_operations`,
`routing_policies`. A `Connection` in this spec maps onto
`provider_connections` (new) with `integration_connections` remaining the
catalogue-facing presentation layer it is today
(`integration_connections.label` is the authoritative connection label;
`verb_bindings.connection_label` is a presentation copy).

### 11.4 There is no provider-independent capability layer at all today

For MCP-consumed servers the adapter id is embedded in the verb id *and*
doubles as the noun (one noun per consumed server); for OpenAPI adapters the
verb id is the raw operationId with no namespace at all. This is exactly the
gap `CanonicalVerb` points at — and it means porting provider verbs in as-is
would bake provider prefixes into the merged product.

### 11.5 Nango is greenfield

The only repo-wide hits are a parity test asserting Nango must NOT render and
a decision log declining to copy Nango from the Figma target. The OAuth start
route is a stub returning 409 `oauth_provider_not_configured`
(`boltrig/kernel/platform_routes/integration_setup.py`); no OAuth exchange exists. Budget Nango
as new work, not integration.

### 11.6 Pagination is bidirectionally absent

The consumer sends one `tools/list` with no cursor loop
(`boltrig/adapters/mcp_consumer.py`, hard cap `MCP_MAX_TOOL_SNAPSHOT = 5000`
— a paginating server's later pages are silently invisible), and Boltrig's
own server face returns `tools/list` in one unpaginated payload
(`boltrig/kernel/mcp.py`). Any cursor work covers both faces. The negotiated
protocol version is a fixed 2024-11-05 reply (not a negotiation).

### 11.7 What already exists and is reused, not rebuilt

- The grants/HITL substrate is deep: `tenant_permissions` ceilings,
  `hitl_requests`/`hitl_responses` with action digests and SEC-181 secure
  fields, `grant_leases` + `grant_authority_snapshots`, held-call CAS replay,
  `skills.tool_grants`; enforced at dispatch AND at HITL respond time. The
  doctrine's dispatch-step-3 grant check lands on real machinery.
- The OpenAPI generator is already deterministic and inert-until-reviewed
  (SEC-22, `adapters.activated` defaults false) — only its output target
  changes.
- Migrations are cheap: single linear alembic chain, ~2–3 schema changes per
  week. The constraint is semantics, not mechanics. `store/schema.sql` is the
  first-boot bootstrap and a migration-parity test compares the catalogues of
  both paths — every alembic revision must edit `schema.sql` in lockstep.
- The Node SDK already exposes an app as an MCP server with byte-compatible
  envelopes; the manifest v2 is an extension, not a rewrite. (Doc drift to fix
  when touching it: `sdks/node/src/server.ts` claims the consumer maps every
  consumed verb to consequence "low"; the consumer now propagates a real
  consequence hint.)

### 11.8 The 128-tool cliff

`MAX_KERNEL_TOOLS = 128` against 633 Opbox source operations: any wildcard
provider grant degrades every turn with a typed error. Per-run capability
projection plus `kernel.capabilities.search` (§7.E) is the systematic fix;
until it lands, hand-curated skill verb lists are the only workaround.
