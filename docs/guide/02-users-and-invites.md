# Users and invites

## Invite-only, no self-signup

There is no open self-signup. An account exists only by consuming a single-use, admin-created invitation. The founding owner is seated once by genesis (`boltrig initiate`); every other user is invited.

## Invite a user

Org-administration is required (`superadmin`, `admin`, or `org-admin`). Create the invitation:

```bash
curl -s -X POST http://localhost:8080/v1/admin/invitations \
  -H 'content-type: application/json' -H "x-boltrig-csrf: $CSRF" \
  --cookie "boltrig_session=...; boltrig_csrf=$CSRF" \
  -d '{"email":"jane@acme.com","role":"member","ttl_days":14}'
```

The response returns the invite token **once**:

```json
{"status": "ok", "id": "...", "email": "jane@acme.com", "invite_token": "<secret shown once>"}
```

Only the token's hash is stored (mirroring the PAT pattern); the raw secret is never persisted or re-shown. Hand the invitee an accept-invite link carrying that token. The invitation is bounded by its own expiry (`ttl_days`, default 14) and is revocable.

### Invite scope and provisioning (all optional)

Each provisioning arm is authorized **before** anything is written (a denial leaves no invitation behind):

- `workspace_id` - seat the invitee into an **existing** workspace on accept, with the invited role. The inviter must be able to manage that workspace (org-admin, or its owner/admin), else `403` with no write.
- `provision_workspace_name` - **create** that workspace on accept and seat the invitee as its owner. Org-admin / owner (already required by the admin check).
- `provision_org_name` - provision a brand-new org (a fresh tenant) on accept and seat the invitee as its owner. **Superadmin only** - a lesser admin is refused `403` with no write.

If none are set, the invitee is simply seated as a user in the console tenant.

List / revoke invitations:

```bash
GET    /v1/admin/invitations
DELETE /v1/admin/invitations/{invite_id}
```

## The privilege ceiling (no self-escalation)

Two clamps guard both `create-invite` and `update-user`:

- No principal may grant a role **ranked above its own**. An attempt raises "cannot grant a role ranked above your own" (`403`).
- Only the owner tier (`superadmin`) may grant `{all: true}` (all-authority) scope.

So an `admin` cannot mint a `superadmin`, and cannot pre-stage all-authority scope on an invitation that would later materialise into a real credential on accept.

## Accept an invite and set a password

The invitee consumes the token and sets their password in one call (public - the token itself is the bearer of authority):

```bash
curl -s -X POST http://localhost:8080/v1/auth/accept-invite \
  -H 'content-type: application/json' \
  -d '{"token":"<the invite secret>","password":"a-strong-passphrase"}'
```

- The password must pass the strength floor (`validate_password_strength`; 12+ characters is the safe floor), or the call is rejected `400`.
- The token must match a pending invitation and must not be expired or already used. Unknown / expired / already-used all return one generic rejection ("invalid or expired invite") so a probe cannot tell them apart.
- Consumption is atomic and single-use: only the winner of the race proceeds.
- Only the argon2id password hash is stored, apart from the identity row. On success the invitee becomes an active user with the invited role/scope, and any workspace/org provisioning on the invite is materialised.

The invitee can then log in normally at the console (see `00-getting-started.md`).

## Manage and deactivate users

List the directory (admin only):

```bash
GET /v1/admin/users
```

Update a user - role, scope, or status (admin only; the escalation clamp applies to role/scope):

```bash
curl -s -X PATCH http://localhost:8080/v1/admin/users/{user_id} \
  -H 'content-type: application/json' -H "x-boltrig-csrf: $CSRF" \
  --cookie "boltrig_session=...; boltrig_csrf=$CSRF" \
  -d '{"status":"deactivated"}'
```

Setting `status` to `deactivated` is an **immediate revoke**: the session resolver checks the current user on every request, so a deactivated user's live session stops resolving at once (fail-closed). Set it back to `active` to restore access. The valid statuses are `active` and `deactivated`.
