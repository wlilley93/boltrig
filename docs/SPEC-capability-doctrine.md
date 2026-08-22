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

**Disposition, migration 0079 (decision 0036).** "All six together" was read
literally as "widen `verb_bindings`". That conflates the two things §1
separates: a SOURCE OPERATION is executed by exactly one adapter, and only the
CAPABILITY is plural. So the plural layer became a new table and the six sites
were each settled rather than each rewritten:

1. PK `(verb_id, tenant_id)` — KEPT. Capability identity is
   `capability_bindings.binding_id`.
2. `ON CONFLICT` replace — `upsert_capability_binding` conflicts on
   `binding_id`, so a sibling binding is never overwritten. Test:
   `test_a_second_binding_coexists_rather_than_replacing`.
3. `get_binding` singular — KEPT. `list_capability_bindings` is the plural read;
   `kernel/routing.py::resolve_execution_plan` collapses it to ONE target.
4. `bind_verb_to_agent` — UNCHANGED; it re-points one source operation.
5. `ensure_activation_safe` — UNCHANGED, deliberately. Two adapters may
   implement one capability; they may not both own one verb id.
6. `_enabled_tools` — joined by `_enabled_capabilities` in the connection
   projection, because "12 verbs" stops being the honest answer here (§6).

### 11.2 A second structural blocker: one live connection per adapter

`integration_connections_one_active_adapter_idx` is
`UNIQUE (tenant_id, adapter_id) WHERE health <> 'revoked'` — one live
connection per adapter. The three-CRM worked example collides with this index
exactly as it collides with the single-binding PK. The multi-binding shard
must reshape both.

**Disposition, migration 0079.** The blocker MOVED rather than being reshaped,
which §11.3 had already decided: routing identity is `provider_connections`,
and that table deliberately carries no uniqueness on `(tenant_id, adapter_id)`.
`integration_connections` keeps its index as the CATALOGUE setup flow's own
rule. The index was not the only thing binding there anyway — the connect path
also refuses on `adapter_credential_already_bound`, so a second live credential
for one adapter is a credential-model change, not an index change. Multi-account
PROVISIONING through the catalogue UI therefore remains unavailable; see §11.9.

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

**Disposition, 2026-08-18. Both faces now paginate; the version is still not
negotiated.** The consumer follows `nextCursor` to the last page under four
bounds — a page ceiling, the ACCUMULATED SCAN cap, a cursor length bound, and a
repeat-cursor check, because a server that returns its own cursor forever is
otherwise an infinite loop inside the 5s probe timeout. The cap counts entries
SCANNED rather than accepted: a name that cannot publish is skipped, so counting
survivors let a server paginate forever with the running total stuck at zero.
The whole walk runs on ONE pinned connection, because opening a client costs a
synchronous DNS resolution on the event loop — time no timeout can interrupt —
and one per page turned a bounded probe into a bounded freeze.

A *falsy* `nextCursor` (absent, null, `""`, `false`, `0`) is the last page: the
pre-pagination code ignored the key entirely and `""` is a common end-of-list
convention, so refusing it would turn discovery of a good single-page server
into a content-free failure. A *truthy but unusable* cursor is a protocol
violation, since reading a real cursor as "no more pages" is the original defect
wearing a loop.

Boltrig's own face accepts `params.cursor` and emits `nextCursor`, paging OVER
`offer_payload` rather than replacing it, so no page-size choice drops a row.
That matters because [2026] VJS-CC-VJS 10 D4 reserves the choice of a truncation
SIZE as a policy question, and a dropping budget is still passed to
`compute_tool_offer` and nowhere else. The default page size is above every
measured surface (293 committed verb rows, 633 for the widest consumed server),
so no client alive sees a different answer today. An absent or empty cursor is
the first page; anything else unresolvable is JSON-RPC `-32602`, because an
empty success page is indistinguishable from "this server has no tools" and an
agent reports that as nothing at all.

**The membership guarantee is exact only for a STABLE offer.** The offer is
recomputed from live store state per page and the rank depends on each verb's
consequence and grant specificity, so a row that re-ranks ahead of the cursor's
anchor between two of a client's requests is delivered on neither page.
Registering an adapter or re-probing a consumed server mid-pagination is enough.
The name-anchored cursor bounds that failure to rows that MOVED; an index cursor
would lose a row whenever the offer merely shrank.

What is NOT closed:
- the protocol version is still a fixed reply on the server face (2024-11-05)
  while the consumer transport pins 2025-06-18;
- `capabilities.tools.listChanged` is still `false` with no notification
  channel, so a mechanism that GROWS a run's tool table has no way to say so —
  a live constraint on §7.E rather than a detail (see §11.10);
- ~~the MCP transport has no response-byte bound~~ — CLOSED 2026-08-18. It now
  reads through the same `bounded_http_response` every other outbound adapter
  uses: streamed, `Accept-Encoding: identity` forced, a declared over-length
  refused before a chunk moves, and a server that ignores the identity request
  refused rather than decompressed. Reusing that helper rather than writing a
  second ceiling was the point — two implementations of one safety bound is how
  the weaker one survives.

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
  envelopes; the manifest v2 is an extension, not a rewrite.

  **Started 2026-08-18: `implements` is live end to end.** A `VerbDef` may
  declare the canonical capability it implements; the SDK emits it on the wire,
  `mcp_tool_policy.implements_hint` validates it as untrusted third-party text
  (verb charset, bounded, and a PINNED claim is refused rather than
  reinterpreted — a version this side has not agreed to must not be silently
  read as the one it has), `McpToolSnapshot` carries it, and the registry
  records a binding. That binding lands **proposed**, because the adapter is not
  first-party: it routes nothing, confers no approval reach, and is invisible to
  the connection projection until a human approves it. The approval step IS the
  control (§5), which is what makes accepting a stranger's claim on
  `matter.open` safe.

  Not yet: capability VERSION on the wire (everything is version 1 and the
  claim is unpinned by construction), and the transform, idempotency and
  provenance fields — those are step 3.

  The doc drift that block warned about is also fixed, and it was worse than
  stale. `server.ts` said the consumer mapped every consumed verb to "low" and
  told operators to re-assert "high" kernel-side; the consumer has failed CLOSED
  since 2026-08-16, so absence reads HIGH. Meanwhile the SDK sent
  `consequence: v.consequence ?? "low"`, turning "the app declared nothing" into
  a positive claim of safety on the wire and defeating that rule for every
  SDK-built server. Absence now travels as absence.

### 11.8 The 128-tool cliff

`MAX_KERNEL_TOOLS = 128` against 633 Opbox source operations: any wildcard
provider grant degrades every turn with a typed error. Per-run capability
projection plus `kernel.capabilities.search` (§7.E) is the systematic fix;
until it lands, hand-curated skill verb lists are the only workaround.

### 11.9 What migration 0079 deliberately left open

The multi-binding shard landed the data model, the deterministic resolver and
capability-addressed dispatch. Four things it did NOT do, each with the step
that owns it:

- **Fan-out reads.** Two eligible bindings for a read refuse with
  `route_required` instead of merging. Merging needs canonical output
  transforms and opaque record refs — step 3. The refusal is the honest
  interim answer, and `test_a_read_is_ambiguous_too_until_fan_out_exists` is
  the marker that must change when step 3 lands.
- **Canonical transforms.** With no input/output mapping, a capability's
  contract IS the contract of the binding selected, and dispatch validates
  against the source operation's own schema. Two bindings with different
  schemas under one capability is therefore a real hazard until step 3;
  `source_schema_digest` is recorded on both records so the divergence is at
  least detectable.
- **An explicit destination in the request.** The doctrine's top precedence
  level has no channel yet, because route information must not travel in the
  business arguments (§7.B). Precedence today starts at the workspace policy.
  When the channel lands it goes ABOVE that, and nothing else moves.
- **Multi-account provisioning.** A tenant can hold many
  `provider_connections`, but the catalogue setup flow still creates only one
  live connection per adapter (§11.2). Three live HubSpots are expressible in
  routing and not yet creatable through the UI.

Two mechanisms now describe bindings: `verb_bindings` (which adapter executes a
source operation) and `capability_bindings` (which operations implement a
capability). That is a layering, not a duplication, but it is a real cost until
every model-facing name is a capability. Decision 0036 records why.

### 11.10 §7.E does not fit the runtime it would have to run in [verified 2026-08-18]

Six parallel readers over the MCP face, the tool ceiling, the consumer, the chat
surface, grants and prior art established that §7.E — "project only relevant
capabilities into each run", with `kernel.capabilities.search` able to "add the
relevant capability to the current worker's tool table" — cannot be built as
written. Three independent mechanisms refuse it, each confirmed against code:

1. **The tool set is frozen at admission.** `CodexPhaseAdmission.kernel_tools`
   is fixed before the turn and the proxy's `allowed_tools` is a frozenset, so
   nothing can grow a live run's tool table. A search verb that returns a
   capability the model then cannot call is worse than no search verb.
2. **Projecting at the MCP face fixes nothing.** `validated_kernel_tool_names`
   is applied to a ceiling compiled independently in
   `fleet/runtime_resolver.py`, BEFORE any `tools/list` happens. The 128-tool
   cliff lives in that compile, not in the face, so narrowing the face narrows
   what the model reads and not what the ceiling admits.
3. **A capability name cannot appear in either derivation today.** Both iterate
   `store.list_verbs()` and test `grants.permits(verb.id)`. A capability is not
   a verb row, and grants are verb-id shaped: `grant_verbs` requires the
   capability grant AND the source operation's, while every shipped skill's
   `tool_grants` enumerates exact verb ids. Renaming the offer without moving
   grants makes every projected tool uncallable; renaming one derivation and not
   the other fails the cell closed at preflight.

So the ordering §10 implies — project, then search, then grow — is not available.
Two shapes are, and choosing between them is a product decision rather than an
implementation detail:

- **Compile the projection, keep the set fixed.** Select the run's capabilities
  at ceiling-compile time from skills, role, workspace and connected systems.
  Fits the frozen-at-admission model exactly and needs no protocol change. The
  cost is that discovery cannot expand a run: a capability not chosen before the
  turn is unreachable within it.
- **Two stable tools instead of many.** Admit `kernel.capabilities.search` and a
  single canonical dispatch tool into the ceiling permanently, so the model
  discovers capabilities and invokes them without the ceiling ever changing.
  This is NOT the `mcp.call(server, tool, arguments)` escape hatch §7.E warns
  about: search returns the canonical schema and every call still traverses the
  dispatcher's grant, HITL and audit path. What it does lose is per-tool schemas
  in the tool list itself, which is a real cost to planning quality.

Either way `capabilities.tools.listChanged` is `false` and there is no
server-to-client notification channel (`POST /v1/mcp` only, no SSE), so "the
tool list changed mid-run" has no way to be said even if it could happen.

Whichever is chosen, capability-shaped grants come first: until a grant token can
name a capability, a projected capability name is a tool nobody can call.

### 11.11 The connection catalogue is readable without a grant [verified 2026-08-18]

`route_required` no longer names the tenant's connections to an ungranted
caller. The read door one module over never checked at all:
`GET /v1/integrations/connections` and `GET /v1/integrations/catalogue` are
registered with the principal dependency only — no `require_author`, no
`GrantChecker.check`, no scope filter — while the `DELETE` on the same prefix
does call `require_author`. `_connection_view` returns the connection label, the
per-account labels, `enabled_tools` and now `enabled_capabilities`. So the exact
list the routing refusal was hardened to withhold is available, by label, to any
authenticated member of the tenant.

**Disposition, 2026-08-18 — CLOSED by filtering rather than by a role gate.**
Requiring `require_author` on the read would have been consistent with the
DELETE beside it and would also have taken the Connections page away from every
ordinary member; leaving it open would have kept the asymmetry the
`route_required` fix was hardened against. Neither is the answer, because the
question the page should answer is not "what has this tenant wired up" but
"what can I use".

So the projection is narrowed and the list is filtered from what survives:

- `_permitted_tools` returns the whole tool list to an author — administering
  integrations is the job — and to anyone else only the verbs their grants
  reach.
- `_may_see` keeps a CONNECTION when something survived that narrowing, with
  one exception: an author still sees a connection whose tool list is empty,
  which is how a revoked one stays visible to the person who has to manage it.
- The CATALOGUE stays visible to everyone and only its `enabled_tools`
  narrows. Knowing that Slack is supported discloses nothing about this tenant;
  knowing which of its verbs are bound here does.

A member with no integration grants now gets an empty list. That is the true
answer rather than an outage, and the test says so explicitly so nobody later
reads it as a bug.
