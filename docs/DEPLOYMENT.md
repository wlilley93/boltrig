# Secure deployment

The same images run everywhere; security is configuration, not a rebuild (P7).
This covers encryption in transit (SEC-10), encryption at rest (SEC-11), and the
corporate proxy + internal CA wiring (US-DEP-04).

## Deploy a signed release

Production runs the exact first-party image digests verified by the release
workflow; it does not rebuild mutable source on the target host. Check out or
transfer the protected release tag so its Compose manifests and migration chain
match the images, then download `boltrig-images.env` from that GitHub release.
The file contains exactly the kernel, fleet, Worker UI, and backup `image@sha256`
references. The fleet digest serves both `fleet-worker` and the durable
`hatchet-worker`; the release overlay pins both entry points and removes both
local build definitions.

With the normal production configuration in `.env`:

```bash
make release-validate RELEASE_IMAGES_ENV=boltrig-images.env RELEASE_ENV=.env
make release-up RELEASE_IMAGES_ENV=boltrig-images.env RELEASE_ENV=.env
```

Run these commands from the exact protected semantic-tag checkout. Install
Cosign and a GitHub CLI with `gh attestation verify` on the deployment host;
validation reads public signature/attestation evidence from GHCR and does not
need a signing credential. If multiple protected semantic tags point at the same
commit, pass the intended one as `RELEASE_TAG=vX.Y.Z`.

The validator rejects missing, additional, or tag-based image values, then
verifies each digest's release-workflow signature, CycloneDX SBOM attestation,
and SLSA provenance against the canonical repository, exact tag, and checked-out
commit. Only after that evidence passes, it pulls the exact kernel and fleet
digests, assembles an unpushed validation image from them, executes the three CLI
version probes, and runs production doctor there. The validation container has
no network, a read-only root filesystem, no capabilities, and receives `.env`
over stdin. It is removed after the check; pulled layers may remain in the local
Docker cache. No service is started or changed. Missing tools, network access,
evidence, image executables, or identity match fail closed. The launch
layers `deploy/compose.release.yml` and `deploy/compose.secure.yml` over the base
manifest, enables the scheduled backup profile, pulls the recorded digests, and
uses `--no-build`. The release overlay also removes the developer bind mount of
`scripts/backup.sh`, so the signed backup image cannot be replaced by mutable
host source. Set `RELEASE_PROFILES=` only when backup scheduling is provided and
verified by an external operator mechanism.

### Worker presentation

Worker is the sole first-party browser surface and is the default Caddy upstream.
The old Operator application, image, deployment overlay and browser path have
been removed. The kernel, dispatcher, database, identities, conversations and
run state remain unchanged by this presentation cleanup.

### Channel-gateway bootstrap and failover (not production-admitted yet)

The protected secure release currently refuses the `channels` profile. The
gateway and WhatsApp bridge are not yet members of the signed image set, and the
secure sandbox has no reviewed provider-egress route. The steps below are for
development and isolated acceptance only; they do not override that release
gate. Production enablement requires signed/SBOM/provenance-bound channel images,
a constrained egress design, and real-provider acceptance.

Worker is the canonical channel configuration surface. Author each socket
channel there with write-only secret-store reference names, then issue the
show-once token for the exact channel set from its detail panel. Mount the token
read-only at `CHANNEL_GATEWAY_TOKEN_FILE`; leave
`CHANNEL_GATEWAY_CHANNELS` empty outside development. The environment-token
alternative is restart-only and must not be configured at the same time.

Before declaring a gateway ready:

1. confirm the database revision exactly matches the packaged Alembic head
   (`alembic heads` and `alembic current` must agree, and `/readyz` must report
   the migration check ready);
2. confirm `GET /ready` succeeds (not merely `/health`);
3. confirm each enabled socket channel has the intended owner label and an
   unexpired lease, then separately prove real provider send/receive;
4. for replacement, stop or fence the old owner and allow its 45-second
   per-channel lease to expire before expecting the standby to receive secrets;
5. exercise at least one real duplicate-session/failover acceptance cycle for
   each deployed provider.

The lease proves single ownership, not process liveness or provider delivery.
Signal and WhatsApp still require external device/account pairing. Token-file
replacement can recover after an authorization refusal; environment tokens
require restart. The MCP token registry is process-local, so gateway requests
must remain sticky to the kernel replica that minted the token (or the
deployment must use one kernel API replica) until a reviewed shared registry
or workload-identity contract replaces that limitation. The gateway does not
mint its own identity or token.

## The deployment tree is immutable release input

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

Do not `git pull` a moving branch on a live host. Check out the protected semantic
tag, require no modified/staged/deleted tracked files, and run `release-validate`
before `release-up`. Those commands bind the host-read Compose, manifest,
libraries, and schema to the same protected commit as the signed image evidence.

`scripts/roll-release.sh` predates the four-image signature/SBOM/provenance gate
and is retained only for legacy/dev investigation. It is not a production
deployment path. The current procedure is
`docs/PROD-CUTOVER-RUNBOOK.md`.

## Validate the manifest with the CANDIDATE image before swapping (task #59)

The database has a version chain, a recorded head, and a parity gate. The
manifest has none of those, and on 2026-07-31 that asymmetry crash-looped a
production kernel on a required spawn-rule field after a flawless database
pre-flight. So before pointing a stack at a new image, parse each target's
manifest with the code that will read it:

```bash
docker run --rm --env-file <stack .env> \
  -v /path/to/manifest.yaml:/m.yaml:ro \
  ghcr.io/wlilley93/boltrig-kernel:<candidate tag> \
  boltrig config-validate /m.yaml
```

Exit 0 means the process will get past config with this build - nothing more
(credentials and endpoints are the doctor's and readiness's jobs). Exit 1 names
the rejection; exit 2 is operator error (no such file). Pass the stack's env
file: `${VAR}` interpolation resolves against the validating process, so a bare
run can fail on a variable that IS set in production - a false red, never a
false green, but a needless one.

The standing half of the same gate runs in CI:
`tests/unit/test_config_validate_cli.py` parses `manifest.example.yaml` with the
shipping loader on every push, so a commit that adds a required field without a
default goes red in the suite before any box meets it.

## Self-hosted host migration preflight

The signed release path above is canonical for production. This section covers
the host-dependent failures that can still appear on a new Linux server, and the
explicitly non-production image-relay path used by disconnected development
hosts. Do not turn any of these host accommodations into a weaker public image
or a provider-specific shipping default.

### Match the image to the host

Before changing a running stack, record the current container image IDs and the
candidate platform:

```bash
uname -m
docker image inspect <candidate-kernel> <candidate-fleet> \
  --format '{{.RepoTags}} {{.Id}} {{.Os}}/{{.Architecture}}'
for service in kernel fleet-worker hatchet-worker; do
  container="$(docker compose ps -q "$service")"
  docker inspect "$container" \
    --format '{{.Name}} {{.Config.Image}} {{.Image}}'
done
```

Production obtains the correct platform through the verified digest-pinned
release set. For a low-bandwidth or disconnected **development** host only, an
operator may fetch/build the exact platform elsewhere, then relay an archive:

```bash
docker save --platform linux/amd64 <kernel-image> <fleet-image> | gzip -1 \
  > boltrig-images-linux-amd64.tar.gz
shasum -a 256 boltrig-images-linux-amd64.tar.gz
# transfer over the trusted operator path
sha256sum boltrig-images-linux-amd64.tar.gz
gzip -dc boltrig-images-linux-amd64.tar.gz | docker load
```

The two checksums must match. `docker save` must name the platform when the local
store contains a multi-architecture index. `docker load` commonly restores the
selected manifest without its registry `RepoDigest`; a host-local tag in a
private development override is therefore acceptable only as recorded local
evidence. It is not a substitute for signature, SBOM, provenance, or digest
verification and must never be called a production release.

BuildKit may lexically warn that `BOLTRIG_CODEX_AUTH_HELPER` looks secret-like.
Its shipping value must remain only the root-owned helper executable path; it is
not a credential. Verify that fact rather than disabling the scanner or ever
placing secret material in that variable.

### Prove the Codex sandbox on the target kernel

Every process that composes the trusted Codex runtime proves the sandbox at
startup: `kernel`, `fleet-worker`, and `hatchet-worker`. Ubuntu 24.04 and later
requires the repository's named AppArmor profile as well as the narrow Docker
seccomp exception used by nested Bubblewrap:

```bash
sudo cp deploy/apparmor/boltrig-codex /etc/apparmor.d/boltrig-codex
sudo apparmor_parser -r -W /etc/apparmor.d/boltrig-codex
```

Add `seccomp:unconfined` and `apparmor:boltrig-codex` to those three services in
the host overlay while retaining `read_only`, `cap_drop: [ALL]`, and
`no-new-privileges:true`. Read and run the real proof in
`deploy/apparmor/README.md` before rollout. `unshare -Ur true` is not proof: it
does not exercise the mount/pivot-root legs. Do not use
`apparmor=unconfined`, disable the host-wide unprivileged-userns restriction, or
skip `prove_sandbox_engagement` to make a container start.

The image's service user is uid 10001. Do not override it to root: with
`cap_drop: ALL`, root has no `CAP_DAC_OVERRIDE`, so an apparently privileged
container can be less able to write its intended service-owned paths. After
startup, require `id -u` to report 10001 in all three services.

### Preserve and separate stack-owned state

Fresh named volumes inherit the image's uid-10001 ownership. Imported or legacy
volumes may not. Inspect the exact mounted volume before changing it, stop its
owner, then repair only that named volume with the verified candidate image:

```bash
docker inspect <container> \
  --format '{{range .Mounts}}{{if eq .Type "volume"}}{{.Name}} -> {{.Destination}}{{println}}{{end}}{{end}}'
docker compose stop <owning-service>
docker run --rm --user 0:0 --entrypoint sh \
  -v <exact-volume-name>:/state <verified-candidate-image> \
  -c 'chown -R 10001:10001 /state'
```

Never run a recursive ownership change against an unresolved variable, a host
root, or a mounted personal profile. Fleet and Hatchet run independent Chromium
processes and must not share a browser profile lock:

```env
BOLTRIG_FLEET_BROWSER_CLI_HOME=/var/lib/boltrig/browser-cli/fleet-worker
BOLTRIG_HATCHET_BROWSER_CLI_HOME=/var/lib/boltrig/browser-cli/hatchet-worker
```

They may share the deployment-owned volume because their roots differ. The
Fleet entrypoint exports its own loopback `BU_CDP_URL`; operators must not point
it at a desktop browser. If an image build or headless server asks a human to
enable `chrome://inspect` or approve remote debugging, reject that image: the
CLI has fallen off the stack-owned browser path.

### Keep Hatchet identity and recovery state together

Hatchet durability spans three coupled items: its database, the
`hatchet_config` volume containing token-signing state, and the worker token.
Do not delete/recreate the config volume while moving an engine, and never touch
another stack's Hatchet container or config as part of a Boltrig rollout.
Back up and restore the database and config as one recovery point using
`docs/backup-restore.md`.

If the signing state is lost, every old worker token becomes unauthenticated.
Mint a replacement only against the intended restored/new engine, write it
atomically into the operator secret source, and record only a one-way
fingerprint—not the token—in the change record. A healthy
`hatchet-worker` means its listener has connected and heartbeated; do not infer
registration merely because the engine container is running.

### Keep provider configuration deployment-private

Boltrig ships provider-neutral. A private development model host, provider URL,
model identifier, or API key belongs only in that deployment's server-side
secret/configuration state and Bifrost volume; it must not enter
`manifest.example.yaml`, Compose defaults, images, the Worker bundle, or public
documentation examples. Run this before publishing any release candidate:

```bash
make public-product-validate
```

The gate requires BYO Bifrost configuration and Familiar + Jarvis as the only
shipping companions. Provider credentials remain kernel/Bifrost-side and never
become Worker fields. Governed model endpoints must use a catalogue-advertised,
exact immutable model ID; aliases containing `latest`, `default`, `preview`,
`stable`, or the other mutable segments rejected by `exact_model_id()` are not
valid routes.

Set `BOLTRIG_MODEL_GATEWAY_HEALTH=1` when the gateway is required. Values such
as `0`, `false`, `off`, and `no` mean disabled; they must not be used as a
placeholder for a required gateway. Before opening ingress, require Bifrost
health, catalogue membership for the exact route, and one bounded
non-effectful inference canary through the same internal URL the kernel uses.
Do not print provider credentials or private endpoint details into the rollout
record.

### Roll only the intended services, then verify through the edge

Create explicit rollback image references and preserve the pre-change Compose
override before a development rollout. Recreate only the affected first-party
runtime services; do not restart Postgres, Redis, Bifrost, or Hatchet engine as
a side effect of changing the kernel/Fleet bytes:

```bash
docker compose config --quiet
docker compose up -d --no-deps --force-recreate \
  kernel fleet-worker hatchet-worker
docker compose ps
```

Allow health start periods to elapse. Then record the actual image IDs and
require all of the following, not a subset:

- database `alembic current` equals the packaged `alembic heads`;
- the live sandbox proof succeeds on the target host;
- kernel `/readyz` is `ready` with Postgres, Redis, Hatchet, migration, model
  gateway, control plane, and stack tools OK;
- Fleet and Hatchet report different browser roots and both are healthy;
- the model canary succeeds when a gateway is enabled; and
- `/`, `/healthz`, and `/readyz` succeed through the real external edge.

For production, rollback means the previously verified signed release and its
matching recovery point, as described in `docs/PROD-CUTOVER-RUNBOOK.md`; a local
rollback tag is development evidence only. Move large local transfer archives
to recoverable trash after the verified server copy is retained, so a relay
does not silently consume the build machine's disk.

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
- Do not infer exposure from a host firewall rule alone. Overlay-network agents
  can install earlier packet-filter rules and bypass an apparently restrictive
  frontend. Prefer explicit loopback/interface binds and the secure overlay,
  then verify listeners with `ss -lntp` and probe from a genuinely external
  host before opening ingress.
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
BOLTRIG_FLEET_BROWSER_CLI_HOME=/var/lib/boltrig/browser-cli/fleet-worker
BOLTRIG_HATCHET_BROWSER_CLI_HOME=/var/lib/boltrig/browser-cli/hatchet-worker
```

The base compose file backs these with named volumes. The first-party images
create the root, home, config, data, and state directories as the unprivileged
`boltrig` user so fresh named volumes start writable by the service; Browser CLI
also gets a stack-owned cache directory. Do not bind-mount `~/.config/herdr`,
`~/.local/share/herdr`, `~/.config/opencode`, `.opencode`, or personal browser
profile state into the stack. Use `make release-validate` before production
cutover. It runs doctor against the operator configuration inside the verified
candidate-image context, where all three stack-owned executables exist. A bare
host-side `boltrig doctor --production` remains a useful diagnostic, but its CLI
checks describe that host and must not be used as release-image evidence.

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

Password-reset delivery is disabled in the standard ASGI composition. An
embedding deployment may inject a reviewed async notifier and a bounded,
redacted readiness probe through
`build_app(password_reset_notifier=...,
password_reset_readiness_probe=...)`. Set
`BOLTRIG_REQUIRE_PASSWORD_RESET_DELIVERY=1` only when first-party session
recovery is required; readiness then fails unless both callables are composed
and the probe returns exactly `true`. The probe result establishes only adapter
posture. The authenticated Operate projection likewise reports a bounded,
recipient-free notifier attempt—not a provider receipt or proof of inbox
delivery. Keep provider credentials in the deployment secret store and validate
real delivery, bounce handling and provider receipts in staging before cutover.

## Signed Worker desktop updates

### Browser agent versus desktop-local agent

Browser Chat is a cloud agent: it calls the authenticated Boltrig kernel, and
the hosted server-cell admission in `docs/CODEX-PRODUCTION-ADMISSION.md` must be
open. The signed Tauri Chat surface is a local agent: it starts a private Codex
App Server over stdio and executes approved file/Bash work on the user's own
computer. There is no silent fallback between them.

Development builds may resolve `BOLTRIG_LOCAL_CODEX_BIN` (an absolute file) or
`codex` from `PATH`; the UI labels that source `development`. Release builds do
not trust a host install. The protected desktop matrix runs
`scripts/stage_desktop_codex.py`, which downloads the official platform package
for Codex 0.144.3, verifies the exact archive and executable SHA-256 values,
stages the complete vendor resource tree, and records a bounded receipt. The
native app repeats the executable digest and version checks before launch and
fails with `local_agent_binary_not_bundled`, `_digest_mismatch`, or
`_version_mismatch` instead of falling back to `PATH`.

Local workspaces are still explicit. In Settings → Device, bind a local folder
as `read_write` and enable the local-agent/command boundary. `Always ask` and
`Approve for me` keep Codex in workspace-write sandboxing; `Full access` is the
user's explicit request for danger-full-access and no per-action prompt. The
local posture is a separate OS-keychain value, defaults to `Always ask`, resets
when the device session is cleared, and requires a native confirmation before
`Full access` is stored. A cloud `Full access` selection never carries into the
desktop-local agent. Remote device command leases remain a different signed
argv-only path and continue to reject shell strings.

Desktop update trust is fixed at Worker build time. Release builds that should
offer updates must set both:

```env
BOLTRIG_UPDATER_ENDPOINT=https://<release-host>/<manifest-path>
BOLTRIG_UPDATER_PUBLIC_KEY=<complete Tauri updater public key>
```

The endpoint must be HTTPS and may use Tauri's `{{target}}`, `{{arch}}`, and
`{{current_version}}` manifest placeholders. The public-key value is the
complete Tauri updater public key, not a path to a mutable file. These values
are compiled into the desktop binary; they are never accepted from the
webview. A build without either value remains usable but Settings truthfully
reports desktop updates as unavailable.

`apps/worker/src-tauri/tauri.conf.json` enables
`bundle.createUpdaterArtifacts`, so the protected desktop release job must
provide `TAURI_SIGNING_PRIVATE_KEY` and, when applicable,
`TAURI_SIGNING_PRIVATE_KEY_PASSWORD` only within that job. Never commit,
compile, or copy the updater private key into a Worker package. Publish the
generated installer, signature, and update manifest atomically to the compiled
release endpoint.

Before enabling desktop-primary distribution, exercise check, download,
signature verification, installation, and restart using packaged macOS,
Windows, and Linux builds. Verify an invalid signature, changed version,
missing manifest, offline endpoint, and unconfigured build all fail closed
without replacing the running application.

## Worker OAuth return registration

The desktop bundle statically registers
`boltrig-worker://oauth/callback`. On Linux, and for Windows development builds,
Worker also asks Tauri to register the configured scheme at runtime. A
registration failure is shown as unavailable rather than inferred ready.
Packaged macOS builds must be installed before testing their static scheme
registration.

This scheme is not a provider callback. A future certified provider must first
return its authorization code to a reviewed kernel-owned HTTPS callback. Only
after server-side code exchange may the kernel redirect an opaque state plus
opaque result handle (or `access_denied`) to Worker. The native parser rejects
provider authorization codes, access tokens, refresh tokens and identity tokens
in the custom-scheme URL. Until that kernel exchange and a provider-specific
authorization-origin allowlist exist, Worker opens no provider authorization
page and reports provider exchange unavailable.

## Checklist

- [ ] Protected release selected; downloaded `boltrig-images.env` passes
      `make release-validate` and contains four `@sha256` image refs; both fleet
      worker services resolve to the one signed fleet digest
- [ ] every image signature, CycloneDX attestation and SLSA provenance verifies
      against `wlilley93/boltrig/.github/workflows/release.yml`, the selected tag,
      and the checked-out commit
- [ ] `make release-up` completed with the secure overlay (TLS terminator in
      front; kernel/UI/local-model host ports closed; no first-party rebuilds)
- [ ] `DATABASE_URL` has `sslmode=require`
- [ ] `PGDATA_HOST` on an encrypted device; backups on encrypted media
- [ ] a complete encrypted recovery set covers both application and Hatchet
      databases plus Hatchet config, Knowledge, libraries and manifest; its
      off-box completion marker and a disposable full restore are verified
- [ ] a fresh cluster created the separate Hatchet database through the packaged
      first-boot hook, or an existing cluster was checked/created explicitly
- [ ] `CA_BUNDLE` set and the bundle mounted; proxy env set if required
- [ ] `BOLTRIG_HERDR_HOME`, `BOLTRIG_OPENCODE_HOME`,
      `BOLTRIG_FLEET_BROWSER_CLI_HOME`, and
      `BOLTRIG_HATCHET_BROWSER_CLI_HOME` set to stack-owned roots; the two
      browser roots are different
- [ ] on Ubuntu 24.04+, the named `boltrig-codex` AppArmor profile is loaded for
      kernel, Fleet and Hatchet, and the real sandbox engagement proof passes
- [ ] all three first-party runtime services execute as uid 10001; imported
      named volumes have verified ownership and no personal profile is mounted
- [ ] Hatchet database, `hatchet_config`, and worker-token identity belong to
      the same recovery point; durable worker registration is healthy
- [ ] `make public-product-validate` confirms BYO Bifrost and only Familiar +
      Jarvis ship; any private development route remains deployment-local
- [ ] Herdr/OpenCode CLI versions and hashes reviewed before image rebuild
- [ ] `make release-validate` executed `herdr`, `opencode`, and `browser-use`
      from the verified candidate-image context and production doctor reported
      zero failures there; no host CLI path was substituted
- [ ] `/readyz` is 200 only after the fleet worker has published fresh live-tool
      evidence; stopping the worker or Chromium makes it return 503 after TTL
- [ ] when first-party password recovery is required, a reviewed notifier and
      bounded readiness probe are injected,
      `BOLTRIG_REQUIRE_PASSWORD_RESET_DELIVERY=1`, and real staging
      delivery/bounce/provider-receipt acceptance is recorded
- [ ] real OIDC configured (`OIDC_*`), `BOLTRIG_DEV_AUTH` unset (SEC-01)
- [ ] verified off-box database snapshot and restore rehearsal completed before
      `make migrate`; current Alembic revision recorded
- [ ] desktop updater endpoint/public key compiled into release builds, signing
      private key confined to the protected build job, and packaged
      cross-platform update acceptance completed
- [ ] packaged desktop scheme registration tested on macOS, Windows and Linux;
      no provider OAuth is advertised until its kernel callback/exchange and
      authorization-origin allowlist pass certification
