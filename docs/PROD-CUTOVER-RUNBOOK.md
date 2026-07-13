# Prod cutover runbook - the full auth/tenancy/audit stack to jellytot-prod

Prepared while proven on dev; HELD at the irreversible step pending the Principal's
explicit go (COUNTY 7-11 D10). This is ready to execute the moment a path is chosen.

## Current prod state (jellytot-prod, verified read-only)
- Box: jellytot-prod-01. Repo `~/Projects/boltrig` at `83ac67f` (the old CF-Access
  commit); today's stack (HEAD `9eee84a`, ~28 commits ahead) is NOT there.
- Runs `boltrig/kernel|fleet|ui|pi-sidecar:0.1.0` (locally-built tags), postgres,
  redis, hatchet. Ports loopback-bound (kernel 127.0.0.1:8628, ui 127.0.0.1:8620).
- Auth: Cloudflare Access at the edge (`CF_ACCESS_TEAM_DOMAIN` + `CF_ACCESS_AUD`
  set, `BOLTRIG_DEV_AUTH=0`, no `BOLTRIG_AUTH_MODE`). The kernel verifies the CF
  Access JWT. Users are CF-Access-provisioned (will = superadmin via role map); they
  have NO first-party password.
- Git remote is https with no creds on the box, so `git pull` needs auth: get the
  code over by `git config` a token, or rsync/tar the working tree from the beelink
  (the cable IP is fastest: `rsync -av --exclude .git --exclude node_modules
  ~/Projects/boltrig/ willlilley@... ` is not set up for prod; use tar over ssh).

## The safety facts that make this Principal-gated
1. Removing CF Access makes the boltrig login + 2FA the SOLE gate on app.boltrig.io.
   A login/2FA fault locks the live console out until fixed on the box.
2. Existing CF-Access users have no password; session-auth needs a seeding path.
3. Prod DB holds real data. The current Alembic chain runs through
   `0023_hitl_request_binding`; unlike the older 0010-0019-only plan, 0022 includes a
   type conversion and column removal and has no automated downgrade. A verified
   off-box snapshot and restore rehearsal are mandatory before applying it.
4. Grant-narrowing (COUNTY 8) is backward-compatible: prod users have no
   org/workspace membership, so SEC-110 keeps their current grants unchanged.

## Common steps (all paths) - get the code + images + schema onto prod
1. Transfer HEAD to prod (tar over ssh, not rsync - avoids the git-creds gap):
   `cd ~/Projects/boltrig && git archive HEAD | ssh jellytot-prod 'cd ~/Projects/boltrig && tar -x'`
   (this updates the working tree only; running containers keep their image).
2. Build the 4 images on prod from the transferred tree (same Dockerfiles as dev).
3. Restore the pre-migration `pg_dump -Fc` into a disposable database, run
   `make migrate`, and complete the migration-parity and application smoke tests.
   Then stop production writers, take and verify a fresh off-box snapshot, apply
   `alembic upgrade head`, and confirm `alembic current` reports
   `0023_hitl_request_binding`. Rollback across 0022 means restoring that snapshot and
   the prior images together; never run `alembic downgrade` across 0022 and never
   roll back only the application image.
4. Bump `User.sessionVersion` is N/A here; force-reload open tabs after the UI image
   swap by the usual cache-bust (new index-*.js hash from the rebuild).
5. Set stack-owned Herdr/OpenCode/Browser CLI roots before any v2 agent-control profile is
   enabled: `BOLTRIG_HERDR_HOME=/var/lib/boltrig/herdr` and
   `BOLTRIG_OPENCODE_HOME=/var/lib/boltrig/opencode`, plus
   `BOLTRIG_BROWSER_CLI_HOME=/var/lib/boltrig/browser-cli` when browser verbs are
   enabled. Never bind prod to a human user's `~/.config/herdr`,
   `~/.local/share/herdr`, `~/.config/opencode`, `.opencode`, or browser profile
   state. Run `boltrig doctor --production` and treat `herdr_stack_home`,
   `opencode_stack_home`, `browser_cli_stack_home`, and `browser_cli_stack_cli`
   failures as blockers.

## Path A - ship code, KEEP Cloudflare Access (recommended, lowest blast)
Do the common steps, then `docker compose up -d --build kernel fleet-worker ui`.
Leave `BOLTRIG_AUTH_MODE` UNSET (CF Access resolver stays). Prod gains tenancy,
audit depth, model routing, the UX overhaul, and 2FA-readiness, with the auth gate
UNCHANGED (zero login risk). The login/2FA swap is a later deliberate step.
Verify: healthz 200 through CF Access; a normal CF-Access login still works; the
new /v1/audit/verify reports chain_intact. Rollback: re-`up -d` the prior image tag.

## Path B - belt-and-suspenders (session auth BEHIND CF Access)
Common steps, then set `BOLTRIG_AUTH_MODE=session` + seed will's password
(`boltrig initiate` refuses if an owner exists - instead add a one-off set-password
path or invite+accept for the existing user), and `up -d --build`. KEEP CF Access at
the edge, so a visitor passes CF Access AND the boltrig login (double gate). Verify
the boltrig login + 2FA enroll/challenge work end to end through CF Access. Only
after that, Path C removes CF Access.

## Path C - full cutover (boltrig login is the sole gate) - HIGHEST BLAST
Path B first (proven), then remove Cloudflare Access at the edge: reconfigure the CF
Access application on app.boltrig.io (delete the policy/app via the CF API with the
`still-block-6ced` token, Access:Apps:Edit) so requests reach the boltrig login
directly. Set a STRONG seed password (not the dev `admin-dev-boltrig`; the min-12
floor refuses `admin`). Verify a full login + 2FA + org/workspace + audit-verify
from a clean browser BEFORE closing the session that could still reach the box.
Rollback: re-add the CF Access application (keep its config exported first).

## Seeding the existing prod superadmin into session auth (paths B/C)
`boltrig initiate` is one-shot and refuses once an owner exists, and prod already has
will as a CF-Access superadmin. Options, cleanest first:
- Add a guarded `boltrig set-password --email <owner>` admin CLI (one-off, owner-only,
  argon2id) - small, reusable, the honest fix. Build this BEFORE a B/C cutover.
- Or: create an admin invitation for will's email and accept it (sets the password
  via the COUNTY 7 accept-invite flow) - uses only shipped routes.

## The one external dependency (audit)
External audit anchoring (RFC3161 TSA + KMS) needs a credential only the Principal
supplies (`BOLTRIG_AUDIT_TSA_URL` / `BOLTRIG_AUDIT_KMS_KEY_ID`); until set, anchors
are `is_dev_fallback=true` (still tamper-evident internally). Not required for any
cutover path.

---

## ACTUAL EXECUTION (2026-07-03) - what happened

Prod was found EMPTY (0 users / conversations / audit rows) on an OLD buggy schema
(users had no `role` column - the duplicate-users bug from the old commit), so the
cutover became a clean fresh deploy, not a data migration.

DONE:
- Backed up the (empty) DB: `~/Backups/nankle-precutover-*.sql.gz` on prod.
- Transferred HEAD, built the 4 images on prod, reset the schema (DROP SCHEMA public
  CASCADE + load the new schema.sql), brought up with `docker compose -f
  docker-compose.yml up -d` (prod uses ONLY docker-compose.yml, NOT the secure
  overlay - the overlay adds a compose Caddy on :80/:443 that conflicts with the host
  Caddy + CF tunnel).
- Set `BOLTRIG_AUTH_MODE=session`; seeded will as owner + org "Boltrig" + workspace
  "Main" with a strong password; set the org `require_two_factor=true` (2FA mandatory).
- Verified on loopback: healthz 200, login ok/superadmin, wrong-password 401.
- Prod DB is named `nankle` (predates the rename); DATABASE_URL points at it - fine.

GOTCHAS hit:
- The new docker-compose.yml prepends `127.0.0.1:` only for the HATCHET ports; prod's
  .env had them in the old full `127.0.0.1:PORT` format -> "invalid IP 127.0.0.1:
  127.0.0.1". Fixed: HATCHET_GRPC_PORT=7077, HATCHET_API_PORT=8888 (bare). KERNEL_PORT
  / UI_PORT stay full `127.0.0.1:8628` / `:8620` (the compose uses `${KERNEL_PORT}:8000`).

BLOCKED on a valid Cloudflare API token (the one in opbox-prod/.cloudflare.env returns
"Invalid API Token" - rotated/expired):
- Removing CF Access from app.boltrig.io (so the boltrig login + 2FA is the sole gate).
  Needs Access:Apps:Edit. Until then prod is belt-and-suspenders: CF Access at the edge
  + the boltrig login behind it.
- dev.boltrig.io -> the beelink dev stack. Needs a cloudflared tunnel ON THE BEELINK
  (the prod tunnel can't reach the beelink's localhost) + DNS/ingress = Tunnel:Edit +
  DNS:Edit. boltrig.io -> marketing is ALREADY live (host Caddy serves /srv/boltrig-
  marketing; apex returns 200 with <title>Boltrig</title>).

FOLLOW-UP HARDENING (non-blocking): set BOLTRIG_ALLOWED_HOSTS=app.boltrig.io + 
BOLTRIG_CORS_ORIGINS=https://app.boltrig.io (currently default permissive).
