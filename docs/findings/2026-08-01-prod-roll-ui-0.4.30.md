# Prod roll ui 0.4.30 - the 31-bug worker sweep reaches the tenants

Date: 2026-08-01. Both stacks rolled `ui v0.4.26-local` -> `v0.4.30`,
digest-pinned. No schema change deployed; kernel and fleet untouched.

## Final state

| stack | kernel | fleet | ui | public surface |
| --- | --- | --- | --- | --- |
| `app.boltrig.io` | `v0.4.28` | `v0.4.28` | `v0.4.30` | 200, fix observed |
| CV (client tenant) | `v0.4.28` | `v0.4.28` | `v0.4.30` | console :8621, fix observed |

UI digest `sha256:9bcb7519319e...`, read from the registry with
`buildx imagetools inspect`, never from the push exit code.

## Why the UI moved alone, again

Same reasoning as the 0.4.8 roll and recorded rather than papered over:
every change in v0.4.30 that tenants can observe is UI (PR #208, boltrig
8a14c69). Rolling kernel/fleet to v0.4.30 would restart a client's serving
kernel for byte-identical behaviour and would pull migration 0067 into a
roll that needs nothing from it. The version skew is deliberate.

Note `scripts/roll-release.sh` intentionally rolls all three images and
would have widened this roll; it was not used. A future all-three roll at
or past v0.4.30 must handle migration 0067 (background_job_reflection).

## What it carries

The 31-bug sweep of `apps/worker` and the shipped nginx artefacts, every
finding adversarially verified before its fix landed. The two that
motivated a fleet roll:

- `client_max_body_size 26m` on the `/v1/` proxy. nginx's compiled-in 1m
  default returned 413 for uploads the kernel explicitly allows (25 MiB
  knowledge files), before the kernel ever saw the request.
- Cache discipline for the SPA: `no-cache` HTML, immutable hashed
  `/assets/`, and a missing chunk is now a 404 rather than an
  `index.html` fallback that strict module-MIME refuses - which blanked
  the app after every redeploy until a hard reload.

Plus the refusal-envelope family (denied/error/unavailable kernel bodies
no longer render as success), conversation-switch and channel-switch
races, approval-retention fixes, and the desktop-origin repair (a Tauri
build without `VITE_API_BASE` now fails loudly instead of dialing its own
webview).

## Verified at the destination, not at the tag

Per stack, after `up -d --no-deps ui`: container healthy AND running the
v0.4.30 image (a container that never restarted reports healthy while
serving the old bundle), then the fix observed at the serving surface:
`cache-control: no-cache` on `/`, 404 with no HTML body for a missing
hashed chunk. For the canary this was confirmed twice - on the box at
`127.0.0.1:8620` and publicly through Cloudflare at `app.boltrig.io`.

## The ledger drift this roll surfaced

The three pin sources disagreed three ways before the roll: `tenants.yaml`
said kernel `v0.4.26-local` / fleet `v0.4.25`, the box ran `v0.4.28` for
both, and the overlay source working tree held an uncommitted
`v0.4.24 -> v0.4.25` edit from a roll that never landed. All three were
reconciled to measured RepoDigests (opbox-prod f567691) before the ui pin
moved (e9aefce). A pin that lags reality rolls production backwards; this
file keeps re-learning that, so the reconcile came first.
