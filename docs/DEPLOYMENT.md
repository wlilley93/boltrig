# Secure deployment

The same images run everywhere; security is configuration, not a rebuild (P7).
This covers encryption in transit (SEC-10), encryption at rest (SEC-11), and the
corporate proxy + internal CA wiring (US-DEP-04).

## Release identity and update channels

One protected semantic tag is the release identity, but each installed surface
consumes it differently. Do not make all three follow a mutable branch or a
generic `latest` image tag.

| Surface | Update source | Promotion rule | Rollback |
| --- | --- | --- | --- |
| `dev.boltrig.ai` | a reviewed commit on the development branch | explicit atomic static-directory swap on Jellytot | restore the previous `dist.rollback-*` directory |
| `app.boltrig.ai` and other hosted Worker stacks | the `ui@sha256` entry in a protected release's `boltrig-images.env` | exact semantic-tag checkout, `release-validate`, then `release-up` | previous protected tag plus its four digest refs |
| already-installed signed desktop apps | `latest.json` attached to the latest stable **full** GitHub release | Tauri verifies the selected platform package with the public key compiled into the app | install a previous signed package explicitly; the updater never follows an image or branch |
| pinned server products such as Opbox | operator-selected protected release tag and that release's `boltrig-images.env` | explicit maintenance-window validation and restart | retain and reapply the previous tag/environment pair |

The release workflow builds all four server images for both release modes. A
stable `full` release additionally builds and signs macOS, Linux and Windows
desktop packages, creates the Tauri static update manifest from those exact
packages, uploads everything while the GitHub release is still a draft, and
then marks that release Latest. A `core` release and any prerelease are
explicitly **not** Latest, so neither can displace the last complete desktop
update manifest.

An app built without an updater endpoint/public key, including the existing
ad-hoc development package, cannot acquire that trust configuration from the
web or from a later unsigned response. It needs one manual reinstall from a
protected full release; signed releases after that update normally in place.

Pinned server products deliberately have no automatic “follow latest” mode.
Automation may notify an operator that a newer protected tag exists, but it must
not download or start it without selecting the tag, verifying the image/SBOM/
provenance set, and retaining the previous tag as rollback. This keeps an Opbox
deployment reproducible even when `dev.boltrig.ai` advances several times a day.

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

### Public hostnames

`boltrig.ai` is the product domain as of 2026-08-18. The routing lives in the
host Caddy on `jellytot-prod` at `/etc/caddy/Caddyfile`, which is **not in this
repository**, so the table is restated here and `scripts/cf-wire-boltrig.py`
carries the same list for the DNS and tunnel side.

| Hostname | Serves |
| --- | --- |
| `boltrig.ai`, `www.boltrig.ai` | the marketing site from `/srv/boltrig-marketing` |
| `app.boltrig.ai` | Worker on `127.0.0.1:8622`, with Operator on `:8620` as a declared fallback |
| `dev.boltrig.ai` | the preview: `:1420` static, `:8629` for `/v1`, `/healthz`, `/readyz` |
| `boltrig.io`, `www.boltrig.io`, `boltrig.dev`, `www.boltrig.dev` | 301 to `https://boltrig.ai{uri}` |
| `app.boltrig.io` | 301 to `https://app.boltrig.ai{uri}` |
| `dev.boltrig.io` | 301 to `https://dev.boltrig.ai{uri}`, **except** the API legs |

A REDIRECT SOURCE STILL NEEDS ITS DNS RECORD AND ITS INGRESS RULE. Caddy issues
the 301 on the box, so the request has to arrive before it can be redirected;
removing a retired hostname from `cf-wire-boltrig.py` breaks it rather than
retiring it.

`dev.boltrig.io` keeps `/v1`, `/healthz` and `/readyz` proxied rather than
redirected, and that exception is load-bearing. `VITE_API_BASE` is baked into
the bundle as an absolute URL, and `dist` deliberately keeps the previous
release's chunks alongside the current one so an open tab survives a release.
Those older chunks call `https://dev.boltrig.io/v1`. Redirecting the API would
break exactly the tabs that compatibility copy protects: a browser does not
follow a redirect on a CORS preflight, and several clients downgrade a
redirected POST to GET. The exception can go once

```bash
grep -rl dev.boltrig.io /home/jellytot/boltrig-dev/dist/assets/
```

returns nothing. Until then the kernel names both hostnames in
`BOLTRIG_ALLOWED_HOSTS`, so the leg is allow-listed rather than smuggled through
on a `Host` header rewritten to a value the kernel already trusts.

**`docker restart` does not reload an `--env-file`.** It replays the container's
baked environment; the file is read once, at create time. Editing
`/home/jellytot/boltrig-dev/backend.env` and restarting leaves the old values in
place while `/healthz` goes green, so the change looks like it silently did
nothing. Recreate the container instead.

### Jellytot development preview

`dev.boltrig.ai` is a development deployment on `jellytot-prod`; it is not a
production release path. From the development Mac, Jellytot is reached through
the existing cable relay:

```bash
ssh beelink-cable "ssh jellytot-prod '<command>'"
```

The preview unit is `boltrig-dev-preview.service`, serving
`/home/jellytot/boltrig-dev/dist` on `127.0.0.1:1420` behind Caddy. Do not move
this workload to `beelink-prod`, CV/opbox, or a personal Ollama/M1 host. The
public-product gate must remain green: provider configuration is BYO Bifrost,
and every character the stock path registers is a bundle in this repository
declaring `ships: true`. That is now four -- Familiar, Jarvis, Ultron and
Colossus. The gate no longer holds a hardcoded list, because the hardcoded one
went stale twice without anyone noticing and a gate that is always red protects
nothing; what it refuses is a registration with no shipping bundle behind it,
which is the leak the list existed to catch.

Build locally, transfer into a new timestamped `dist.candidate-*` directory,
and compare a deterministic relative-path/content digest before promotion. A
macOS tar stream can contain AppleDouble `._*` metadata; remove those files
from the candidate before comparing or serving it. Keep the candidate and live
directory distinct; never copy candidate files over the serving tree.

An atomic directory swap must not delete the immutable hashed assets used by
already-open browser sessions. After the pristine candidate digest matches the
local build, copy only absent files from the live `dist/assets` directory into
the candidate with no-overwrite semantics (for example, GNU
`cp --update=none` or `rsync --ignore-existing`). Never copy
`index.html`, never overwrite a candidate asset, and record a second digest for
the final compatibility tree. Keep at least the immediately preceding release's
hashed assets for the active-session grace period. Hosted/CDN releases follow
the same ordering: publish new immutable assets first, publish the new index
last, and defer old-asset deletion. Otherwise a user crossing the release while
finishing onboarding or changing route can receive a lazy-chunk 404 and a blank
screen even though a refresh succeeds.

Atomically rename the current directory to a unique `dist.rollback-*`, rename
the verified compatibility candidate to `dist`, and restart with `sudo -n
systemctl restart boltrig-dev-preview.service`. An unprivileged `systemctl`
command cannot restart this system unit. Allow the preview process up to ten
seconds to bind its port before deciding it failed; an immediate probe can
produce a false negative. On a real failure, stop the unit, move the failed
candidate aside, restore the rollback directory, and restart.

Acceptance requires all three public endpoints to return HTTP 200:

```text
https://dev.boltrig.ai/
https://dev.boltrig.ai/healthz
https://dev.boltrig.ai/readyz
```

Keep the static rollback and the separately named backend rollback until the
authenticated UI smoke is complete. A static-only deploy does not authorize a
backend, database, production, or CV/opbox change.

The Worker also carries a one-shot dynamic-import recovery boundary. It reloads
once per failed chunk fingerprint and then renders an explicit Reload action;
that is a last-resort guard, not a substitute for retaining immutable assets.

When an explicitly authorised development rollout also replaces the kernel or
Hatchet task-worker source, validate the candidate with the pinned images before
promotion and take a compressed database dump before applying migrations. Keep
the stopped kernel container, the previous backend/config/env directories, and
that dump under the same deployment timestamp until the authenticated smoke is
complete. `manifest.yaml` is not a secret and must remain readable by the
images' unprivileged `boltrig` user (normally mode `0644` on a root-owned or
operator-owned host path); mode `0600` owned by the host operator makes the
bind-mounted file unreadable and puts the kernel into a restart loop. Secrets
remain in the mode-`0600` env file. Recreate or restart `hatchet-worker` after
promoting the manifest: its entrypoint decides whether to start declared local
helpers before the Python task listener begins, so changing the bind-mounted
file underneath an already-running worker is insufficient. Acceptance includes
the worker's own `127.0.0.1:8001/health` receipt in addition to the three public
endpoints above.

A bind-mounted source update does not install new Python packages. If the
current lockfile adds a runtime dependency, a container restart can therefore
look healthy until the first request reaches the new import. Rebuild the normal
development images, or derive a temporary development overlay from each exact
currently deployed image digest with `deploy/dev-runtime-overlay.Dockerfile`.
The overlay must install the complete current `requirements-lock.txt` with
`--require-hashes`; do not `pip install` an individual package into a running
container. Record both base digests and the derived image IDs, validate the
candidate source against those images, and retain the old stopped containers for
rollback. This overlay is never a production release artifact: production uses
the full signed kernel and fleet Dockerfiles.

#### Hosted-development BYO model hygiene

A shared preview must not inherit an operator's personal provider credential.
For the kernel service, omit legacy `OPENAI_API_KEY` and
`ANTHROPIC_API_KEY` entries rather than leaving blank assignments. Recreate the
container after changing its env file: Docker stores the environment in
container metadata, so restarting an existing container does not remove the old
value. Inspect stopped rollback containers too and remove any that retain a
provider key. Do not restart or rewrite Bifrost, database, Hatchet, CV/opbox or
personal model-host containers while doing this cleanup.

When the preview depends on Bifrost, set:

```env
BOLTRIG_MODEL_GATEWAY_HEALTH=1
```

Require `/readyz` to report `model_gateway=ok`; a configured-but-unchecked
gateway is not acceptance. An empty Bifrost `/v1/models` catalogue is a valid,
truthful pre-onboarding state and cloud sends must remain unavailable.

The organisation-level `allow_own_ai_keys` flag is changed only through the
authenticated, approval-gated `PATCH /v1/orgs/current` path. It enables the
sealed org/workspace/user provider-native hierarchy in **Account → Access**;
it does not expose a provider key to the browser or an agent. Per-user
onboarding now completes the server-owned Bifrost lifecycle: the kernel consumes
the sealed proposal, reconciles a tenant/scope-bound provider key, creates an
exact-model virtual key, and retains only sealed references. Trusted Codex calls
receive the virtual key at the model-proxy boundary; the browser, cell and agent
never receive either the provider credential or that virtual key.

The onboarding proposal is deliberately two-step. The first Continue submits
the sealed proposal; the second explicitly approves/applies it through the
ordinary HITL policy. A pending or expired proposal is not configured state.
Expired proposals cannot be recovered because their plaintext key was never
stored, so the user must re-enter the provider key. Replacing a key for the same
scope updates the stable Bifrost provider-key binding; changing provider/model
rotates the virtual key. Removal revokes the Bifrost virtual key and provider
key before deleting the local sealed configuration and fails closed if gateway
revocation cannot be confirmed.

Acceptance for a BYO-model onboarding deployment is therefore all of:

1. `GET /v1/ai-keys` reports the intended exact model with
   `gateway_ready=true` (never inspect or log secret material);
2. `GET /v1/chat/model-choices` reports that exact model as the personal
   default, with `default_source=personal`;
3. the model trigger names the exact model, not `Automatic`, before a send;
4. a hard browser refresh preserves the same exact model and leaves Send
   available; and
5. the resulting trusted-runtime/model-proxy receipt binds the same model.

`Automatic` is reserved for a runnable platform default. Do not copy an
operator's personal root key into the kernel or a shared Bifrost configuration
to make this smoke pass.

#### Voice onboarding and hosted speech services

The optional Voice onboarding step uses the same write-only integration-secret
boundary as other governed connections. The browser submits provider-declared
fields once and clears secret inputs before awaiting the response; keys are not
returned to the Worker, stored in browser state, or exposed to an agent. The
shipped hosted choices are xAI, ElevenLabs, Deepgram, OpenAI Audio, Fish Audio,
and an OpenAI-compatible speech endpoint. A user may skip this step without
blocking onboarding and add voice later.

Register only the adapters that the deployment can actually reach. Official
provider adapters use their fixed HTTPS origins. A custom/self-hosted speech
connection must use a canonical HTTPS origin that is reachable from the Boltrig
server and admitted by the ordinary network allowlist; it is not a browser-to-
LAN tunnel. Private on-device Pocket/Whisper-style services belong behind the
desktop device boundary rather than in a hosted-server connection. Connection
setup is not routing authority: changing the tenant-wide STT/TTS or realtime
binding remains a separate governed operation, so onboarding must not claim a
saved key is already the active voice route.

For a voice-enabled deployment, verify the catalogue and connection projection
without inspecting secret material, then exercise one bounded transcription and
one bounded synthesis call through the kernel. A degraded initial adapter health
is expected before the first authenticated provider call and must not be
presented as a successful provider probe.

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
root, or a mounted personal profile. One `browser-executor` service owns the
deployment's Browser Use state and Chromium process. Kernel, Fleet, and Hatchet
reach it only through `/run/boltrig-browser/browser.sock`; the socket volume is
read-only everywhere except the executor, and the executor publishes no port.
The executor is the sole member of the `browser-egress` network. Chromium is
forced through a loopback proxy that re-applies the public-address/domain policy
after redirects and page clicks, connects to the single vetted IP, disables
non-proxied WebRTC UDP and QUIC, and accepts only ports 80/443. Do not add the
executor to `default`, bypass the proxy, or widen its ports to reach an internal
application; use a reviewed public endpoint or a purpose-built kernel adapter.
Do not add browser-profile mounts back to the callers or point `BU_CDP_URL` at a
desktop browser. If an image build or headless server asks a human to enable
`chrome://inspect` or approve remote debugging, reject that image: the CLI has
fallen off the stack-owned browser path.

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

## Browser CLI stack state

Browser Use is the only separately shipped stack tool. The fleet image installs
its hash-locked CLI and production uses separate service-owned roots for the
ordinary and durable workers, never an operator's personal browser profile:

```env
BOLTRIG_FLEET_BROWSER_CLI_HOME=/var/lib/boltrig/browser-cli/fleet-worker
BOLTRIG_HATCHET_BROWSER_CLI_HOME=/var/lib/boltrig/browser-cli/hatchet-worker
```

The base compose file backs these with named volumes. The first-party images
create the root, home, config, data, and state directories as the unprivileged
`boltrig` user so fresh named volumes start writable by the service, including a
stack-owned cache directory. Do not bind-mount personal browser profile state
into the stack. Use `make release-validate` before production cutover. It runs
doctor against the operator configuration inside the verified fleet-image
context, where the stack-owned executable exists. A bare
host-side `boltrig doctor --production` remains a useful diagnostic, but its CLI
checks describe that host and must not be used as release-image evidence.

To upgrade Browser Use, update `deploy/browser-cli-requirements.in` and regenerate
`deploy/browser-cli-requirements.txt` for Browser Use CLI with
`uv pip compile deploy/browser-cli-requirements.in --overrides deploy/browser-cli-overrides.txt --generate-hashes --python-platform linux -o deploy/browser-cli-requirements.txt`.
Rebuild the images after any change. Production doctor still requires
`browser-use` to resolve from the deployed stack path before browser verbs are
treated as ready. Do not set `BOLTRIG_BROWSER_CLI_BIN` to a binary under a
developer home directory, and do not copy binaries or profiles from a developer
workstation into production.

Browser CLI child processes do not inherit the service environment wholesale.
They receive stack-owned `HOME`/XDG paths and a small runtime allowlist (`PATH`,
proxy, locale, CA-bundle settings). Only explicit scoped handoffs such as the
per-run `BU_NAME` are added. Browser Use cloud/profile env is disabled by default:

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

`GET /v1/platform/status` includes a redacted Browser CLI stack posture. It
reports image-shipped install mode, stack-owned state posture, and which
container owns the runtime, but it never returns actual state roots,
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
`control.*` registration, safe Browser CLI stack posture, and a fresh
HMAC-authenticated Redis receipt from the fleet worker's local Browser Use and
loopback Chromium CDP probes. Receipt keys are deployment-scoped and the signing key is
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

Password-reset delivery remains fail-closed unless the standard ASGI process is
given a complete server-side MailerSend configuration:

```env
BOLTRIG_PASSWORD_RESET_PROVIDER=mailersend
BOLTRIG_MAILERSEND_API_KEY=<secret-store value>
BOLTRIG_PASSWORD_RESET_FROM_EMAIL=noreply@<verified-domain>
BOLTRIG_PASSWORD_RESET_FROM_NAME=Boltrig
BOLTRIG_PASSWORD_RESET_PUBLIC_ORIGIN=https://<worker-origin>
BOLTRIG_REQUIRE_PASSWORD_RESET_DELIVERY=1
```

The adapter posts only to MailerSend's fixed HTTPS API, refuses redirects and
environment proxies, disables open/click/content tracking, and bounds the whole
request to five seconds. Its readiness probe uses MailerSend's read-only
`/v1/api-quota` endpoint and consumes no mail quota. An embedding deployment may
instead inject another reviewed async notifier and bounded probe through
`build_app(password_reset_notifier=...,
password_reset_readiness_probe=...)`. Readiness establishes only adapter/token
posture. The authenticated Operate projection likewise reports a bounded,
recipient-free notifier attempt—not a provider receipt or proof of inbox
delivery. Keep the API key in the deployment secret store and validate real
delivery, suppression/bounce handling and provider receipts in staging before
cutover.

## Signed Worker desktop updates

### Account-first desktop connection and download

The production account session is the only user-facing entry flow. A user signs
in to the hosted Worker, downloads the signed desktop package from the
authenticated Settings surface, and signs in to the same Boltrig origin when
the app starts. Do not publish instructions that ask users to copy a device
enrollment code or paste a browser handoff bundle.

For a full release, configure the protected release-environment variable:

```env
BOLTRIG_DESKTOP_DOWNLOAD_URL=https://<reviewed-release-page>
```

The candidate build accepts this only for the `ui` image, requires an
absolute HTTPS URL without embedded credentials, and compiles it into that
authenticated UI. A `core` release deliberately bakes an empty value because it
ships no desktop packages. Local Compose development can use the same variable;
an absent or unsafe value shows “not published” instead of inventing a link.

After desktop account authentication, Worker automatically uses the existing
authenticated enrollment-start endpoint and consumes the bootstrap inside the
same signed app. The short-lived bootstrap is an implementation detail, never a
user-transferable secret. The resulting private key, rotating device session,
lease verifier and opaque folder bindings stay in the OS keychain. If the app
finds a key that is unreadable or is not among the signed-in account's trusted
computers, it refuses automatic replacement and asks before removing local
credentials. This device identity remains necessary for per-computer
revocation, signed exact-action leases, and native paths that must never enter a
browser cookie or server response.

The packaged UI is cross-origin from the HTTPS kernel. Session-auth deployments
must explicitly add the platform origins they ship to `BOLTRIG_CORS_ORIGINS`:

```env
BOLTRIG_CORS_ORIGINS=https://app.example.com,tauri://localhost,https://tauri.localhost
```

macOS/Linux use `tauri://localhost`; Windows is pinned to
`https://tauri.localhost` by Tauri's `useHttpsScheme`. Never add `null`, `*`, or
a plaintext Windows desktop origin. Only these built-in origins, when also
present in the explicit CORS list, receive the cross-site
`SameSite=None; Secure` session cookie. The signed desktop performs login,
second-factor completion, refresh and logout through a fixed native bridge
pinned at compile time to `BOLTRIG_DESKTOP_API_ORIGIN`. That bridge validates
the two expected cookies and installs them directly into the webview cookie
store; it never returns the httpOnly session secret to JavaScript.

Every desktop build must set `VITE_API_BASE` and
`BOLTRIG_DESKTOP_API_ORIGIN` to the same canonical origin. Setting only the
Vite value produces a UI that renders the account forms but whose native HTTP
transport cannot contact the server. The checked-in Tauri pre-build command
refuses that split configuration, and the Rust build script tracks the native
origin so Cargo cannot reuse a binary compiled for an older or empty value.

Because
WKWebView also suppresses third-party cookies on later cross-origin requests,
the typed web SDK uses a bounded native transport in the packaged desktop.
That transport accepts only `/v1` paths at the compile-time origin, adds the
native-held cookie and CSRF value, strips `Set-Cookie` from the response
projection, rejects redirects and bounds request/response sizes and total
response time.
The hosted browser continues to use ordinary same-origin Fetch and
`SameSite=Strict` cookies.

Connecting the computer does not grant file, Bash, camera or background access.
Users must still choose each local folder and enable its capabilities in
Settings, and ordinary exact-action approval rules continue to apply. Provider,
Bifrost, integration and organisation credentials remain kernel-side; the
desktop download or login flow must never accept them.

### Browser agent versus desktop-local agent

Browser Chat is a cloud agent: it calls the authenticated Boltrig kernel, and
the hosted server-cell admission in `docs/CODEX-PRODUCTION-ADMISSION.md` must be
open. The signed Tauri Chat surface is a local agent: it starts a private Codex
App Server over stdio and executes approved file/Bash work on the user's own
computer. There is no silent fallback between them.

“Local” describes execution and data ownership, not necessarily model
inference. The bundled Codex process uses that user's own Codex authentication
and may contact the Codex service for reasoning; Bash, approved filesystem
access, thread persistence and process ownership remain on the computer. The
desktop child receives an allowlisted environment and never inherits Boltrig
provider credentials, gateway keys, GitHub tokens or SSH agent sockets. Do not
describe this posture as an offline model, and do not make a personal Ollama or
operator model host a release default.

Development builds may resolve `BOLTRIG_LOCAL_CODEX_BIN` (an absolute file) or
`codex` from `PATH`; the UI labels that source `development`. Release builds do
not trust a host install. The protected desktop matrix runs
`scripts/stage_desktop_codex.py`, which downloads the official platform package
for Codex 0.144.3, verifies the exact archive and executable SHA-256 values,
stages the complete vendor resource tree, and records a bounded receipt. The
native app repeats the executable digest and version checks before launch and
fails with `local_agent_binary_not_bundled`, `_digest_mismatch`, or
`_version_mismatch` instead of falling back to `PATH`.

An ad-hoc debug `.app` can exercise local development but is not desktop
release evidence. Release acceptance requires the protected platform build,
publisher signature/notarization, updater signature, exact bundled Codex
receipt, an authenticated local turn that executes a harmless command in the
selected workspace, interrupt/switch cleanup, and restart/resume of the same
local thread. Record the model/network leg separately from the local
command/filesystem leg so a successful cloud inference is never reported as
proof that execution happened on the server.

Several desktop surfaces legitimately inspect the same enrolled-computer
credential during startup. They must share the native process cache rather
than reading `device-session` independently: otherwise an ad-hoc signature
change produces repeated macOS Keychain prompts. The first read is
single-flight, successful saves/removals update the cache, and a denied read is
remembered until restart. Never work around this by exporting the Keychain
secret to JavaScript or a plaintext local file. A stable publisher signature
remains required for normal upgrade continuity.

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
offer updates compile both:

```env
BOLTRIG_UPDATER_ENDPOINT=https://github.com/wlilley93/boltrig/releases/latest/download/latest.json
BOLTRIG_UPDATER_PUBLIC_KEY=<complete Tauri updater public key>
```

The protected workflow derives the endpoint from the canonical repository; it
is not an operator-provided URL. `scripts/build_desktop_update_manifest.py`
requires every generated updater package and signature, binds each URL to the
exact semantic tag, and merges all three platform fragments into `latest.json`.
The public-key value remains protected release configuration and is the complete
Tauri updater public key, not a path to a mutable file. Both values are compiled
into the desktop binary and are never accepted from the webview. A build without
either value remains usable but Settings truthfully reports desktop updates as
unavailable.

`apps/worker/src-tauri/tauri.conf.json` enables
`bundle.createUpdaterArtifacts`, so the protected desktop release job must
provide `TAURI_SIGNING_PRIVATE_KEY` and, when applicable,
`TAURI_SIGNING_PRIVATE_KEY_PASSWORD` only within that job. Never commit,
compile, or copy the updater private key into a Worker package. Publish the
generated installer, signature, platform fragment, and merged update manifest
atomically while the release is still a draft. The package signature, rather
than the mutable `latest.json` pointer, is the executable trust boundary.

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
- [ ] `BOLTRIG_FLEET_BROWSER_CLI_HOME` and
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
- [ ] Browser Use lock and hashes reviewed before image rebuild
- [ ] `make release-validate` executed `browser-use`
      from the verified candidate-image context and production doctor reported
      zero failures there; no host CLI path was substituted
- [ ] `/readyz` is 200 only after the fleet worker has published fresh live-tool
      evidence; stopping the worker or Chromium makes it return 503 after TTL
- [ ] when first-party password recovery is required, the complete server-only
      MailerSend configuration (or another reviewed notifier and bounded probe)
      is composed,
      `BOLTRIG_REQUIRE_PASSWORD_RESET_DELIVERY=1`, and real staging
      delivery/bounce/provider-receipt acceptance is recorded
- [ ] real OIDC configured (`OIDC_*`), `BOLTRIG_DEV_AUTH` unset (SEC-01)
- [ ] verified off-box database snapshot and restore rehearsal completed before
      `make migrate`; current Alembic revision recorded
- [ ] desktop updater endpoint/public key compiled into release builds, signing
      private key confined to the protected build job, and packaged
      cross-platform update acceptance completed
- [ ] full release has a reviewed `BOLTRIG_DESKTOP_DOWNLOAD_URL`; authenticated
      browser Settings opens the signed release page, while core/invalid/HTTP
      configurations show no download link
- [ ] packaged desktop scheme registration tested on macOS, Windows and Linux;
      no provider OAuth is advertised until its kernel callback/exchange and
      authorization-origin allowlist pass certification
