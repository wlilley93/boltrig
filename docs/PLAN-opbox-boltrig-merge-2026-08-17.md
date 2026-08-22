# Opbox + Boltrig unification — evaluation and migration plan

> **Repo copy 2026-08-18.** Master evaluation + migration plan for the Opbox ⇄
> Boltrig unification ("Opbox Agents"). Two decisions remain the Principal's and
> gate only Phases 5–6: (1) Hermes' fate — it is both the in-Next chat provider
> and a resellable managed offering; (2) the embedding model per product
> boundary — Boltrig's default is lexical feature-hashing into vector(256) while
> Opbox runs two disjoint pipelines (OpenAI 1536 vs Ollama), so "shared
> pgvector" shares nothing that matters until one model is chosen.
> Canonical capability spec: `docs/SPEC-capability-doctrine.md`. Ratified
> push-backs: decisions 0030–0035. Nothing in Phases 0–4 depends on the two
> open decisions.


Written 2026-08-17. This is the deliverable for "evaluate, improve, or push back on
this plan to the fullest. plan the migration", composed with the capability
doctrine supplied 2026-08-17.

Evidence base: 12 parallel code readers (opbox-frontend, opbox-kernel,
opbox-prod-infra, boltrig on beelink, live docker state on beelink +
jellytot-prod, graphon precedent) plus one doctrine-verification agent. Every
load-bearing claim below carries a file:line or live-container citation from
that pass; the raw reader reports are at
`/tmp/merge-readers/*.txt` (session temp) and the pre-verification state of
understanding at `~/handover-2026-08-17-opbox-boltrig-merge.md`. All remote
access was read-only.

---

## 0. Verdict

**The destination is right, and a surprising amount of it already exists in
production.** The two products are integrated today at every seam the plan
describes: opbox chats through boltrig under per-user PATs with the user's own
opbox grants carried on-behalf (live on the Classical Visas client); boltrig
consumes 633 opbox verbs over the opbox kernel's MCP door behind grants and
HITL (live); the boltrig console is mounted at
`classicalvisas.opbox.app/boltrig` (live); opbox's seven Automations surfaces
were retired from the rail on 2026-08-16 explicitly "because that work will be
run through boltrig"; and skills are already authored-as-files / served-from-DB
on **both** sides independently. The plan is less a greenfield programme than
a formalisation and completion of an integration already underway.

**Three mechanisms in the plan are specified wrong and must be replaced:**

1. **"Wrapping the boltrig UI as a microservice inside opbox"** cannot be an
   iframe — boltrig's nginx ships `X-Frame-Options: DENY` + CSP
   `frame-ancestors 'none'`, opbox's own CSP allows only `self` + Calendly,
   and CSS custom properties do not cross a frame boundary, so "opbox colour
   tokens" would need a token-sync contract that exists nowhere. The right
   mechanism already exists and was built for exactly this: the
   `@wlilley93/boltrig-web-sdk` BoltrigClient (2,522 lines), whose stated
   purpose is "so opbox and the Worker render identical chat/run data". Build
   the Agents tab opbox-native on the SDK + kernel `/v1`.
2. **"Port the opbox kernel verbs to ship with boltrig"** is a category error
   — the 913 verbs are const Rust registry rows fused to the kernel's own
   Postgres, RLS, audit chain and actor model; there is no extractable verb
   library, only a deployable service behind `/v/:verb` and `/mcp` doors.
   The port already happened: it's the MCP consumer adapter. The capability
   doctrine formalises this correctly — opbox ships as a first-party SDK
   plugin (manifest v2, `implements:` declarations) and becomes a Connection.
3. **"Share the same pgvector, minio etc."** is the highest-risk,
   lowest-user-value item and is scheduled first by nothing except the plan's
   wording. Today nothing is shared: pg18 vs pg16, two different hatchet-lite
   builds with zero multi-tenant configuration anywhere, bifrost
   config-in-postgres vs config-in-volume, and boltrig runs no MinIO at all.
   Consolidate last, instance-first, database-separate.

**The capability doctrine survives verification intact** — all nine of its
current-code claims confirmed against the beelink tree (single binding per
tenant+verb enforced in six places, provider-prefixed model-facing naming,
single unpaginated `tools/list`, 2024-11-05 server face, deterministic inert
OpenAPI generator, Node-SDK-as-MCP-server, Connections inventory page, fused
dispatch with no routing stage, credentials-last) — and two structural
blockers it didn't name were found (§3). Adopt it as the canonical boltrig
spec before the merge work starts.

---

## 1. What already exists, mapped to the plan

| Plan point | Already in production/code | Remaining gap |
|---|---|---|
| Pass-through AI | `/api/ai/kernel-chat` SSE proxy to boltrig `/v1/chat`; per-user PAT (`User.boltrigPat` AES-GCM → `BOLTRIG_CHAT_PATS` fallback → provisioning at `control.invitation.create`); user's clamped opbox bearer as `on_behalf_bearer` sealed per-run into boltrig's opbox adapter credential (`app/api/ai/kernel-chat/route.ts`, `src/lib/ai/boltrig-chat.ts:87-158`) | build-time flag `NEXT_PUBLIC_USE_KERNEL_CHAT`; demo has no PAT |
| Boltrig uses opbox | McpConsumerAdapter at `http://Opbox-Kernel:8088/mcp` publishing 633+ `opbox.*` verbs; `BOLTRIG_ADDONS=opbox` addon ("Boltrig ships two ways"); curated `ops/opbox` skill (~15 verbs, sole write `opbox.add_comment`); live on cv-boltrig tenant | raw provider-prefixed verbs; 128-tool cliff; no canonical layer |
| Agents UI in opbox | `classicalvisas.opbox.app/boltrig/*` → cv-boltrig-ui with `X-Forwarded-Prefix` (Caddy subpath mount); web SDK exists for an API-first face | no native tab; iframe blocked |
| Opbox loses AI | 7 Automations surfaces retired from rail 2026-08-16, routes still live; retirement register says "waiting on a migration, not on a decision to bin them" | backend (agent_task queue, poller, Agent Bridge, workflows, scheduled tasks) still live |
| Skills files→DB | opbox: repo `.md` → boot-time `syncAll()` → `WorkspaceSkill` + KB TableRow + file-shadow + fs-mirror out for agents (`src/lib/skills/sync.ts`, `fs-mirror.ts`); boltrig: `libraries/skills/*.yaml` → `load_skills_dir` upsert (`boltrig/skills/loader.py:38-50`) | bridge between them is a manual backfill script |
| Spotlight/cowork | cowork is a fullscreen AI **mode** of Spotlight (not a route); its backend already switches to boltrig under the build flag | — |
| Deployment flags | `BOLTRIG_ADDONS` (fail-closed, per-tenant); demo runs boltrig as *optional, fail-closed* (no `depends_on`, every consumer degrades) | UI flag system doesn't exist on either side |

Also already written down inside boltrig: `docs/proposals/opbox-pinned-boltrig-agent-runtime.md`
(DESIGN, unimplemented) frames the same unification as "swap the agent
runtime, keep the Opbox kernel as verb authority" — this plan and that
proposal agree on the kernel-authority point and should be reconciled into
one document.

---

## 2. Point-by-point evaluation

**001. Ship together; boltrig UI flagged off, opbox UI flagged on (reverse on
boltrig-only).** KEEP the outcome, CHANGE the mechanism. Two flag seams exist
today and both teach a lesson: `NEXT_PUBLIC_USE_KERNEL_CHAT` is a Docker
build ARG inlined into the client bundle — an unbaked image silently bypasses
boltrig and deploy tooling had to grow a pre-flight grep for it (a recorded
incident shape); `BOLTRIG_ADDONS` is env, per-tenant, fail-closed on typos.
The demo already demonstrates the correct pattern: boltrig is *optional by
provisioning* — no `depends_on`, every consumer fails closed
(`demo-frontend-runtime.yml:47-51`). Make **presence = provisioning**: the
Agents tab renders when a boltrig connection is configured and healthy; the
boltrig console renders when it isn't. No new flag system, no build-time
seams, and the AI-surface equivalent is the doctrine's binding-presence rule
(zero opbox bindings → capabilities don't project).

**002. Branded "Opbox Agents".** KEEP. In the opbox-native tab the branding is
trivial (it's opbox UI). Rebranding the boltrig console itself is NOT config —
title/meta/BrandMark/desktop label/marketing copy/a custom font are hardcoded
across the bundle (`apps/worker/index.html`, `BrandMark.tsx`,
`settingsSections.ts:51-137`) — but in combined mode clients never see the
console, so defer that work until a boltrig-only deployment actually wants
white-labelling.

**003. Agents tab wrapping the boltrig UI as a microservice, opbox colour
tokens.** CHANGE FUNDAMENTALLY. Iframe is blocked from both directions
(boltrig nginx `X-Frame-Options: DENY` + `frame-ancestors 'none'`,
`apps/worker/nginx.conf:17-19`; opbox CSP `frame-src 'self'` + Calendly only,
`src/middleware/security-headers.ts:65-74`) and theming across a frame
boundary has no mechanism (CSS vars don't inherit into iframes; the only
injection path, `applyCustomTokens`, is visit-scoped to the appearance
page). Build the tab opbox-native on `sdks/web` + kernel `/v1` (chat SSE,
runs, work items, routines, budgets, artifacts — the SDK covers the console
surface). Opbox components consume opbox CSS custom properties for free.
The existing subpath mount stays as the zero-build fallback for admin access.
This is also cheaper to keep honest: two clients, one kernel, no sync bugs
between skins.

**004. Familiar only.** KEEP, knowing it's a code change not a flag:
`validate_public_product.py` hard-requires exactly `[FAMILIAR, JARVIS,
ULTRON]`, `characters.ts` statically registers all three, and jarvis is in
the `ROUTINE_COMPANIONS` frozenset — all three must change together. The
costs are low: emotion's only consumers are jarvis/ultron (familiar declares
no phenotype; the relay is off in prod containers anyway), the WebGL2 body
has a CSS-badge fallback for business browsers, and familiar runs voice-less
by design. One verification before promising voice: familiar's only voice id
is `vera` and whether it exists inside the deployed `pocket-voice:1.3` image
is unverified — a missing id is a silent per-call 404. Note the deployed
v0.4.31 images predate the bundle refactor entirely, so this rides the next
release train regardless.

**005. Share one pgvector, one MinIO, "etc.".** RESCOPE AND RESEQUENCE (see
push-back 003 in §5 and Phase 5). The honest version: share the *instance*,
keep separate *databases*; adopt opbox's MinIO only if boltrig grows object
needs (it has none today — filesystem vault + postgres blobs + optional
S3-compatible code); defer hatchet and bifrost until sharing is proven. And
note the trap: "shared pgvector" is not semantic RAG today — boltrig's
default embedder is lexical feature-hashing into `vector(256)`, opbox has two
disjoint pipelines (OpenAI 1536 frontend vs Ollama kernel). Sharing the
extension shares nothing that matters until a single embedding model is
chosen.

**006. @-mention opbox entities in chat.** KEEP — it's the highest-value
feature of the merge and it is greenfield on both sides (zero mention
machinery anywhere: plain-textarea composer, no message-schema field, no
entity resolver, no EntityProvider). Design: composer autocomplete →
EntityProvider protocol (copy the `fleet/ports` / `knowledge/ports`
dependency-inversion pattern) → resolution through the already-published
opbox search verbs → `brref_` provenance refs in context → follow-ups route
by origin. Auth follows the pattern already live in production: the
`on_behalf_bearer` per-user clamp.

**007. Port opbox kernel verbs into boltrig, flagged off on boltrig-only.**
DROP AS STATED; REPLACE with the doctrine's shape. The verbs are `const
VERBS: &[Verb]` rows whose handlers are fused to the kernel's Postgres, RLS
GUC binding, hash-chained audit and actor/bearer model, dispatched through
one function (`registry/dispatch.rs:24-30`); tests pin registrations to court
determinations and require repo-root docs, so the crate doesn't even build
cleanly outside its tree. The integration shape that exists — opbox-kernel
deployed as a service, boltrig calling `/mcp` — IS the port. What actually
changes under the doctrine: those 633 raw `opbox.*` source operations get
compiled into canonical capabilities (`matter.open`,
`corporate_entity.incorporate` — domain semantics, never `opbox.*`), opbox
declares `implements:` in a manifest v2, and "flagged off on boltrig-only"
becomes "zero bindings → not projected". One real defect to fix on the way:
the opbox verb-form mismatch already bit once (kernel door noun-first vs
frontend door verb-first silently resolved to zero tools,
`libraries/skills/ops/opbox.yaml:36-43`).

**008. Opbox loses all AI except the pass-through.** KEEP THE DIRECTION,
SCOPE THE DELETION. What must be ported or kept before anything is deleted:
(a) **spend governance lives inside the frontend AI routes** (checkBudget
pre-stream, cost tee, reseller markup into `BillingLineItem`s) — boltrig has
its own budgets ledger but org-level BYOK/reseller invoicing is opbox-side;
(b) **chat history lives in three stores** (kernel `conversation*`, legacy
`AiChatThread/Message`, boltrig conversations via `ConversationExt`) —
reconcile or lose it; (c) **transcription, passport OCR, TTS, voice
governance are business features with user data**, not agent chat — keep
them (Classical Visas processes visas with them); (d) small load-bearing AI
calls are sprinkled across non-AI surfaces (widget-configure, workflow AI
step, DOCX vision review, title-gen) with no boltrig equivalent — keep a
thin model path for them; (e) Hermes is both the in-Next chat provider and a
**resellable managed offering** — decide its fate deliberately; (f) the
agent runtime is a distributed system (kernel `agent_task` + in-process
poller + external Agent Bridge competing on leases + escalation gates) —
tasks stall if verbs move without both drainers. `metacognition/` is 663
markdown files, zero runtime — nothing to port. Sequence: delete nothing
until the parity ledger in Phase 6 says so.

**009. Skills authored as files, served from DB.** KEEP — it is already the
shape on both sides. The actual work is the bridge: opbox's fs-mirror (which
exists precisely because "per-user Hermes agents read skills from a
filesystem path, not from the Opbox DB") is a manual backfill script, and
overlay staleness (`overlayStaleSince`) must be honoured or boltrig silently
serves stale bodies. Automate the mirror (cron or post-sync hook) and stamp
versions.

**010. Files + tiptap editor as a microservice.** SPLIT THE PLAN. The Files
browser is the extraction-friendly half: `FilecloudShell` sits behind a
`StorageAdapter` interface with exactly one implementation — a second adapter
against a standalone backend is a contained change. But every file byte
today moves through opbox kernel verbs (`file.put`/`file.download`, sealed
AES-GCM into the kernel's MinIO), so a boltrig-only Files tab needs its own
storage backend behind a new adapter, not a lift of the current one. The
tiptap editor is the expensive half and should be DEFERRED: documents are
not a model, they are TableRow rows in a system table written via kernel
table verbs; the editor carries ~40 custom extensions (DOCX round-trip,
track changes, entity mentions, inline AI) and 226 `components/ui` imports.
Recommendation: no boltrig-only Files tab until a boltrig-only customer
needs one — today the only boltrig-only audience is the app.boltrig.io
canary.

**011. Opbox as the parent docking station.** KEEP THE CONCEPT, USE THE
NATIVE EQUIVALENT. There is no dock/sub-app mechanism in opbox — the real
mounting surfaces are the global right-side Inspector (380px, stack-based),
per-record RecordSidebar, the Spotlight overlay, and the module rail. "Boltrig
docks in" = one `MODULE_NAV` row + canvas layout + section-nav registration
(+ the four hand-maintained nav copies kept in sync — the code itself warns
"four copies of one rule is three chances to disagree"). Note the collision:
the new tab must replace, not coexist with, the still-live unregistered
`/automations/agents` route retired the day before this plan.

**012. All AI side panels become boltrig-themed chats.** DROP the
"boltrig-themed" half. It contradicts point 003's direction, it would require
the theming machinery that doesn't exist (boltrig has three coexisting
CSS-variable generations; branding is compiled in), and a foreign-skinned
pane inside a business product reads as a bug, not a feature. One embedded
experience, built once, opbox-styled: the same SDK chat component behind
Spotlight's AI mode, the entity AI tab, the dashboard widget, and the mobile
route — all of which exist today as mounting points.

**013. Spotlight loses cowork, replaced by agent chat.** KEEP — it is
95% done. Cowork is a fullscreen AI mode (not a route; docs say "do not
invent a /cowork route"), and its backend already switches to boltrig under
the build flag. Finish by making the Agents tab the persistent surface and
Spotlight a launcher into it, and move endpoint selection from build-time to
a server-probed runtime config so the unbaked-image failure mode dies.

---

## 3. The capability doctrine: verified, and what it changes

All nine embedded current-code claims CONFIRMED (details in
`~/handover-2026-08-17-opbox-boltrig-merge.md` §2.11–2.12). Five findings
beyond the doctrine's own text:

1. **Multi-binding is a six-place change**, not a PK edit: the
   `(verb_id, tenant_id)` PK, the `ON CONFLICT … DO UPDATE` upsert,
   `get_binding`'s singular contract, `bind_verb_to_agent`,
   `ensure_activation_safe` (ownership is exclusive at the control plane
   too), and `_enabled_tools` (counts by `target_ref == adapter_id`).
2. **A second structural blocker the doctrine didn't name**:
   `integration_connections_one_active_adapter_idx` is `UNIQUE (tenant_id,
   adapter_id) WHERE health <> 'revoked'` — one live connection per adapter.
   The three-CRM example collides here exactly as it collides with the
   single-binding PK.
3. **Name collisions are live**: `Connection` (`integration_connections`)
   and `capability` (`agent_capabilities`, `capability_attestation_sets`)
   are taken by unrelated concepts. Pick distinct table/model names
   (`provider_connections`, `capability_bindings`, `source_operations`,
   `routing_policies` are all free).
4. **Nango is greenfield** — the only repo hits are a parity test asserting
   it must not render and a decision log declining to copy it from Figma;
   the OAuth start route is a stub returning 409. Budget it as new work, not
   integration.
5. **Pagination is bidirectionally absent** — boltrig's consumer sends one
   `tools/list` (hard cap 5000) *and* boltrig's own server face returns one
   unpaginated page. The opbox kernel door also returns a single page; under
   633 verbs that's fine today, but the cursor loop should land with the
   ingestion work.

What the doctrine changes about the merge plan — now evidence-backed:

- **The verb story inverts** (confirmed: there is *no* provider-independent
  capability layer today; MCP verb ids embed the adapter id and double as
  the noun; OpenAPI verb ids are raw un-namespaced operationIds). Porting
  opbox verbs as-is would bake provider prefixes into the merged product.
- **Deployment shape becomes data**: binding presence, not code flags.
- **The 128-tool cliff makes per-run capability projection load-bearing for
  the merge, not optional**: opbox publishes 633 verbs and
  `MAX_KERNEL_TOOLS=128` — any wildcard `opbox.*` grant degrades *every*
  turn with a typed error; today the escape is a hand-curated ~15-verb
  skill. Projection + `kernel.capabilities.search` is the systematic fix.
- **Sequencing amendment (ratified)**: the doctrine's own order is
  hide-names → multi-bindings (CRM) → transforms/provenance → MCP
  ingestion → manifest v2 → Worker UI. The merge forces one improvement:
  the opbox first-party plugin is a **Level-1 `implements:` mapping** —
  easier than CRM structural matching — so dogfood opbox alongside CRM in
  step 2. The merge exercises only single-binding paths initially (one
  opbox connection per tenant); multi-binding is boltrig's own roadmap.
- **Public mapping packs vs private opbox, resolved**: the public repo holds
  third-party packs; the opbox pack ships signed inside the plugin (first-
  party trusted), so no opbox schema needs to be public.
- **The grants/HITL substrate is deep and reusable** (tenant ceilings,
  HITL with action digests, grant leases, held-call CAS replay) — the
  doctrine's dispatch-step-3 lands on real machinery, and the merge's
  per-user model (`on_behalf_bearer`) already flows through it in
  production.

---

## 4. Target architecture (combined deployment)

```
                    ┌─ opbox-frontend (Next.js) ── the product face
                    │    Agents tab (MODULE_NAV)  ── opbox-native, built on
                    │    Spotlight AI mode          boltrig-web-sdk → /v1
                    │    entity AI tab / dashboards (same SDK chat component)
                    │    Settings → Connections/Capabilities/Rules/Review
                    │               (opbox-native admin on kernel /v1)
  one box           │
  ──────────────    ├─ opbox-kernel (Rust) ────── verb authority: 913 verbs,
                    │    /v/:verb + /mcp doors; entity/matter/file SoR
                    │
                    ├─ boltrig kernel (FastAPI :8000) ─ Opbox Agents engine:
                    │    canonical capabilities, bindings, routing, dispatch,
                    │    grants/HITL, chat /v1, agent runtime, routines
                    ├─ boltrig fleet-worker (+ hatchet-worker, browser-executor)
                    ├─ worker-ui console ── admin/dev only in combined mode;
                    │                        product face in boltrig-only mode
                    │
                    ├─ ONE postgres instance (pg18): databases opbox | hatchet |
                    │    bifrost | boltrig-<tenant>  (separate DBs, one engine)
                    ├─ ONE MinIO (opbox-owned; boltrig optional adopter)
                    ├─ hatchet: one engine per side initially (see Phase 5)
                    └─ bifrost: one per side (different config stores)

  opbox ⇄ boltrig seam: opbox ships an SDK plugin (manifest v2, implements:)
  registered as a Connection; boltrig compiles source operations → canonical
  capabilities; the model sees crm.contact.search / matter.open, never
  opbox.*; per-run projection keeps tools ≤128; brref_ provenance powers
  @mentions and origin-routed follow-ups.
```

Boltrig-only deployment = the same boltrig stack with zero opbox bindings
(no plugin, no connection), the console as the face, its own postgres —
which is what it runs today.

---

## 5. Push-backs, ranked

**001. The iframe is impossible as specified** — doubly blocked (both
sides' headers/CSP), no token-crossing mechanism, and the half-built iframe
precedent in opbox (`jellytot/box-apps.ts`) has zero render-site callers.
The SDK path is not a compromise; it is strictly better (one kernel, two
first-class clients, no skin-sync work).

**002. "Port the verbs" would have ported nothing** — 913 const Rust rows
fused to one crate's schema/authz/audit; the service boundary is the only
sane seam, and it already exists. The doctrine's plugin framing is the
correct formalisation; adopt it and delete the word "port" from the plan.

**003. Shared infra is the riskiest item and the plan puts it first.**
Hatchet: different builds (v0.91.2 vs digest 30ff826b, version unrecorded),
zero multi-tenant configuration on either side, client tokens embed the
gRPC address, and prod tenants currently lack the hatchet-worker the newer
compose requires (their durable path may silently no-op — a pre-existing
defect to fix regardless). Bifrost: config in postgres vs UI-managed
volume; merging means shared global provider keys with no namespaces
configured — a cross-product blast radius. Postgres: pg16→pg18 for every
boltrig database. Do instance-level consolidation late, and only as far as
it pays.

**004. The 128-tool cliff is the merge's hardest technical constraint.**
633 opbox verbs vs `MAX_KERNEL_TOOLS=128`; wildcard grants break every
turn. Without doctrine steps 1+2+projection landing first, the combined
product ships with hand-curated verb lists as a permanent workaround.

**005. Spend governance and the BYOK/reseller model must survive the AI
deletion.** Budget checks, cost ledgers, reseller markup and managed-Hermes
invoicing live in the routes the plan deletes. Parity ledger before
deletion, per surface.

**006. Chat history lives in three stores.** Reconciliation (or an explicit
read-only legacy archive) must be a named migration step, not an
afterthought.

**007. Capacity is a live constraint.** jellytot-prod is a 3GB/2vCPU VPS
running ~40 containers including two full boltrig tenants; kernel+fleet
images are ~3.6GB each. "Always ship together" must ship a measured minimal
combined profile (target: share postgres+redis, drop hatchet-dashboard,
bifrost optional, browser-executor behind a profile) validated on the demo
box — or the density math fails on the second client.

**008. Build-time flags are a proven incident shape** (the unbaked
`NEXT_PUBLIC_USE_KERNEL_CHAT` image). Every new deployment-shape seam
should be runtime/env, fail-closed, demo-style.

**009. "Shared pgvector" ≠ semantic RAG today.** Boltrig's default embedder
is lexical feature-hashing (`vector(256)`); opbox runs two disjoint
pipelines with different models. Pick one embedding model per product
boundary or accept incomparable vectors; boltrig's fixed `vector(256)`
constrains the choice if knowledge ever shares infrastructure.

**010. Files+tiptap conflation** (see 002 §2): one thin-adapter extraction,
one non-extraction. Don't let the cheap half justify the expensive half.

**011. The theming contradiction (points 003 vs 012) resolves one way**:
opbox-native everywhere in the combined product. "The AI pane looks like
the AI" is not worth building a second theming system and a skin-sync test
regime for.

**012. Two opbox frontends exist** — the actively-developed Solid
frontispiece inside opbox-kernel (deployed nowhere) and the shipped Next.js
app. State in the plan that "opbox frontend" means the Next.js repo, or the
ambiguity will bite an implementer.

**013. Voice needs one verification before it's promised** — `vera` inside
the deployed pocket-voice image is unconfirmed; voice containers run
outside compose with no mounts and no config capture (drift risk in its
own right).

**014. Security hygiene to fold into the work** (found on the way, all
pre-existing): a live tenant DB password committed in the tracked
`boltrig-tenants/cv/compose.override.yml`; a long-lived `OPBOX_MCP_TOKEN`
in the cv kernel's env (move to per-call kernel-resolved credentials);
`jellytot-download`'s deliberate sensitivity-ACL bypass; the hermes
gateway's fixed dev credentials (not deployed, but don't ever expose it);
solo boltrig's dev-auth headers on a shared box.

---

## 6. Migration plan

Ordering rules that bind every phase (verified): boltrig rolls are
canary-first, per-stack **migrate-then-deploy back-to-back** (the migration
gate now lives inside `roll-release.sh` and migrates to the target image's
asserted head — the "skips alembic" memory is stale); opbox order is
kernel migration → frontend schema → frontend container, never `prisma db
push` on a deployed DB; builds happen on beelink (only x86_64 builder,
shared box — schedule around foreign builds); pushes relay via beelink's
`gh` / `opbox-relay.git`; lane locks govern who writes where. The pilot
tenant is **cv** — it already runs the co-deployment shape end to end.

### Phase 0 — Decisions and canonical specs (days, no code)
- Ratify: SDK-native Agents tab (no iframe); drop boltrig-theming; familiar-
  only; files-for-boltrig-only deferred; infra scope = one postgres instance
  + one MinIO per box, hatchet/bifrost deferred; Hermes fate; embedding
  model choice; opbox-RAG vs boltrig-knowledge boundary.
- Write the capability doctrine into the boltrig repo as the canonical spec
  **with a known-gaps section** (the graphon spec's one lesson: gaps lived
  only in a handover and the spec rot was invisible). Reconcile
  `docs/proposals/opbox-pinned-boltrig-agent-runtime.md` into it.
- Record this document's push-backs as ADRs in the respective repos.

### Phase 1 — Boltrig capability foundations (doctrine steps 1–2)
Pure boltrig work, ships independently, no client-visible change:
- Add `internal_source_operation_id` / `canonical_capability_id` /
  `model_display_name` / `connection_label`; stop exposing namespaced ids
  through the MCP face once a canonical mapping exists.
- The multi-binding schema: `source_operations`, `capability_bindings`,
  `routing_policies`, `provider_connections` (names chosen to dodge the
  live collisions), CanonicalVerb identity, ExecutionPlan. Change all six
  enforcement sites together (PK, upsert, `get_binding`,
  `bind_verb_to_agent`, `ensure_activation_safe`, `_enabled_tools`) **and**
  drop/reshape the one-active-adapter unique index.
- CRM domain first as the doctrine says; corporate-services vocabulary
  (`matter.open`, `corporate_entity.incorporate`, `beneficial_owner.verify`,
  `filing.prepare`) drafted in parallel.
- Gate: existing suites green; parity tests for single-binding behaviour
  unchanged; alembic head bump rides the normal 2–3/week cadence.

**Landed 2026-08-18.** Step 1 as migration 0078 (presentation columns). Step 2
as migration 0079: `provider_connections`, `source_operations`,
`capability_bindings`, `routing_policies`, the deterministic resolver
(`boltrig/kernel/routing.py`) and capability-addressed dispatch, with the CRM
domain declared by the reference adapter through the new `VerbSpec.implements`.
Two departures from the wording above, both recorded rather than quietly taken:
the six enforcement sites were DISPOSED OF individually rather than all
rewritten, because only the capability is plural and `verb_bindings` was never
the wrong table (decision 0036); and the one-active-adapter index was not
reshaped, because routing identity moved to a table that never carried it
(SPEC §11.2 disposition). What that leaves open — fan-out reads, canonical
transforms, an explicit destination channel, multi-account provisioning — is
SPEC §11.9.

### Phase 2 — Opbox as first-party plugin (doctrine steps 4–5, partial 3)
- Node SDK manifest v2: opbox-kernel's `/mcp` door declares source
  operations + `implements:` for the corporate-services canonicals, with
  transforms/consequence/idempotency/provenance fields. Import today's 633
  verbs as unmapped source operations; map the ~15 the ops skill curated
  first, then grow.
- Connection record per workspace ("Opbox — Acme workspace"); routing
  policy default = that connection; grants remain the opbox-side ceiling
  via the existing `on_behalf_bearer` flow.
- MCP consumer pagination loop (both faces eventually; opbox's single page
  is under the 5000 cap today).
- Per-run capability projection + `kernel.capabilities.search` (kills the
  128-tool cliff).
- Fix along the way: the noun-first/verb-first door mismatch; the stale
  SDK consequence comment (`sdks/node/src/server.ts:94-98`).
- Gate: cv tenant chat drives opbox canonical capabilities under the
  user's own grants, tools ≤128 without hand-curation.

### Phase 3 — Combined-product UI
- Agents tab in opbox-frontend: `MODULE_NAV` row + canvas layout + section
  nav + the four nav copies + Spotlight reachability + status-bar
  registration (the 46 design gates apply). Built on `sdks/web`; replace
  the retired `/automations/*` neighbourhood deliberately (redirect, then
  delete routes with the backend in Phase 6).
- One SDK chat component behind the existing mounting points (Spotlight AI
  mode, entity tab, dashboard widget, mobile route) — endpoint selection
  moved to runtime server config; PAT provisioning flow (UI on
  `control.invitation.create`, HELD-approval path surfaced).
- Settings → Connections/Capabilities/Rules/Review as opbox-native admin
  pages on kernel `/v1` (doctrine step 6, combined-product half).
- Boltrig console: unchanged, admin/dev role in combined mode.
- Gate: demo (boltrig-optional fail-closed) and cv both render the tab;
  design gates pass; no iframe anywhere.

### Phase 4 — Merge features
- @opbox-entities: EntityProvider protocol, composer autocomplete, message
  schema field, resolution via opbox search verbs, `brref_` provenance,
  origin-routed follow-ups (doctrine step 3 completed by this).
- Skills bridge automated (post-sync hook/cron driving the fs-mirror,
  overlay-staleness honoured, versions stamped).
- Familiar-only: `characters.ts` + validator + `ROUTINE_COMPANIONS` +
  surface tests; verify `vera` exists in the voice image or drop voice from
  the combined-product claim.
- Voice/emotion config captured in compose (the hand-run containers become
  declared services or stay deliberately out with a documented reason).

### Phase 5 — Infrastructure consolidation (per box, cv first)
- One postgres instance (pg18): migrate boltrig tenant DBs pg16→pg18
  (dump/restore per stack, stack down, back-to-back with its deploy);
  separate databases preserved; fix the deleted-config-path compose chains
  on both boxes while there.
- One MinIO: opbox-owned; boltrig adopts only if it grows object needs.
- Hatchet: pin ONE build; only then evaluate a single engine (mint both
  consumers' tokens there; multi-tenancy is unproven — test on demo with
  canary workloads before cv). Also: add the missing hatchet-worker to the
  prod tenants (pre-existing defect).
- Bifrost: keep per-side (config-store mismatch + provider-key blast
  radius); revisit only with a namespace plan.
- Embedding: one model decision per boundary; re-embed if unifying.
- Capacity: measure the minimal combined profile on demo; decide whether
  jellytot-prod can host client #2 or the fleet needs a bigger box.

### Phase 6 — Opbox AI decommission (last, ledger-gated)
- Parity ledger per surface: chat loop → SDK chat (history reconciled from
  all three stores first); agent runtime (agent_task + poller + Agent
  Bridge + escalations) → boltrig agents/routines — move BOTH drainers or
  drain first; workflows + ScheduledTasks → boltrig
  workflow_definitions/schedules; small AI calls keep a thin Bifrost path;
  transcription/OCR/TTS/voice-govern STAY as opbox product features;
  Hermes per Phase 0 decision.
- Delete in-Next chat loop, agent routes, legacy tables only as each
  ledger line closes; keep spend governance ported or wrapped throughout.
- Gate: one full release cycle on cv with the combined product, canary
  first, rollback = previous image tags + the (still-deployable) standalone
  stacks.

### Continuous
- One combined release script chaining: publish both image families →
  boltrig alembic gate per stack → boltrig compose up → opbox kernel
  migration → frontend runtime-release-migrate → frontend recreate with
  full overlay set → public-URL verification (today no script chains
  these; operator discipline holds them).
- Security hygiene items (push-back 014) folded into the touching phases.
- `addons active:` log lines remain the roll gate's mode detector.

---

## 7. What this plan deliberately does not do

- No iframe embedding, no boltrig-skin-in-opbox, no console rebrand
  plumbing.
- No tiptap extraction, no boltrig-only Files tab (deferred pending a real
  user).
- No hatchet/bifrost merge until pinned, proven, and namespaced.
- No deletion of opbox AI surfaces ahead of the parity ledger.
- No new generic feature-flag system — presence = provisioning everywhere.

## 8. Open questions that survived the evidence pass

1. Whether `vera` exists in the deployed pocket-voice image (needs a
   container exec; read-only passes couldn't).
2. Whether hatchet-lite v0.91.x tenant isolation actually holds two
   consumer orgs (untestable without a live experiment; Phase 5 gates on
   it).
3. Hermes' fate (product decision with revenue attached).
4. The agent-chat target behind prod Caddy's `/chat/* → agent-chat:8099`
   (no such container appears in `docker ps` — possibly dead config).
5. Where the demo frontend images are built (tags exist; build path not
   located by the readers).
