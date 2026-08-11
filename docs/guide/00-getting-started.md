# Getting started

## What Boltrig is

Boltrig is a governed agent-orchestration kernel: a single-tenant console where humans and AI agents run work through one audited chokepoint. Every external action (a tool call, a model call, an agent spawn) funnels through the kernel's `Dispatcher.invoke`, which resolves the verb, validates parameters, checks grants (deny-by-default), applies the human-in-the-loop gate, resolves any credential kernel-side, executes, and writes one tamper-evident audit row - in that fixed order, always. Identity is invite-only (no self-signup), credentials are sealed so an agent never sees a raw key, and sensitive-classified data is pinned to a local model endpoint. This guide is for the person standing up and administering a box.

## Stand up a box with genesis

`genesis.sh` is the one-shot founder ceremony: it turns a fresh `git clone` into a usable box in one run (fill secrets, bring the stack up, boot Hatchet, seed the founding superadmin, verify a real login).

```bash
cp .env.example .env      # genesis fills the blank internal secrets for you
bash genesis.sh dev       # target: dev | base | secure
```

Targets:

- `dev` - the kernel's own Caddy on `:8080`, loopback (local development).
- `base` - the plain `docker-compose.yml` stack.
- `secure` - the hardened compose overlay.

### Inputs (env first, then prompt)

Genesis reads these from the environment if set, otherwise prompts interactively (and falls back to the shown default when non-interactive, e.g. in CI):

| Variable | Prompt | Default |
| --- | --- | --- |
| `ORG_NAME` | First organisation name | `Boltrig` |
| `WS_NAME` | First workspace name | the org name |
| `SUPERADMIN_EMAIL` | Superadmin email | `will.lilley93@gmail.com` |
| `SUPERADMIN_PASSWORD` | Superadmin password | `admin` |

Non-interactive example:

```bash
ORG_NAME="Acme" WS_NAME="Acme HQ" \
SUPERADMIN_EMAIL="admin@acme.com" SUPERADMIN_PASSWORD="a-strong-passphrase" \
bash genesis.sh dev
```

### Password floor

The superadmin password must pass `validate_password_strength` before the owner is seated. The seed's default `admin` is below the strength floor and is intended only as a placeholder for a throwaway local box - supply a strong password (the strength check enforces a minimum length; 12+ characters is the safe floor) for anything you will expose.

### What genesis does (phases)

- Phase 0: copies `.env` / `manifest.yaml` if missing, fills blank internal secrets (`POSTGRES_PASSWORD`, `BOLTRIG_AUDIT_HMAC_KEY`), and sets `BOLTRIG_AUTH_MODE=session`, `BOLTRIG_DEV_AUTH=0` (invite-only first-party login is the gate).
- Phase 1: brings up Postgres + Redis and creates the separate `hatchet` database (Hatchet-lite needs its own db owned by the boltrig role or its engine never boots).
- Phase 2: builds and brings up the full stack, waits for the kernel to be healthy. A fresh volume loads the schema on first boot (no migration needed on a clean box).
- Phase 3: mints and wires the Hatchet client token, then restarts the fleet worker so it selects the durable executor.
- Phase 4: runs `boltrig initiate` to seat the founding OWNER (role `superadmin`), the default org (renamed to `ORG_NAME`), the default workspace (`WS_NAME`), and the owner's org + workspace memberships. This step is one-shot: it refuses to run twice once an owner exists.
- Phase 5: verifies `GET /healthz` and a real `POST /v1/auth/login` round-trip.

Genesis is idempotent and resume-safe: secret fills only touch blanks, and re-running after a mid-run crash reads back the persisted secrets. A clean end prints:

```
== GENESIS COMPLETE ==
   console:  http://localhost:8080    login: <your email>
```

## Log in

Open the Worker at `http://localhost:8082` (the `WORKER_PORT`, `8082` by default). The login page posts to `POST /v1/auth/login` with your email and password. On success the kernel sets an httpOnly session cookie (`boltrig_session`) plus a readable CSRF cookie (`boltrig_csrf`) and returns your user record.

From a headless client you can hit the same endpoint directly:

```bash
curl -s -X POST http://localhost:8080/v1/auth/login \
  -H 'content-type: application/json' \
  -d '{"email":"admin@acme.com","password":"your-password"}'
```

Login is rate-limited (5/min per identity, 30/min per IP), verifies in constant time, and returns one generic failure (`invalid email or password`) whether the email is unknown, the password is wrong, or the user is deactivated - so the response never reveals which emails exist.

Change the seed password before exposing the box to the internet. There is no open self-signup: every other account exists only by accepting an admin-created invitation (see `02-users-and-invites.md`).
