# Secure deployment

The same images run everywhere; security is configuration, not a rebuild (P7).
This covers encryption in transit (SEC-10), encryption at rest (SEC-11), and the
corporate proxy + internal CA wiring (US-DEP-04).

## Deploy a signed release

Production runs the exact first-party image digests verified by the release
workflow; it does not rebuild mutable source on the target host. Check out or
transfer the protected release tag so its Compose manifests and migration chain
match the images, then download `boltrig-images.env` from that GitHub release.
The file contains exactly the kernel, fleet, UI, and backup
`image@sha256` references.

With the normal production configuration in `.env`:

```bash
make release-validate RELEASE_IMAGES_ENV=boltrig-images.env RELEASE_ENV=.env
make release-up RELEASE_IMAGES_ENV=boltrig-images.env RELEASE_ENV=.env
```

The validator rejects missing, additional, or tag-based image values. The launch
layers `deploy/compose.release.yml` and `deploy/compose.secure.yml` over the base
manifest, enables the scheduled backup profile, pulls the recorded digests, and
uses `--no-build`. The release overlay also removes the developer bind mount of
`scripts/backup.sh`, so the signed backup image cannot be replaced by mutable
host source. Set `RELEASE_PROFILES=` only when backup scheduling is provided and
verified by an external operator mechanism.

## `git pull` on the deployment tree IS a deploy step

The images above are digest-pinned, and that covers only what is IN them. The base
compose bind-mounts host paths straight into running containers, and those bytes
come from a git checkout on the box, not from any image:

| container | mounted from the deployment tree |
| --- | --- |
| kernel, fleet-worker | `manifest.yaml`, `libraries/` (the skills the agents load) |
| postgres | `boltrig/store/schema.sql` |

**A bind-mounted directory is a deployment surface exactly like an image tag, and
digest pinning does nothing for it.** On 2026-07-27 `app.boltrig.io` was serving a
correctly-pinned kernel while its deployment tree sat 57 commits behind `main`. A
merged fix to `libraries/skills/ops/opbox.yaml` - eight `tool_grants` naming the
kernel door's noun-first verbs while the tenant runs the frontend door's verb-first
ones, so none of them resolved and the skill's Opbox reach was nil - stayed
undelivered for three days. Nothing was wrong with the release; the deploy was
simply half done, and no step in this document said so.

So a roll is:

```bash
# 1. the tree the containers read from
ssh <host> 'cd ~/Projects/boltrig-main && git pull --ff-only origin main'
# 2. the images
docker compose ... pull && docker compose ... up -d
# 3. prove BOTH halves landed, on EVERY tenant, before calling it done
make fleet-drift-all
```

`make fleet-drift-all` compares each pinned digest against what the daemon is
actually running AND reports any bind-mounted path whose upstream has commits it
has not pulled. Staleness is scoped to the mounted path, so an unrelated merge does
not turn it red; a detached HEAD on a deployment tree is reported as the finding it
is. It needs a box, so it is an operator command and never a CI gate.

## TLS in transit (SEC-10)

Run the secure overlay, which puts a Caddy TLS terminator in front of the UI and
the kernel and stops publishing their ports directly:

```bash
BOLTRIG_DOMAIN=boltrig.example.com \
  docker compose -f docker-compose.yml -f deploy/compose.secure.yml up -d
# or: make secure-up
```

- For a public domain Caddy auto-provisions a certificate; for `localhost` it uses
  its built-in internal CA. To present an internal-CA / corporate certificate,
  replace auto-TLS in `deploy/Caddyfile.example` with `tls /certs/site.crt
  /certs/site.key` and mount those files into the `caddy` service.
- Only Caddy is reachable from outside; the kernel and UI lose their host ports in
  the overlay. Internal service-to-service traffic stays on the compose network.
- Postgres connections use TLS by putting `sslmode=require` in `DATABASE_URL`.
  For host-spanning deployments, terminate mTLS for adapter connections to
  enterprise services per the adapter's credential material.

## Encryption at rest (SEC-11)

Postgres data, library artefacts, and backups must sit on encrypted storage. The
app does not encrypt the disk; the deployment does, with no image change:

- Point the Postgres data dir at an encrypted device or path and set it via env:
  `PGDATA_HOST=/mnt/luks/boltrig-pgdata docker compose ... up -d`. Use a LUKS
  volume on-prem, or a cloud encrypted disk (EBS/PD/Azure Disk with CMK).
- Put backups (`./backups`, see `backup-restore.md`) on the same encrypted media.
- The external secret store (Vault/KMS) holds credentials; the app DB stores only
  references (SEC-04), so an at-rest disk never contains plaintext secrets.

## Corporate proxy + internal CA (US-DEP-04)

- Egress proxy: set `HTTP_PROXY` / `HTTPS_PROXY` / `NO_PROXY`. They are passed as
  build args and read at runtime; adapters honour them for outbound calls.
- Internal CA: set `CA_BUNDLE` to the in-container path of your CA bundle. The
  secure overlay mounts `${CA_BUNDLE_FILE:-./deploy/ca-bundle.crt}` to
  `/certs/ca.pem` in the kernel and fleet containers; set `CA_BUNDLE=/certs/ca.pem`.
- Air-gapped: set `AIR_GAPPED=1`, disable hosted model endpoints, and run the
  `local-model` profile; no component requires internet to start (SEC-20).

## Herdr/OpenCode/Browser CLI stack state

Herdr, OpenCode, and Browser Use CLI state are stack components. The first-party
images ship pinned CLI binaries (`herdr` in the kernel image, `opencode` and
`browser-use` in the fleet-worker image), and production must use clean
service-owned state roots, not an operator's personal terminal, coding-agent, or
browser profile:

```env
BOLTRIG_HERDR_HOME=/var/lib/boltrig/herdr
BOLTRIG_OPENCODE_HOME=/var/lib/boltrig/opencode
BOLTRIG_BROWSER_CLI_HOME=/var/lib/boltrig/browser-cli
```

The base compose file backs these with named volumes. The first-party images
create the root, home, config, data, and state directories as the unprivileged
`boltrig` user so fresh named volumes start writable by the service; Browser CLI
also gets a stack-owned cache directory. Do not bind-mount `~/.config/herdr`,
`~/.local/share/herdr`, `~/.config/opencode`, `.opencode`, or personal browser
profile state into the stack. Run `boltrig doctor --production` before cutover;
it fails when these roots are unset, point at user-owned state, or the runtime
cannot resolve stack-owned `herdr` / `opencode` / `browser-use` binaries.

To upgrade the shipped CLIs, change the pinned Herdr/OpenCode version and sha256
build args in `deploy/kernel.Dockerfile` / `deploy/fleet.Dockerfile`, or update
`deploy/browser-cli-requirements.in` and regenerate
`deploy/browser-cli-requirements.txt` for Browser Use CLI with
`uv pip compile deploy/browser-cli-requirements.in --overrides deploy/browser-cli-overrides.txt --generate-hashes --python-platform linux -o deploy/browser-cli-requirements.txt`.
Rebuild the images after any change. Production doctor still requires
`browser-use` to resolve from the deployed stack path before browser verbs are
treated as ready. Do not set
`HERDR_BIN`, `BOLTRIG_OPENCODE_BIN`, or `BOLTRIG_BROWSER_CLI_BIN` to binaries
under a developer home directory, and do not copy binaries or profiles from a
developer workstation into production.

Herdr, OpenCode, and Browser CLI child processes do not inherit the service
environment wholesale. They receive stack-owned `HOME`/XDG paths and a small
runtime allowlist (`PATH`, proxy, locale, CA-bundle settings). Only explicit
scoped handoffs are added, such as OpenCode's per-run Boltrig MCP token or
Browser CLI's per-run `BU_NAME`. Browser Use cloud/profile env is disabled by
default:

```env
BOLTRIG_BROWSER_CLOUD_POLICY=disabled
```

If a deployment uses Browser Use cloud profiles, set
`BOLTRIG_BROWSER_CLOUD_POLICY=stack` and provide only stack-owned handoff values
such as `BOLTRIG_BROWSER_CLOUD_API_KEY` and
`BOLTRIG_BROWSER_CLOUD_PROFILE_ID`. The adapter maps those into the child
process. Do not set personal `BROWSER_USE_*` variables in the service
environment; they are stripped from child processes and are not a supported
production configuration.

`GET /v1/platform/status` includes a redacted Herdr/OpenCode/Browser CLI stack
posture. It reports image-shipped install mode, stack-owned state posture, and
which container owns the runtime, but it never returns actual state roots,
binary paths, browser auth/session data, Browser Use cloud values, tokens,
credentials, or user profile locations. Treat it as the operator-facing
confirmation that the deployed stack is cleanly wired; `boltrig doctor
--production` remains the hard pre-cutover gate that verifies binaries resolve
in their target images.

## Model Gateway Health

The Bifrost/model-gateway seam is inert until `BOLTRIG_MODEL_GATEWAY_URL` is set.
`GET /v1/platform/status` always reports the safe static posture. Optional live
health polling is disabled unless the deployment sets:

```env
BOLTRIG_MODEL_GATEWAY_HEALTH=1
BOLTRIG_MODEL_GATEWAY_HEALTH_PATH=/health
```

Boltrig derives the health URL from the internal `/v1` gateway base, for example
`http://bifrost:8080/v1` to `http://bifrost:8080/health`. An explicit
`BOLTRIG_MODEL_GATEWAY_HEALTH_URL` is allowed only for internal-looking hosts;
external hosts are rejected and never polled. The status payload exposes only
coarse health/cache/provider counts, not gateway URLs, provider keys, tokens,
credentials, or raw gateway payloads.

## Database migration and rollback safety

Alembic is the authoritative production upgrade path. `boltrig/store/schema.sql`
is only a fresh-database bootstrap and is checked for catalogue parity by
`make migration-parity`; never replay it over an existing deployment.

Before every production migration:

1. stop writers or put the service into a maintenance window;
2. take an off-box `pg_dump -Fc` snapshot and verify it with `pg_restore --list`;
3. rehearse `alembic upgrade head` and application smoke tests against a restored
   copy of the production snapshot;
4. record `alembic current` and confirm it advances to the expected head; and
5. retain the prior application images until the migration smoke is complete.

Revision `0022_schema_parity` is deliberately irreversible. It reconciles
objects that may have existed outside Alembic, converts `users.groups` from
JSONB to `TEXT[]` where necessary, and removes the obsolete `users.updated_at`
column. Its `downgrade()` fails closed because an automated reverse migration
could destroy or misinterpret production data. Rollback across this boundary is
a coordinated restore of the verified pre-migration database snapshot plus the
prior application images; do not use `alembic downgrade` and do not roll back
only the code.

## Liveness and readiness

`GET /healthz` remains the liveness endpoint. `GET /readyz` is the unauthenticated,
redacted deployment-readiness endpoint and returns HTTP 503 whenever a required
component is not ready. In production it requires reachable Postgres and Redis,
an `alembic_version` exactly equal to the packaged migration head, complete
`control.*` registration, safe Herdr/OpenCode/Browser CLI stack posture, a
kernel-local `herdr --version` probe, and a fresh HMAC-authenticated Redis
receipt from the fleet worker's local OpenCode, Browser Use, and loopback
Chromium CDP probes. Receipt keys are deployment-scoped and the signing key is
purpose-derived from `BOLTRIG_AUDIT_HMAC_KEY`, so another service or deployment
cannot forge or collide with healthy evidence. The receipt expires when the
worker or its tools stop reporting; the kernel does not assume fleet binaries
share its image or hard-code a fleet service address.
Development retains posture-only compatibility unless
`BOLTRIG_REQUIRE_STACK_TOOL_HEALTH=1` is set.

Hatchet is live-probed when `BOLTRIG_HATCHET_HEALTH=1`,
`BOLTRIG_REQUIRE_DURABLE=1`, or `HATCHET_CLIENT_TOKEN` is configured. The model
gateway is live-probed when `BOLTRIG_MODEL_GATEWAY_HEALTH=1` or an explicit
internal health URL is configured. Once enabled, either seam is required and a
failed probe makes readiness fail closed. Bound every dependency probe with
`BOLTRIG_READINESS_TIMEOUT` (default 0.75 seconds). The response contains only
coarse status/reason codes and migration revision names; it never returns DSNs,
URLs, credentials, command output, binary paths, or raw exception messages.
Concurrent calls are coalesced and the redacted result is cached briefly
(`BOLTRIG_READINESS_CACHE_TTL`, default 1 second) so the unauthenticated
orchestrator endpoint cannot amplify into unbounded subprocess/dependency
probes.
`BOLTRIG_STACK_TOOL_RECEIPT_TTL`,
`BOLTRIG_STACK_TOOL_HEARTBEAT_INTERVAL`, and
`BOLTRIG_STACK_TOOL_PROBE_TIMEOUT` tune the bounded worker receipt loop; see
`.env.example` for defaults and limits.

## Checklist

- [ ] Protected release selected; downloaded `boltrig-images.env` passes
      `make release-validate` and contains five `@sha256` image refs
- [ ] `make release-up` completed with the secure overlay (TLS terminator in
      front; kernel/UI/local-model host ports closed; no first-party rebuilds)
- [ ] `DATABASE_URL` has `sslmode=require`
- [ ] `PGDATA_HOST` on an encrypted device; backups on encrypted media
- [ ] `CA_BUNDLE` set and the bundle mounted; proxy env set if required
- [ ] `BOLTRIG_HERDR_HOME`, `BOLTRIG_OPENCODE_HOME`, and `BOLTRIG_BROWSER_CLI_HOME`
      set to stack-owned roots
- [ ] Herdr/OpenCode CLI versions and hashes reviewed before image rebuild
- [ ] `boltrig doctor --production` sees stack-owned `herdr`, `opencode`, and
      `browser-use` CLIs
- [ ] `/readyz` is 200 only after the fleet worker has published fresh live-tool
      evidence; stopping the worker or Chromium makes it return 503 after TTL
- [ ] real OIDC configured (`OIDC_*`), `BOLTRIG_DEV_AUTH` unset (SEC-01)
- [ ] verified off-box database snapshot and restore rehearsal completed before
      `make migrate`; current Alembic revision recorded
