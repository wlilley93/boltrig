# 0038 - Opbox is a client of Boltrig, and what that means per component

- Status: proposed (the storage limb needs the court, see "The route")
- Date: 2026-08-19
- Related: decisions 0030-0037 (0031 on plugin shape, 0032 on infrastructure,
  0035 on presence), `docs/SPEC-capability-doctrine.md`,
  `.vjs/orders/2026-VJS-CC-BOLTRIG-CROSS-TENANT-IDENTITY-001.yaml`,
  `.vjs/orders/2026-VJS-CC-BOLTRIG-ORG-WORKSPACE-TENANCY-001.yaml`

## Context

The Principal's direction, 2026-08-17 (M4) and 2026-08-18/19: Boltrig is the
grounding repo and every server gets it. Opbox becomes a client of Boltrig,
"built on Boltrig", and the same will apply to later apps. Where Opbox is
present, Boltrig presents as **Opbox Agents**; a Boltrig URL still works and it
is the same agent and the same kernel either way. The database is shared, with
Boltrig owning identity, and there is "presumably just one kernel".

The question this decision answers is the one that was open: **which component
lives where**. Without it "one kernel" reads as "port one into the other", which
decision 0031 already refused, and the estate ends up with two of everything and
a plan that cannot say which one to delete.

Measured on 2026-08-18/19 and load-bearing below: Opbox `public` holds 387
tables and Boltrig 120, with **exactly four name collisions** (`users`,
`workspaces`, `workspace_members`, `agent_capabilities`), all name-only. The
live Opbox door publishes **443 verbs**; the Rust registry holds ~748; the
doctrine's "633" matches neither and should be re-derived. Opbox already stores
passwords in the kernel `actor` table rather than Prisma `users`, and already
mints a Boltrig account and PAT at registration.

## The disposition

**One authority plane, not one process.** "One kernel" is satisfied when exactly
one system decides identity, authority, routing and audit for an agent action.
It is not satisfied by merging two codebases, and pursuing that reading means
rewriting ~748 Rust verbs fused to their own schema, RLS and hash-chained audit,
which 0031 refused on evidence.

| Component | Owner | What is deleted | When |
|---|---|---|---|
| Identity, sessions, MFA, invites | **Boltrig** | Opbox kernel `actor` credentials; Opbox's own session issuance | Phase B |
| Orgs, workspaces, membership | **Boltrig** | Opbox `workspaces`/`workspace_members` as sources of truth (they become projections) | Phase B |
| AI settings (BYOK) | **Boltrig** | Opbox `resolve-ai-config.ts` and its tier walk | Phase B |
| Agent runtime, routines, cost, Bifrost, Hatchet | **Boltrig** | Opbox's agent worker and queue | Phase B |
| Chat | **Boltrig** runs it, **Opbox** surfaces it | Opbox `/api/ai/chat` in-Next path | Phase A tail |
| Regulated domain facts and their verbs | **Opbox kernel** | nothing | never |
| Workflow engine | **Opbox** keeps its own | nothing | never |
| Capability routing and the model-facing offer | **Boltrig** | nothing | done |

**Identity and auth.** Boltrig owns it, and half of that is already true: Opbox
passwords live in the kernel `actor` table rather than Prisma, and Opbox already
provisions a Boltrig account plus PAT at registration. There are two auth
systems today and one already calls the other. **No third auth service is
needed**; Boltrig already is one (`boltrig/identity/`: sessions, TOTP, recovery,
invites, delegation, password reset). `identity_orgs` already resolves one email
to many orgs before any tenant is bound, which is exactly the Principal's "run
two businesses from one account", so that requirement is wiring rather than
design.

**AI settings are a straight duplication and Boltrig's is the better one.**
Opbox walks user > workspace > org > env in `resolve-ai-config.ts`; Boltrig's
`ai_configs` is keyed `(tenant_id, level, scope_id, modality)` with a
`credential_ref` into a sealed store and **no plaintext key column at all**.
This is a deletion on the Opbox side, not a merge.

**The Opbox kernel stays, and stops being a kernel.** It keeps ~114 regulated
tables, per-workspace hash-chained audit under an advisory lock, RLS on 39
tables, and the verbs fused to them. It stops owning identity, the agent
surface, AI config and chat. Every agent-initiated call reaches it through
Boltrig's capability router. That is what makes Opbox unable to work without
Boltrig while leaving the regulated core where its guarantees live.

**Opbox loses its AI surface, in this order.** Agents tab first (additive, and
decision 0030 already fixes the mechanism: built on the web SDK, not an iframe
of the Worker); then AI side panels become Boltrig chats; then Spotlight's
cowork becomes an agent chat; then the in-Next `/api/ai/chat` path retires. The
first three are reversible and the last is not, so it goes last.

**The SDKs, and one of them just got less urgent.** `sdks/web` is essential: it
is how Opbox renders Agents without re-implementing a client, per 0030.
`sdks/node` remains the third-party plugin path, but **shipping mapping packs
means Opbox no longer needs SDK manifest v2 to be reachable** - a pack inside
Boltrig maps Opbox's operations with zero Opbox changes. Ladder step 5 therefore
drops from blocker to convenience.

**Storage.** One Postgres instance, one database, two schemas (`boltrig.*`,
`opbox.*`). The four collisions vanish with no renaming and each side keeps its
migration runner. This limb contradicts 0032 and needs the route below.

## The route, and why an ADR alone is not enough

0032 positively directs "share the Postgres **instance**, keep **separate
databases**", so the storage limb supersedes it. That much is an ADR.

Two binding orders constrain how, and one of them points toward sharing rather
than away from it:

- `CROSS-TENANT-IDENTITY-001` forbids "a_super_tenant_or_app_level_scoping_
  that_collapses_the_org_equals_tenant_rls_fence". A shared database is lawful
  only if tenancy stays on the **RLS fence**. That is what makes a
  non-superuser, NOBYPASSRLS Boltrig role non-negotiable rather than prudent.
- `ORG-WORKSPACE-TENANCY-001` D9 forbids "rebuilding_the_rls_tenant_fence_
  instead_of_reusing_it". **Separate databases force a rebuild; one database
  lets it be reused.**

Because the storage limb touches an order's ground, the lawful route is a
submission and a convening, not this file: "ONLY the court may make the
substitution". D10 also gates live prod cutover on explicit Principal go.

## What was done now, and what deliberately not

DONE, and shipped: the capability chain end to end. An external provider's
operations become source operations having declared nothing; a mapping pack
inside Boltrig proposes canonical bindings and is dormant until its provider is
present; a governed HITL-gated verb approves one; the MCP face and the Codex
ceiling then offer the canonical name from **one** derivation instead of two
copies; and an approval is withdrawn when the schema under it moves.

NOT done, deliberately: no storage change, no identity change, no deletion on
the Opbox side. Nothing in the table above marked Phase B has been started, and
none of it should start before the route above is walked.

## Consequences

- The estate can say, per component, which system owns it and what gets
  deleted. That was the gap: "one kernel" was being read as a merge.
- Opbox can be mapped onto canonical capabilities **without Opbox changing at
  all**, which decouples the two release trains for the whole of Phase A.
- Five privilege blockers stand between here and the storage limb, each a silent
  failure: the blanket `public` grant to `opbox_app`, the unnamespaced
  `app.workspace_id` GUC, a superuser co-tenant making RLS inert, the shared
  advisory-lock keyspace, and `runtime-schema-contract.sql` asserting a
  two-party database.
- Every cross-product test on both sides mocks the other. Nothing has ever run
  Boltrig against Opbox, so pack drift, schema drift and the bearer round trip
  are unverified between them.
