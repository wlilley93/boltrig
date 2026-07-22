# First-party invite-only login ([2026] VJS-COUNTY 7)

The optional first-party email/password gate that can stand in for Cloudflare
Access as the sole internet-facing door. It reuses the existing users /
user_invitations / user_sessions plumbing; it is NOT a parallel account system.

Enable it (opt-in; existing deploys are unchanged when unset):

    BOLTRIG_AUTH_MODE=session
    BOLTRIG_SESSION_TENANT=<tenant>          # default: "default"
    BOLTRIG_SESSION_COOKIE_SECURE=1          # default on; set 0 only for local http

Seat the founding owner once (invite-only needs a first inviter):

    boltrig initiate --email owner@example.io   # prompts for a password; run-once

The CF Access resolver stays in the code; the prod cutover / CF-Access removal is
Principal-gated (D10), not done here.

## HTTP surfaces (what the login UI builds against)

All bodies are JSON. Cookies: `boltrig_session` (httpOnly, Secure, SameSite=Strict)
is the session; `boltrig_csrf` (readable) mirrors the session-bound CSRF token.
Every mutating request made with the session cookie MUST echo the CSRF token in the
`X-Boltrig-CSRF` header (safe GET/HEAD are exempt). Bearer/PAT requests are not
CSRF-gated.

The terminal client `boltrig chat` is such a PAT client: it authenticates with a
PAT bearer (`--token` / `BOLTRIG_CLI_TOKEN` / `~/.config/boltrig/cli.toml`) and
drives the same `/v1/chat` chokepoint as the site - no CSRF, no session cookie.

### POST /v1/auth/accept-invite   (public)
Consume a single-use invite token and set a password.

    req:  { "token": "boltrig_invite_...", "password": "<>=12 chars>" }
    200:  { "status": "ok", "email": "invitee@example.io" }
    400:  { "status": "error", "reason": "invalid or expired invite" }   # also for replay/expired
    400:  { "status": "error", "reason": "password must be at least 12 characters" }

The invite token is returned ONCE by the existing admin route
`POST /v1/admin/invitations` (now also returns `"invite_token"`). No self-signup.

### POST /v1/auth/login   (public)
Verify email+password, issue a session.

    req:  { "email": "...", "password": "..." }
    200:  { "status": "ok", "csrf_token": "...", "user": {"id","email","role"} }
          + Set-Cookie: boltrig_session=...; boltrig_csrf=...
    401:  { "status": "error", "reason": "invalid email or password" }   # generic, non-enumerating
    429:  { "status": "error", "reason": "too many attempts" }           # rate limited

Read `csrf_token` from the body (or the `boltrig_csrf` cookie) and send it as
`X-Boltrig-CSRF` on every later mutating request.

### POST /v1/auth/logout   (session; CSRF required)
Revoke the current session; clears cookies. `200 {"status":"ok"}`.

### POST /v1/auth/refresh   (session; CSRF required)
Rotate the session secret + CSRF token and extend the bounded expiry (call
periodically to keep a long browser session alive).

    200:  { "status": "ok", "csrf_token": "<new>" } + refreshed Set-Cookie

Existing session management (`GET /v1/me/sessions`, `DELETE /v1/me/sessions/{id}`)
is unchanged and works over the session cookie.
