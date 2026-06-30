# Boltrig - Requirements, Round Four

## Settings, Account & Access Management, with Errata from Confirmation

**Document type:** Requirements addendum to the Boltrig SRS (Rounds One to Three)
and the Security Hardening Specification. **Status:** build-ready. Extends, does
not replace, the prior specifications. This is the closing functional round
before the refactoring + security-refinement phase.

**Inherited conventions.** Requirement ids (`FR-AREA-NN`, `US-AREA-NN`,
`SEC-NN`), the ten architectural principles, the Round-Three cross-cutting rules
(C1 manifest-as-source-of-truth; C2 authoring writes versioned data not code; C3
RBAC-gated + audited; C4 actions pass the chokepoint; C5 scope-filtered views),
and the governance ratchet (every new guarantee invariant-bound, binding-debt 0,
no `K-*` invention) all apply unchanged. New area codes: **USR**
(users/provisioning), **HEAD** (headless/API & MCP clients), **MOB**
(mobile/responsive), **SET** (settings), **PAT** (personal access tokens). This
round also commits and details Round Three's **RTR** (router authoring) and hosts
Round Three's **ADM** (admin), **NOT** (notifications), and **PA** (personal
agents) inside the settings surface.

---

# Chapter 1 - Confirmations & Errata

Each confirmation below is stated as fact about the current build, the intended
behaviour, and the requirement that closes any gap.

## 1.1 Multi-user installations and user provisioning

**Confirmed.** One installation is one tenant serving all of an organisation's
users. Identity federates to the organisation's IdP (OIDC/SAML); the subject and
tenant come from verified token claims; roles and scopes come from the manifest's
IdP-group->role mappings. **There is no in-app invitation or self-service
onboarding flow today**, a user gains access solely by being in a mapped IdP
group, and is provisioned (a `users` row) on first authenticated login.

**Errata / new requirements.** Provisioning and lifecycle must be explicit and
surfaced:

- **US-USR-01 - IdP-driven membership (default).** A user who authenticates with
  a valid token and belongs to a mapped IdP group is provisioned just-in-time
  with the role/scope that mapping grants; an unmapped user is denied
  (fail-closed). *(Confirms current behaviour; bind it.)*
- **US-USR-02 - Admin invitation flow (new, optional per org).** An org-admin may
  invite a user by email; the invitation records an intended role/scope; the
  invitee gains access on first SSO login, which provisions them with that
  role/scope. Invitations expire, are revocable, and are audited. Invitation
  **does not** create a password or bypass the IdP, it pre-stages the role/scope
  for an SSO-authenticated identity.
- **US-USR-03 - User directory and lifecycle management.** An org-admin can view
  the user directory (identity, mapped role, scope, last seen), adjust a user's
  role/scope within the bounds the IdP mapping allows, and
  **deactivate/offboard** a user, which immediately revokes access (short token
  TTL or introspection) and triggers data handling per retention/offboarding
  rules (Round Three TEN-04). All changes are audited.
- **US-USR-04 - Group-sync transparency.** Where roles derive from IdP groups,
  the directory shows the source group for each user's role, so an admin can see
  why a user has the access they do.

## 1.2 Authoring nouns and verbs - current vs. committed

**Confirmed.** There are no noun/verb authoring endpoints in the current build.
Nouns, verbs, and bindings are created **only** by registering an adapter, a
built-in adapter named in the manifest, an AI-generated adapter from an OpenAPI
spec (review-gated), or an external MCP server via the consumer, whose
`describe()` returns `VerbSpec`s from which the registry creates the entries
(codeless, P1). They may also be defined as manifest/library data applied at
boot.

**Errata / committed requirements.** Round Three's Router authoring (Epic RTR) is
hereby committed with the explicit end-user workflow:

- **US-RTR-01 (committed) - Author a noun.** In the Router, a permitted user
  creates a noun: an id, a human description, and a JSON schema for the noun's
  entity. Saving versions it (`config_revisions`) and round-trips to
  library/manifest data (C1).
- **US-RTR-02 (committed) - Author a verb on a noun.** The user adds a verb to a
  noun: id (namespaced under the noun), input and output JSON schemas, a
  consequence level (`low`/`high`), an optional rate limit and degraded-mode
  spec. High-consequence verbs automatically engage the HITL gate.
- **US-RTR-03 (committed) - Set the binding.** The user binds the verb to an
  implementation: an existing adapter (deterministic) or an agent (reasoning).
  Switching a binding is versioned, takes effect without restart, and does not
  change the verb's schema surface or its MCP-face shape.
- **US-RTR-04 - Discoverability and grants.** A newly authored verb is
  immediately discoverable (`/v1/capabilities`, scoped to the caller, AZ-06) and
  invocable **only** by callers whose grants permit it; authoring a verb grants
  no one authority over it.

*The current adapter-registration path remains the primary, codeless way to add
whole families of verbs; Router authoring is for bespoke or domain-specific
nouns/verbs and for re-binding.*

## 1.3 Headless usage - API and MCP without the site

**Confirmed and supported.** The kernel is the product; the site is one client
over it. The `/v1/mcp` face accepts a bearer token, and all REST endpoints are
usable by any authenticated client. A user can therefore drive the fleet's
granted verbs entirely from their own client, Claude Code, Claude Desktop, a
Teams agent, Cursor, or a script, with no site.

**Errata / new requirements.** Make headless a first-class, ergonomic path:

- **US-HEAD-01 - Headless REST access.** Every operational endpoint
  (`/v1/invoke`, `/v1/capabilities`, `/v1/spawn`, `/v1/chat`, `/v1/hitl`,
  `/v1/work`, ...) is usable by an authenticated non-interactive client with the
  same authorization and audit as the site. *(Confirms current behaviour.)*
- **US-HEAD-02 - User-authenticated MCP, scoped to the user.** The MCP face MUST
  accept a user's bearer token or personal access token and scope the advertised
  tools and every call to that user's effective grants (tenant ceiling intersect
  user scope), distinct from the run-scoped sidecar token path. A user connecting
  Claude Code sees and can call only their permitted verbs, each running the full
  chokepoint.
- **US-HEAD-03 - Connection guidance surfaced in settings.** Settings provides
  the connection details a user needs to attach an external client: the MCP
  endpoint URL, how to authenticate (token), and copy-paste setup for common
  clients (e.g. a Claude Code / Teams agent MCP connection). *(Links SET / PAT
  below.)*
- **US-HEAD-04 - Parity of controls.** Headless clients are subject to identical
  grants, HITL gating, rate limits, budgets, and audit as the site; there is no
  reduced-security headless path.

## 1.4 Mobile-responsive UI

**Confirmed - partial today.** The UI sets a `width=device-width` viewport and
uses flex layout (basic fluidity) but has **no responsive breakpoints**; it is
desktop-first and does not adapt well to small screens. The shadcn/AI chat
component primitives are responsive and mobile-capable, so the path, especially
for the Chat surface, is straightforward.

**Errata / new requirements.**

- **US-MOB-01 - Responsive layout.** The site is responsive across phone, tablet,
  and desktop breakpoints; panels reflow to a single-column, navigable layout on
  small screens; no horizontal scrolling of primary content; touch targets meet
  minimum sizing.
- **US-MOB-02 - Chat as the primary mobile surface.** The Chat panel is fully
  usable on a phone, streaming responses, tool/sub-agent cards, and inline HITL
  (approval/clarification) cards render and are actionable on mobile, built on the
  responsive chat component primitives.
- **US-MOB-03 - Mobile-appropriate operation.** Approvals and Kanban are usable on
  mobile (approve/respond, view work and its trace); authoring/admin surfaces may
  be desktop-optimised but must not be broken or unreachable on mobile.
- **US-MOB-04 - Accessibility.** The UI targets WCAG 2.1 AA: keyboard
  navigability, sufficient contrast, screen-reader labelling, focus management,
  and a reduced-motion option (links SET appearance).

---

# Chapter 2 - The Settings Area

A dedicated **Settings** area, reachable from the site and backed by the kernel
API, organising per-user, per-team, and organisation configuration. It hosts
Round Three's Admin Console, notifications, and personal-agent settings rather
than duplicating them.

## 2.1 Structure, access model, and cross-cutting rules

- **SET-00 - Sectioned and RBAC-gated.** Settings is divided into sections; each
  section is visible and editable only to roles whose scope permits it (C3, C5):
  **Account, Appearance, Notifications, Developer & Connections, Personal Agent,
  Privacy & My Data, Security & Sessions** are available to every authenticated
  user for their own account; **Team/Workspace** to leads for their department;
  **Organisation & Administration** to org-admins.
- **SET-01 - Persisted, validated, audited.** Every setting persists
  (`user_settings`/config tables), is validated before save, and, where it is a
  configuration or security change, is written to the audit log with the actor.
- **SET-02 - Org config round-trips (C1).** Organisation/admin settings are an
  editing surface over the manifest; changes are versioned (`config_revisions`)
  with rollback and a manifest export, so the installation remains
  file-deployable.
- **SET-03 - Headless parity.** Every setting changeable in the UI is also
  changeable via a corresponding API endpoint with the same authorization, so
  headless users are not second-class.

## 2.2 Account & Profile

- **SET-10 - Profile.** View identity (display name, email, sourced from the IdP,
  read-only where the IdP is authoritative), set a preferred display name where
  permitted, and view mapped role/scope and the source IdP group (US-USR-04).
- **SET-11 - Locale & timezone.** Set personal locale and timezone, used for
  date/time display, scheduling, and locale-aware agent reasoning (links Round
  One i18n).

## 2.3 Appearance & Accessibility

- **SET-20 - Theme & density.** Light/dark/system theme, layout density, and
  font-size scaling.
- **SET-21 - Accessibility preferences.** Reduced-motion, high-contrast, and
  screen-reader-optimised options (links MOB-04).

## 2.4 Notifications

- **SET-30 - Notification routing (hosts Round Three NOT).** Per-user routing of
  event types (approval, escalation, work status, budget alert, error) to
  channels (in-app, email, Slack, Teams, webhook, pager); leads may set team
  defaults; the Approvals panel remains the canonical record regardless of
  channel.

## 2.5 Developer & Connections - Personal Access Tokens and headless clients

This section makes headless usage (Chapter 1.3) ergonomic and is **central**, not
optional.

- **SET-40 / PAT-01 - Issue personal access tokens.** A user can mint a personal
  access token for non-interactive clients (Claude Code, a Teams agent, scripts).
  Each token has a name, an expiry (required, with a sane maximum), and a scope
  that is a **subset of the user's own grants**, never an escalation. The secret
  is shown **once** at creation and stored only as a hash.
- **PAT-02 - Manage and revoke.** The user can list their tokens (name, scope,
  created, last used, expiry, never the secret), and revoke any token
  immediately; revocation takes effect at once. Tokens are auditable and surfaced
  in Security & Sessions.
- **SET-41 / HEAD-03 - Connection details.** Display the MCP endpoint URL and
  REST base URL, the authentication method, and copy-paste setup snippets for
  common clients (e.g. a Claude Code or Teams MCP connection), so a user can
  attach an external client in minutes.
- **PAT-03 - Token least privilege and expiry by default.** New tokens default to
  the minimum useful scope and a bounded lifetime; a token can never carry
  authority the user lacks at use-time (re-checked against current grants on every
  call), and a de-provisioned user's tokens stop working.

## 2.6 Personal Agent

- **SET-50 - Personal agent (hosts Round Three PA).** A user configures their
  personal agent (runtime, skills, enable/disable). It is isolated from fleet
  state and acts only with the owner's delegated permissions, audited under the
  owner's identity (Round Three SEC-30). Configurable from settings and via the
  headless API.

## 2.7 Privacy & My Data

- **SET-60 - My data export.** A user can export their own data (their
  conversations, work items they own, their settings) in a documented format,
  scope-filtered to themselves.
- **SET-61 - My data deletion.** A user can delete their own conversations/memory
  subject to retention and legal-hold rules; deletions are audited (links Round
  Three PRIV-04, TEN-04). Org-wide retention is set by admins (2.10).

## 2.8 Security & Sessions

- **SET-70 - Active sessions and tokens.** View active sessions/clients and
  personal access tokens; revoke any session or token; see last-used and origin
  where available.
- **SET-71 - MFA and IdP security status.** Show the user's authentication/MFA
  status as reported by the IdP and link to the IdP for changes; Boltrig does not
  store passwords or MFA secrets (IAM-11) and never presents itself as the
  authoritative authentication authority.
- **SET-72 - My activity.** A user can view an audit of their own recent activity
  (scope-filtered to themselves), reinforcing transparency.

## 2.9 Team / Workspace (leads)

- **SET-80 - Department preferences.** A lead manages department-scoped settings:
  team notification defaults (SET-30), team skill overrides (Round Three SKS /
  SKL inheritance), and department spawn/budget visibility, within the bounds set
  by org admins, versioned and audited.

## 2.10 Organisation & Administration (org-admins) - hosts Round Three Admin Console

- **SET-90 - User management & invitations.** The user directory and lifecycle
  (US-USR-02/03/04): invite, view, adjust role/scope within IdP bounds,
  deactivate/offboard, all audited.
- **SET-91 - Identity & SSO.** View/edit IdP configuration and the
  group->role/scope mappings (Round Three ADM-01), validated and versioned;
  changes to mappings are high-sensitivity and audited (Round Three IDP-02).
- **SET-92 - Departments & hierarchy.** Manage the tier-2 department structure,
  their domain skills, queue sources, and spawn budgets (round-trips to the
  manifest).
- **SET-93 - Budgets & cost.** Set tenant/department/workflow budgets and
  hard-stops; view cost rollups (Round Three OBS-01).
- **SET-94 - Model endpoints.** Manage model endpoints, the default and the
  sensitive (local) endpoint, and per-capability pinning/fallback (Round
  Two/Three).
- **SET-95 - HITL channels.** Configure the approval channel(s), escalation
  chain, approval timeout, and `blocking_verbs` (Round One/Two).
- **SET-96 - Connectors & adapters.** View connected adapters and MCP servers,
  their health and credential-reference/rotation status (never values, Round
  Three ADM-03), and launch Adapter Studio (generate/review-activate, Round Three
  ADS).
- **SET-97 - Network, privacy & retention.** Manage proxy/CA/air-gap settings,
  PII detection, data residency, retention periods, and audit-export
  configuration (Round One/Three), all versioned and audited.
- **SET-98 - Configuration history & export.** Per-section revision history with
  rollback and a full manifest export (C1, Round Three ADM-02).

---

# Chapter 3 - Consolidated Functional Requirements

The user stories above (US-USR-*, US-RTR-*, US-HEAD-*, US-MOB-*) and the settings
controls (SET-*, PAT-*) constitute this round's functional requirements.
Acceptance criteria, expressed as testable conditions, are embedded with each.
The defining acceptance threads to verify:

- **Provisioning:** an unmapped, un-invited identity is denied; a mapped or
  invited identity is provisioned with exactly its intended role/scope;
  deactivation revokes access promptly.
- **Authoring:** a noun and verb authored in the Router become discoverable
  (caller-scoped) and invocable only under grants, with versioning and
  round-trip.
- **Headless:** a personal access token scoped to a subset of the user's grants
  drives `/v1/invoke` and the MCP face; it cannot exceed the user's authority;
  revocation is immediate.
- **Mobile:** the Chat surface (streaming, tool/sub-agent cards, inline HITL) is
  fully usable on a phone; primary surfaces reflow without horizontal scrolling.
- **Settings:** every UI-changeable setting is changeable via API with identical
  authorization; org config edits version and round-trip to a manifest.

---

# Chapter 4 - Data Model Additions

```sql
-- Personal access tokens (SET-40 / PAT-*)
CREATE TABLE personal_access_tokens (
    id          TEXT PRIMARY KEY,
    tenant_id   TEXT NOT NULL,
    user_id     TEXT NOT NULL,
    name        TEXT NOT NULL,
    token_hash  TEXT NOT NULL,        -- hash only; secret shown once at creation
    scope       JSONB NOT NULL,       -- subset of the user's grants
    created_at  TIMESTAMPTZ NOT NULL,
    expires_at  TIMESTAMPTZ NOT NULL, -- required, bounded
    last_used_at TIMESTAMPTZ,
    revoked     BOOLEAN NOT NULL DEFAULT false
);
CREATE INDEX ON personal_access_tokens (tenant_id, user_id);

-- User invitations (US-USR-02)
CREATE TABLE user_invitations (
    id          TEXT PRIMARY KEY,
    tenant_id   TEXT NOT NULL,
    email       TEXT NOT NULL,
    intended_role TEXT NOT NULL,
    intended_scope JSONB NOT NULL,
    invited_by  TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL,
    expires_at  TIMESTAMPTZ NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending'  -- pending | accepted | revoked | expired
);

-- Per-user settings/preferences (SET-*)
CREATE TABLE user_settings (
    user_id     TEXT NOT NULL,
    tenant_id   TEXT NOT NULL,
    key         TEXT NOT NULL,        -- 'theme'|'locale'|'timezone'|'a11y.reduced_motion'|...
    value       JSONB NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, user_id, key)
);

-- Sessions (SET-70) - if not delegated entirely to the IdP/token store
CREATE TABLE user_sessions (
    id          TEXT PRIMARY KEY,
    tenant_id   TEXT NOT NULL,
    user_id     TEXT NOT NULL,
    client      TEXT,                 -- 'web'|'claude-code'|'teams'|...
    created_at  TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ,
    revoked     BOOLEAN NOT NULL DEFAULT false
);
```

The `users` and `role_mappings` tables already exist; `config_revisions` (Round
Three) carries org-setting versioning. Notification preferences and
personal-agent config reuse the Round Three tables (`notification_prefs`,
`personal_agents`).

---

# Chapter 5 - Interface Additions

All RBAC-gated (C3), scope-filtered (C5), and audited; each UI setting has an API
equivalent (SET-03).

```
# Settings (per-user)
GET/PUT /v1/me/settings                  account, appearance, locale, a11y
GET     /v1/me/activity                  own scope-filtered audit (SET-72)
GET     /v1/me/export                    own-data export (SET-60)
DELETE  /v1/me/conversations/{id}        own-data deletion (SET-61, retention-bound)

# Personal access tokens (PAT-*)
GET/POST /v1/me/tokens                   list / mint (secret returned once)
DELETE   /v1/me/tokens/{id}              revoke
GET      /v1/me/connections              MCP/REST connection details + snippets (HEAD-03)

# Sessions
GET/DELETE /v1/me/sessions[/{id}]        list / revoke (SET-70)

# Notifications & personal agent (host Round Three)
GET/PUT /v1/me/notifications             routing (SET-30)
GET/PUT /v1/me/agent                     personal agent (SET-50)

# User management & invitations (org-admin)
GET     /v1/admin/users                  directory (US-USR-03)
PATCH   /v1/admin/users/{id}             role/scope within IdP bounds; deactivate
GET/POST /v1/admin/invitations           list / create invitation (US-USR-02)
DELETE  /v1/admin/invitations/{id}       revoke

# Router authoring (committed RTR)
POST    /v1/nouns                        create/update a noun + schema
POST    /v1/verbs                        create/update a verb (schemas, consequence)
POST    /v1/verbs/{id}/binding           set/replace the binding

# Organisation settings - the Round Three admin routes (/v1/admin/config/*) host SET-90..98
```

The `/v1/mcp` face is updated to accept a user bearer/PAT and scope to the user's
effective grants (US-HEAD-02), in addition to the run-scoped sidecar token.

---

# Chapter 6 - Security Additions

Continues the SRS `SEC-*` sequence and cross-references the Security Hardening
Specification families.

- **SEC-34 - Personal access tokens never escalate.** A PAT's authority is the
  intersection of its declared scope and the user's *current* grants, re-checked
  on every call; it cannot exceed the user, is bounded by a required expiry, is
  stored only as a hash, and is revocable immediately. A de-provisioned user's
  tokens cease to function. *(Per IAM-06/07, KEY-03; bind by test.)*
- **SEC-35 - Invitations do not bypass the IdP.** An invitation pre-stages a
  role/scope for an SSO-authenticated identity only; it creates no password and
  grants no access until the invitee authenticates through the IdP; invitations
  expire and are revocable and audited. *(Per IAM-01/11.)*
- **SEC-36 - Settings changes are authorization-checked and audited.** Every
  settings write enforces the section's RBAC server-side (not in the UI) and is
  audited with the actor; org-config writes are versioned and round-trip (C1,
  C3). *(Per AZ-01/07.)*
- **SEC-37 - Headless parity, no weak path.** Headless REST/MCP clients are
  subject to identical grants, HITL gating, rate limits, budgets, and audit as
  the site; the user-authenticated MCP connection is scoped to the user's
  effective grants and runs the full chokepoint. *(Per AGT-09/AZ-03; bind by
  test.)*
- **SEC-38 - Mobile session hygiene.** Mobile/web sessions follow the same token,
  timeout, and revocation rules (IAM-12); no relaxed authentication for mobile.
  Connection details and tokens are never exposed to unauthenticated views.
- **SEC-39 - Authored verbs are safe-by-default.** A verb authored in the Router
  with a mutating/destructive effect must be markable (and defaulted)
  `high`-consequence so the HITL gate engages; authoring grants no caller
  authority over the verb (US-RTR-04). *(Per ADP-10/AZ-08.)*

---

# Chapter 7 - Non-Functional Additions

- **NFR-MOB-01 - Responsive performance.** The site is responsive across
  phone/tablet/desktop breakpoints and remains performant on mobile networks and
  devices; streaming in Chat degrades gracefully on slow connections.
- **NFR-A11Y-01 - Accessibility.** The UI targets WCAG 2.1 AA (keyboard,
  contrast, screen-reader labelling, focus, reduced motion).
- **NFR-SET-01 - Settings consistency.** UI and API settings paths are consistent
  (SET-03); a change made via one is reflected in the other.
- **NFR-MNT-01 - Core unchanged.** Settings, tokens, invitations, and Router
  authoring add routes, data, and UI over existing services and the registry; the
  kernel dispatch sequence is unchanged (verified by diff).

---

# Chapter 8 - Definition of Done (Round Four)

In addition to prior rounds' definitions of done, this round is complete when:

1. **Provisioning** - an unmapped/un-invited identity is denied; a mapped or
   invited identity is provisioned with its intended role/scope; an admin can
   view the directory, adjust role/scope within IdP bounds, and deactivate a user
   with immediate revocation, all audited.
2. **Authoring** - a noun and verb authored in the Router become
   caller-scoped-discoverable and invocable only under grants, versioned and
   round-tripping; high-consequence verbs engage the gate.
3. **Headless** - a personal access token scoped to a subset of the user's grants
   drives `/v1/invoke` and the user-authenticated MCP face, cannot exceed the
   user, and revokes immediately; connection details and client snippets are
   available in settings.
4. **Mobile** - Chat (streaming, tool/sub-agent cards, inline HITL) is fully
   usable on a phone; primary surfaces reflow responsively without horizontal
   scrolling; the UI meets WCAG 2.1 AA.
5. **Settings** - all sections are RBAC-gated, persisted, validated, and audited;
   every UI setting has an API equivalent with identical authorization; org-config
   edits version, roll back, and export to a manifest.
6. **Security & governance** - SEC-34..39 are bound to tests with catalogue
   entries; `check_invariants.py` passes at binding-debt 0; a diff confirms the
   kernel dispatch sequence is unchanged.

---

# Chapter 9 - Suggested Build Order & Handoff

1. **Personal access tokens + user-scoped MCP (PAT, US-HEAD-02)** - unblocks
   headless clients (Claude Code/Teams) immediately and establishes the
   token-security pattern (SEC-34/37).
2. **Settings shell + Account/Appearance/Notifications/Privacy/Security (per-user
   SET-*)** - the user-facing surface and its API parity.
3. **User management & invitations (USR / SET-90)** - directory, role/scope
   adjustment, deactivation, the optional invite flow.
4. **Router authoring (committed RTR)** - noun/verb/binding authoring with
   versioning and round-trip.
5. **Mobile/responsive pass (MOB)** - responsive layout and the Chat-first mobile
   experience on the chat component primitives; accessibility.
6. **Organisation & Administration settings (SET-90..98)** - host the Round Three
   Admin Console, connectors, budgets, models, HITL, retention, with
   history/export.

**Handoff note.** This closes the functional requirement rounds (One to Four).
The next phase is **refactoring and further security refinement to reduce the
codebase**, driven by the Security Hardening Specification (Batch 1 + Addendum)
and a forthcoming security-refinement requirement set. The combined functional
surface (Rounds One to Four) and security surface (the two security documents)
are the inputs to that consolidation. Maintain the governance ratchet throughout:
every guarantee bound, binding-debt 0, severability and single-chokepoint
integrity preserved, no `K-*` invention.
