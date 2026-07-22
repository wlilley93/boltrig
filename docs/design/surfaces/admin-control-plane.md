# Admin control-plane surface: ratified specification

Status: **ratified 2026-07-21**. Route: `#/admin`. This closes the Admin IA gate in the
Enhancement Charter.

## 1. Mental model

Admin is the operator's control desk for two different truths:

1. **Configuration** edits versioned manifest sections through typed, governed forms.
2. **Organisation** manages people, policy, invitations, workspaces, and AI-key references.

The top-level switch between those truths is fixed. Configuration never becomes a raw JSON
editor. Organisation never becomes one long wall of unrelated cards. Its five task modes are
Members, Policy, Invitations, Workspaces, and AI keys, with one task visible at a time.

## 2. The 80% paths

Configuration: select a manifest section, change a typed field, review the diff, and press
**Request change**. The result pauses for approval, then the exact verb is reapplied with its
single-use approval.

Organisation: choose one task, inspect its scoped records, and use the task's one primary action.
Server authority is always visible. Client role gates only decide navigation visibility.

## 3. Configuration contract

- Section selection is URL-stable within the admin route and backed by the section registry.
- SchemaFormV2 is the primary editor. Unknown operator-owned keys survive round trips.
- Invalid JSON in any advanced escape hatch blocks the request and retains focus.
- Review changes uses DiffView before submission.
- `control.config.upsert` is consequence-high. The canonical foreshadow, Request change copy,
  and PendingHumanCard are mandatory.
- Revision history is read-only until Rollback is armed. Rollback uses P27 and records a new
  revision. Credential values are never returned or rendered, only references.

## 4. Organisation contract

- Members: directory, role, grants, and scope. Writes use typed pickers and faithful denials.
- Policy: organisation name and policy fields through a governed SaveBar.
- Invitations: create and revoke with the exact recipient and scope visible.
- Workspaces: create, update, and scoped membership as supported by the server.
- AI keys: show provider and reference metadata only. Secret material uses SecretOnce and is
  never redisplayed.
- Only the active task mounts visible primary controls. The other tasks retain data through
  normal React state and server reads, not hidden duplicate forms.

## 5. Chat parity

| UI action | Verb path | Chat phrasing | Status |
|---|---|---|---|
| Update manifest section | `control.config.upsert` | "Set the runtime concurrency limit to 8." | exists |
| Roll back section | `control.config.rollback` | "Roll runtime configuration back to revision 12." | exists |
| Update organisation policy | `control.org.update` | "Rename the organisation to Acme Operations." | exists |
| Update member | `control.user.update` | "Give Alex author access in workspace support." | exists |
| Create or revoke invitation | `control.invitation.create` / `.revoke` | "Invite Alex as a viewer in support." | exists |
| Manage workspace | `control.workspace.create` / `.update` / `.member.add` / `.member.remove` | "Create a support workspace." | exists |
| Manage AI-key reference | `control.ai_key.set` / `.delete` | "Register the production Anthropic key reference." | exists |

Each write task exposes N16 ByChat built from current form state. Both clients receive the same
pending-human contract and use the same approval route.

## 6. Acceptance

- Configuration and Organisation are the only top-level views.
- Organisation shows one task at a time.
- No secret value is readable after creation.
- No config write bypasses the governed control verb.
- Diff, requester, exact params, approval, application, and revision remain traceable.
- Every denial comes from the server and every identifier is mono.
