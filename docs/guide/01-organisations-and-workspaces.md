# Organisations and workspaces

## The model: org = tenant, workspace = a slice inside it

- An **organisation** is the tenant boundary. The organisation row's `id` **is** the `tenant_id` - exactly one org per tenant - so all row isolation stays keyed on `tenant_id`. An org carries a name, a url-safe slug, settings, and two policy flags: `allow_own_ai_keys` and `require_two_factor`.
- A **workspace** belongs to exactly one org and is tenant-scoped. It is a working slice inside the org (its own membership and settings). Genesis seeds one default workspace; you create more as you need them.

Membership is modelled separately from the entities:

- **OrgMember** - a user's org-level role, drawn from the platform role vocabulary.
- **WorkspaceMember** - a user's per-workspace role, drawn from a small fixed set (`owner`, `admin`, `member`, `viewer`, `agent`).

## Roles and what each can do

Two role vocabularies apply.

### Org / platform roles (precedence, most-privileged first)

`superadmin` (the owner) > `admin` > `org-admin` > `department-head` > `manager` > `engineer` > `member` > `agent` > `viewer`. An unmapped caller gets role `none` (fail-closed: no authority).

Organisation-administration routes accept the admin tier only: `superadmin`, `admin`, `org-admin`. The founding owner seated by genesis is `superadmin`.

### Workspace roles and their grant ceilings

When a caller is operating **inside an active workspace**, their org/user grants are narrowed by the workspace role's ceiling. Narrowing only ever intersects **down** - a workspace membership can take authority away, never add it. Configure/administer verbs live under the `control.*` namespace; workspace self-administration is the finer `control.workspace.*` slice.

| Workspace role | Ceiling (what it keeps) |
| --- | --- |
| `owner` | everything the org already grants; administers the workspace |
| `admin` | operate + configure (all resource + registry verbs), but not workspace self-administration (`control.workspace.*` denied) |
| `member` | operate only: resource verbs, no configure/administer (`control.*` denied) |
| `agent` | same operate ceiling as `member` (a non-human runtime seat; `control.*` denied) |
| `viewer` | read-only: keeps only concrete read verbs; every write and every wildcard grant collapses |

An unknown workspace role resolves to empty grants (fail-closed).

## How workspace membership narrows a caller's grants

On login the session picks a deterministic default active workspace from your memberships (or none if you belong to none yet). On **every** request the session resolver re-authorizes that active workspace against current membership: if the workspace was deleted or your membership was revoked, the active workspace drops to `None` (fail-closed) - a session can never keep workspace access it has lost.

Effective grants are then computed once, per request: `effective = (org/user grants) ∩ (active workspace role ceiling)`, but only when you are in an active workspace. With **no** active workspace your org grants apply unchanged. The kernel's grant chokepoint enforces those effective grants; the routes carry no workspace logic of their own.

## Create a workspace

Org-admin / owner only (creating a workspace is an org-level act). The creator is seated as the workspace `owner` immediately.

```bash
curl -s -X POST http://localhost:8080/v1/workspaces \
  -H 'content-type: application/json' -H "x-boltrig-csrf: $CSRF" \
  --cookie "boltrig_session=...; boltrig_csrf=$CSRF" \
  -d '{"name":"Engineering"}'
```

List your own workspaces (only those you are a member of):

```bash
GET /v1/workspaces
```

Rename / change settings / archive a workspace (org-admin, or an owner/admin of that workspace):

```bash
PATCH /v1/workspaces/{workspace_id}    # {"name": "...", "settings": {...}, "status": "active|archived"}
```

## Add and remove members

Add an existing org user to a workspace with a per-workspace role. Manage rights required (org-admin, or a workspace owner/admin). The role must be one of the five workspace roles; the target user must already exist in the org.

```bash
curl -s -X POST http://localhost:8080/v1/workspaces/{workspace_id}/members \
  -H 'content-type: application/json' -H "x-boltrig-csrf: $CSRF" \
  --cookie "boltrig_session=...; boltrig_csrf=$CSRF" \
  -d '{"user_id":"jane@acme.com","role":"member"}'
```

List a workspace roster (org-admin or a member of it):

```bash
GET /v1/workspaces/{workspace_id}/members
```

Remove a member (manage rights required):

```bash
DELETE /v1/workspaces/{workspace_id}/members/{user_id}
```

## Switch the active workspace

The active workspace lives on your session. Switching is re-authorized against membership: an unknown workspace is `404`, one you are not a member of is `403`, both with no write.

```bash
curl -s -X POST http://localhost:8080/v1/me/active-context \
  -H 'content-type: application/json' -H "x-boltrig-csrf: $CSRF" \
  --cookie "boltrig_session=...; boltrig_csrf=$CSRF" \
  -d '{"workspace_id":"ws_engineering"}'
```

Active context requires a first-party session login - a PAT / bearer principal has no session to carry an active workspace, so this route fails closed for it.

## The org itself

- `GET /v1/orgs/current` - your org's handle + policy flags (readable by any authenticated caller in the tenant; never a secret).
- `PATCH /v1/orgs/current` - org-admin only: rename, edit settings, toggle `allow_own_ai_keys` and `require_two_factor`.
- `GET /v1/orgs/current/members` - the org membership roster (used to populate an add-member picker).
