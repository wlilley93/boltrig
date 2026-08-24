---
area: 19 Deployment topology, the release train and recovery
id-block: BT-REQ-1900 to BT-REQ-1999
referent commit: 19bcae7fa81663fe8998377c86451ba08fb16e48 (origin/main)
author-agent: spec-area-19
date: 2026-08-24
---

# SPEC-19 Deployment topology, the release train and recovery

## Search bound declared up front

Every file in this area's scope was opened and read end to end, not sampled:
`docker-compose.yml` (773 lines), `docker-compose.vm.yml` (118),
`.dockerignore` (48), `Makefile` (494), `genesis.sh` (186), the five overlays
under `deploy/` (`compose.secure.yml`, `compose.release.yml`, `compose.dev.yml`,
`compose.inprocess.yml`, `compose.opbox-link.yml`), `deploy/Caddyfile.example`,
`deploy/backup.Dockerfile`, `deploy/release-doctor.Dockerfile`,
`deploy/dev-runtime-overlay.Dockerfile`, `deploy/postgres-init-hatchet.sh`,
`deploy/apparmor/boltrig-codex`, and the in-scope scripts
(`scripts/roll-release.sh`, `roll-migrate-stack.sh`, `release_asset.sh`,
`backup.sh`, `backup-loop.sh`, `backup-healthcheck.sh`, `build-wheelhouse.sh`,
`dev-up.sh`, `docker-disk-hygiene.sh`, `require_local_docker.py`). The four
in-scope documents were read in full: `docs/DEPLOYMENT.md` (1032 lines),
`docs/PROD-CUTOVER-RUNBOOK.md`, `docs/backup-restore.md`,
`docs/ARCHITECTURE-stack.md`.

Files OUTSIDE the scope were read only far enough to settle a boundary question
and are cited only for what was read: `deploy/kernel.Dockerfile` and
`deploy/fleet.Dockerfile` (structural greps plus the user and entrypoint
blocks), `apps/worker/Dockerfile` and `apps/worker/nginx.conf` (edge routing),
`scripts/kernel-entrypoint.py`, `boltrig/fleet/infrastructure/cell_privilege.py`,
`scripts/validate_release_compose.py`, `validate_release_images.py`,
`validate_release_mode.py`, `verify_recovery_set.py`, `verify-deployment.sh`,
`scripts/check_gate_coverage.py`, `scripts/check_health_claims.py`,
`boltrig/release_mode.py`, `.env.example`, `.gitignore`,
`.github/workflows/release.yml` (preflight, candidates matrix, publish
promotion), `tests/deploy/*`, `tests/security/test_round_seventeen.py`,
`tests/security/test_round_six.py` and `tests/invariants.yaml`. Nothing about
those files is claimed beyond the lines cited.

Two things this document does NOT settle, deliberately. No `docker`,
`docker compose`, `make` or `pytest` command was executed (the contract forbids
it on this host), so every claim here is a claim about the manifests and scripts
as written, never about an observed container. And the merge semantics Docker
Compose applies at `config` time were reasoned from the manifests and their
`!override` / `!reset` tags rather than measured. Where that distinction changes
a verdict it is called out inline and lands in OPEN QUESTIONS.

Absence claims each carry their own `rg` bound inline.

## 2. Purpose

This subsystem is the physical shape of a Boltrig deployment and the procedures
that move it: one Compose model of fifteen services with a hardening anchor, a
set of overlays that specialise it for dev, VM, secure and signed-release
postures, and a release train that turns a protected git tag into four
digest-pinned images an operator can validate before starting. It also owns the
recovery half, which is the only reason a deployment survives its disk: a
profile-gated backup sidecar that produces complete, checksummed, optionally
encrypted recovery sets, and a read-only verifier that refuses a partial one.
The area's whole argument is that a deploy is not finished when a container is
running, and every gate here exists because a previous roll proved that.

## 3. Boundaries

**What this area owns.**

- The Compose service topology: images, ports, volumes, networks, health probes,
  restart policy, dependency ordering, profile gating.
- The container hardening anchor `x-app-hardening` and which services merge it.
- The five overlays plus the VM overlay, and the order they layer in.
- The release train from tag to running stack: build, scan, sign, attest,
  promote, emit `boltrig-images.env`, validate, pull, start, verify.
- Backup, recovery-set verification, restore ordering and rehearsal.
- Host hygiene that keeps a deploy host able to deploy: disk pruning, the
  wheelhouse, the genesis ceremony.

**What it must not touch.** This area records the shape of the deployment; it
does not define what the kernel serves (SPEC-02), what readiness actually probes
(SPEC-12), what a manifest may say (SPEC-11), or how the Codex cell wall works
(SPEC-04). Where a compose key exists only to satisfy one of those subsystems,
this document says so and cites the consumer rather than re-deriving it.

**Forbidden by rule, and by which rule.**

- No first-party service in the signed-release model may carry a `build:` key or
  a tag-based image. Enforced at `scripts/validate_release_compose.py:84` `release service {name} still has a build definition` and
  `scripts/validate_release_compose.py:87` `release service {name} is not pinned by image digest`.
- The `channels` profile may not be active in a release model at all:
  `scripts/validate_release_compose.py:49` `release channels posture is not admitted: channel-gateway/`.
- The signed backup image may not have its script replaced by a host mount:
  `scripts/validate_release_compose.py:125` `release backup service replaces signed code with a source mount`.
- Operator backup credentials may not reach git or any build context:
  `.dockerignore:24` `deploy/rclone/` and `.dockerignore:25` `**/rclone.conf`, bound by
  `tests/deploy/test_compose_hardening.py:333` `def test_backup_credentials_are_excluded_from_git_and_image_contexts():`.

## 4. Objects and contracts

### 4.1 The service inventory

Fifteen services are declared in `docker-compose.yml`. Every one of them carries
`restart: unless-stopped`; there is no service in the base model that would fail
to come back after a host reboot. Bounded: `grep -n "restart:" docker-compose.yml`
returns exactly 15 hits and `grep -n "^  [a-z][a-z0-9-]*:" docker-compose.yml`
returns exactly 15 service keys, 2026-08-24, pinned tree. Note what
`unless-stopped` does NOT cover: a container an operator stopped by hand stays
stopped across the reboot, and the Docker daemon itself must be enabled at boot
for any of this to fire.

| service | image | published host ports | networks | profile |
| --- | --- | --- | --- | --- |
| `postgres` | pgvector pg16, tag plus digest `docker-compose.yml:44` `image: pgvector/pgvector:pg16@sha256:131dcf7ff6a900545df8e7e092c270aa8c6db2f2c818e408cb45ec21316b74e6` | none | default | - |
| `redis` | redis 7, tag plus digest `docker-compose.yml:73` `image: redis:7@sha256:b2b95679e3b46fb51864949ed25ea976fc3a6bcc00a40a1bc00d568cb2822e50` | none | default | - |
| `kernel` | `boltrig/kernel:0.1.0`, built `docker-compose.yml:95` `image: boltrig/kernel:0.1.0` | `KERNEL_PORT` default 8000, ALL interfaces `docker-compose.yml:172` `${KERNEL_PORT:-8000}:8000` | default + sandbox | - |
| `fleet-worker` | `boltrig/fleet:0.1.0`, built | none | default | - |
| `browser-executor` | the same fleet image, different command `docker-compose.yml:342` `boltrig.fleet.browser_executor` | none | browser-egress ONLY `docker-compose.yml:351` `- browser-egress` | - |
| `hatchet-worker` | the same fleet image, third command `docker-compose.yml:385` `boltrig.fleet.hatchet_worker` | none, health server on container loopback 8001 | default | - |
| `hatchet-engine` | hatchet-lite, digest-pinned `docker-compose.yml:432` `image: ghcr.io/hatchet-dev/hatchet/hatchet-lite@sha256:30ff826bdc65efc15a46df61e6d16dcc52f76cf2cf2693e848c6789e2b48718f` | loopback 7077 `docker-compose.yml:455` `127.0.0.1:${HATCHET_GRPC_PORT:-7077}:7077` and loopback 8888 `docker-compose.yml:456` `127.0.0.1:${HATCHET_API_PORT:-8888}:8888` | default | - |
| `hatchet-dashboard` | hatchet-dashboard, digest-pinned `docker-compose.yml:468` `image: ghcr.io/hatchet-dev/hatchet/hatchet-dashboard@sha256:326774d08b1ce9123482cdb0ff24a4c0eb54b112d27207789dffb6f82d2667e9` | loopback 8889 `docker-compose.yml:475` `127.0.0.1:${HATCHET_DASHBOARD_PORT:-8889}:80` | default | - |
| `ui` | `boltrig/ui:0.1.0`, built from the Worker Dockerfile `docker-compose.yml:486` `image: boltrig/ui:0.1.0` | `WORKER_PORT` default 8082, ALL interfaces `docker-compose.yml:492` `${WORKER_PORT:-8082}:8080` | default + sandbox | - |
| `bifrost` | maximhq bifrost, digest-pinned `docker-compose.yml:519` `image: maximhq/bifrost@sha256:c4de3a1d6bd2f9b8b0b8f508deaaf0337a793603d2b84b61138cdb35f94a4318` | loopback 8081 `docker-compose.yml:527` `127.0.0.1:${BIFROST_PORT:-8081}:8080` | default + sandbox | gateway `docker-compose.yml:517` `profiles: [` |
| `local-model` | vllm-openai, tag plus digest `docker-compose.yml:539` `image: vllm/vllm-openai:v0.24.0-ubuntu2404@sha256:bfdefe75b5c3fb83f4f0fcaae8f39fac87941cbadb05cd2203f44a1689236c71` | loopback 8001 `docker-compose.yml:552` `127.0.0.1:${LOCAL_MODEL_PORT:-8001}:8000` | default + sandbox | local `docker-compose.yml:537` `profiles: [` |
| `channel-gateway` | `boltrig/channel-gateway:0.1.0`, built | none, exposes 8091 `docker-compose.yml:608` `8091` | sandbox ONLY `docker-compose.yml:586` `- sandbox` | channels |
| `signal-cli` | signal-cli-rest-api, tag plus digest `docker-compose.yml:638` `image: bbernhard/signal-cli-rest-api:0.99@sha256:96578363477d97cb1d8da303791b2ad686b374a255fce4d78c7c6f00ef56cba8` | none, exposes 8080 | sandbox ONLY | channels |
| `whatsapp-bridge` | the first-party bridge image `docker-compose.yml:672` `image: boltrig/channel-gateway-whatsapp-bridge:1.0.0` | none, exposes 3000 | sandbox ONLY | channels |
| `backup` | built from the backup Dockerfile | none | default | backup `docker-compose.yml:709` `profiles: [` |

Four profiles gate six services out of a bare `docker compose up -d`:
`gateway` (bifrost), `local` (local-model), `backup` (backup) and `channels`
(channel-gateway, signal-cli, whatsapp-bridge).

Three services share ONE built image, `boltrig/fleet:0.1.0`, distinguished only
by command: `fleet-worker` (the delegation pump, `docker-compose.yml:230` `boltrig.api.worker`),
`browser-executor` (the sole Chromium owner) and `hatchet-worker` (the durable
task listener). This is load-bearing for the release train, which pins all three
to a single fleet digest.

### 4.2 The hardening anchor

`x-app-hardening` `docker-compose.yml:27` `x-app-hardening: &app-hardening` is a YAML anchor merged with `<<:`
into six services. It sets six properties: a read-only rootfs
`docker-compose.yml:28` `read_only: true`, a writable tmpfs `docker-compose.yml:29` `tmpfs:`, all
capabilities dropped `docker-compose.yml:31` `cap_drop:`, no-new-privileges
`docker-compose.yml:34` `no-new-privileges:true`, a pids limit `docker-compose.yml:35` `pids_limit: 512` and a memory
limit `docker-compose.yml:36` `mem_limit: 1g`.

**Merged into six services:** kernel (`docker-compose.yml:97` `<<: *app-hardening`), fleet-worker
(`docker-compose.yml:229` `<<: *app-hardening`), browser-executor (`docker-compose.yml:341` `<<: *app-hardening`),
hatchet-worker (`docker-compose.yml:384` `<<: *app-hardening`), channel-gateway
(`docker-compose.yml:587` `<<: *app-hardening`) and whatsapp-bridge (`docker-compose.yml:668` `<<: *app-hardening`).

**Not merged, nine services:** postgres, redis, hatchet-engine,
hatchet-dashboard, ui, bifrost, local-model, signal-cli, backup. Seven of the
nine are third-party images that need a writable rootfs or data directory. The
compose header states the intent as covering the first-party app containers
`docker-compose.yml:24` `# read-only, drop all Linux capabilities, forbid privilege escalation, and are`, and signal-cli says so for itself
`docker-compose.yml:633` `# Third-party image, so the first-party hardening anchor does not apply;`. No comparable statement exists for `ui` or `backup`;
the `ui` image instead drops to the nginx user in its own Dockerfile
(`apps/worker/Dockerfile:63` `USER nginx`) and `backup` runs as root
(`deploy/backup.Dockerfile:57` `USER root`) because the dump, encryption and copy tools all
write into the backups directory.

**Per-service overrides.** An explicit key beats the merge key, so a service that
restates its tmpfs list replaces the anchor's single entry rather than extending
it.

- `kernel` restates tmpfs with five entries: one for temporary files, the shared
  0711 cell root `docker-compose.yml:142` `- /var/lib/boltrig/codex-cells:mode=0711,uid=10001,gid=10001,noexec,nosuid,nodev` and four 0700 per-slot mounts at uids
  20001 to 20004, the first being `docker-compose.yml:150` `- /var/lib/boltrig/codex-cells/slot-0:mode=0700,uid=20001,gid=20001,noexec,nosuid,nodev`.
- `kernel` sets its own user `docker-compose.yml:119` `user:` and re-adds two
  capabilities after all are dropped `docker-compose.yml:120` `cap_add:`: SETUID and
  SETGID.
- `fleet-worker` and `hatchet-worker` each restate tmpfs with the same cell root:
  `docker-compose.yml:247` `- /var/lib/boltrig/codex-cells:mode=0711,uid=10001,gid=10001,noexec,nosuid,nodev` and `docker-compose.yml:390` `- /var/lib/boltrig/codex-cells:mode=0711,uid=10001,gid=10001,noexec,nosuid,nodev`. The compose comment
  records why the worker needs it, naming the exact crash
  `docker-compose.yml:235` `# CodexSandboxEngagementError: probe_root /var/lib/boltrig/codex-cells is not a directory`.

**The uid-0 kernel is not a running-as-root kernel.** The image's final user is
`boltrig` at uid 10001 (`deploy/kernel.Dockerfile:220` `RUN useradd --create-home --uid 10001 boltrig && \`), and the compose
`user` key is consumed by an entrypoint that forks a uid-0 spawner and then drops
the process that becomes the API: `scripts/kernel-entrypoint.py:83` `if os.fork() == 0:` forks the
spawner and `scripts/kernel-entrypoint.py:91` `drop_privileges(API_UID, API_GID)` drops the parent, with the drop
re-reading proc rather than trusting the syscalls
(`boltrig/fleet/infrastructure/cell_privilege.py:175` `# Never trust the calls; ask the kernel what actually happened.`). So PID 1 in a running
kernel container is uvicorn at uid 10001 and a forked child holds uid 0. The
separation engages only when the capability is actually present:
`scripts/kernel-entrypoint.py:78` `if not per_cell_uid_mode_available():` takes a byte-identical passthrough exec
otherwise.

### 4.3 Networks

Three networks, all plain bridges in the base model.

- `default` `docker-compose.yml:746` `driver: bridge`, the app network. Members: postgres,
  redis, kernel, fleet-worker, hatchet-worker, hatchet-engine,
  hatchet-dashboard, ui, bifrost, local-model, backup.
- `sandbox` `docker-compose.yml:755` `driver: bridge`, the isolation network for the severed
  sidecars. Members: kernel, ui (`docker-compose.yml:490` `- sandbox`), bifrost,
  local-model, channel-gateway, signal-cli, whatsapp-bridge. Only the secure
  overlay makes it internal (`deploy/compose.secure.yml:85` `# Enforce no arbitrary egress for the Pi sidecar (SEC-48). internal: true means`); the base file
  says so in terms `docker-compose.yml:751` `# a local gateway. For production, ALWAYS use the secure overlay`.
- `browser-egress` `docker-compose.yml:760` `driver: bridge`, internet for Chromium with no
  Compose service peers. Exactly one member, and the release validator asserts
  that: `scripts/validate_release_compose.py:104` `release browser executor is not isolated on browser-egress`.

Because `browser-executor` sits on `browser-egress` only, it can reach neither
Postgres nor Redis nor the kernel. Its callers reach it exclusively over a shared
named volume carrying a Unix socket, read-write in the executor
(`docker-compose.yml:356` `- browser_executor_socket:/run/boltrig-browser`) and read-only everywhere else
(`docker-compose.yml:179` `- browser_executor_socket:/run/boltrig-browser:ro`).

### 4.4 Volumes

Eleven named volumes, declared from `docker-compose.yml:762` `volumes:` to
`docker-compose.yml:773` `hatchet_config:`.

| volume | owner (rw) | readers (ro) | what is lost with it |
| --- | --- | --- | --- |
| `pgdata` | postgres | - | all application state |
| `redis_data` | redis | - | bounded relay and counter state, append-only persisted `docker-compose.yml:78` `--appendfsync` |
| `hatchet_config` | hatchet-engine | backup, in the release overlay | the Hatchet token-signing keyset; losing it invalidates every worker token |
| `knowledge_data` | kernel, fleet-worker `docker-compose.yml:296` `- knowledge_data:/var/lib/boltrig/knowledge` | backup, in the release overlay | canonical Knowledge originals |
| `cognee_data` | kernel | - | rebuildable Cognee state |
| `browser_cli_data` | browser-executor `docker-compose.yml:345` `BOLTRIG_BROWSER_CLI_HOME: /var/lib/boltrig/browser-cli/executor` | - | browser auth and session state |
| `browser_executor_socket` | browser-executor | kernel, fleet-worker, hatchet-worker | the only path to Chromium |
| `bifrost_data` | bifrost | - | provider routing and cached config |
| `signal_cli_data` | signal-cli `docker-compose.yml:644` `- signal_cli_data:/home/.local/share/signal-cli` | - | registered Signal account keys |
| `whatsapp_session` | whatsapp-bridge `docker-compose.yml:684` `- whatsapp_session:/data` | - | WhatsApp session credentials |
| `backup_health` | backup | kernel `docker-compose.yml:181` `- backup_health:/run/boltrig-backup-health:ro` | the freshness marker readiness and the backup-status route read |

Bind mounts from the deployment tree are a separate durability surface,
enumerated in section 6.4.

### 4.5 Health probes

| service | probe | interval, timeout, retries, start period |
| --- | --- | --- |
| postgres | the standard readiness helper `docker-compose.yml:65` `- pg_isready -U $${POSTGRES_USER:-boltrig} -d $${POSTGRES_DB:-boltrig}` | 10s, 5s, 10, 10s |
| redis | a ping | 10s, 5s, 10, none |
| kernel | readiness, not liveness `docker-compose.yml:213` `import urllib.request; urllib.request.urlopen('http://localhost:8000/readyz')` | 30s, 5s, 5, 60s `docker-compose.yml:217` `start_period: 60s` |
| fleet-worker | the signed Redis receipt read back `docker-compose.yml:320` `- python -m boltrig.api.cli fleet-health` | 60s, 10s, 3, 90s `docker-compose.yml:329` `start_period: 90s` |
| browser-executor | a Unix-socket self-probe `docker-compose.yml:360` `- python -m boltrig.fleet.browser_executor --health` | 15s, 4s, 5, 30s |
| hatchet-worker | the SDK listener heartbeat server `docker-compose.yml:421` `import urllib.request; urllib.request.urlopen('http://127.0.0.1:8001/health', timeout=3)` | 30s, 5s, 3, 30s |
| ui | a static index probe `docker-compose.yml:498` `- wget -q --spider http://127.0.0.1:8080/index.html` | 30s, 5s, 5, 10s |
| channel-gateway | readiness, not health `docker-compose.yml:615` `import urllib.request; urllib.request.urlopen('http://localhost:8091/ready')` | 30s, 5s, 3, 10s |
| whatsapp-bridge | a health route | 30s, 5s, 3, 10s |
| backup | declared in the image, not compose `deploy/backup.Dockerfile:87` `HEALTHCHECK --interval=60s --timeout=5s --start-period=5m --retries=3 \` | 60s, 5s, 3, 5m |
| hatchet-engine, hatchet-dashboard, bifrost, local-model, signal-cli | none declared | - |

The kernel's probe moved from liveness to readiness on 2026-07-26 and the file
records the incident that forced it: forty minutes of 503 on an unapplied
migration head while the container reported healthy `docker-compose.yml:191` `# 2026-07-25 a client tenant sat at /readyz 503 on an unapplied migration head`.
That coupling is deliberate and has a stated cost: services depending on a
healthy kernel will not START during a Hatchet outage
`docker-compose.yml:200` `# without it is genuinely not ready. Cost: channel-gateway and pi-sidecar`.

### 4.6 Dependency ordering

- `kernel` waits on postgres healthy, redis healthy and browser-executor healthy.
- `fleet-worker` waits on the same three.
- `hatchet-worker` waits on postgres, redis and browser-executor healthy, and on
  hatchet-engine merely started `docker-compose.yml:415` `condition: service_started`, because the engine
  declares no healthcheck and a healthy condition is therefore unavailable.
- `hatchet-engine` waits on postgres healthy.
- `hatchet-dashboard` and `ui` use the short list form, which means started, not
  healthy: `docker-compose.yml:494` `- kernel`.
- `channel-gateway` waits on kernel healthy; `whatsapp-bridge` waits on
  channel-gateway started; `backup` waits on postgres healthy.

## 5. Control flow

### 5.1 Cold bring-up of a fresh box (the genesis ceremony)

`genesis.sh` is the one-shot founder path. Seven steps, each with its failure
branch.

1. **Target selection.** `genesis.sh:22` `$TARGET` maps `dev` to base plus the dev
   overlay, `secure` to base plus the secure overlay, `base` to the base file
   alone; anything else exits 2. The gateway profile is always added
   `genesis.sh:28` `COMPOSE_PROFILES=(--profile gateway)`. Failure branch: an unknown target aborts before touching
   anything.
2. **Phase 0, secrets.** Copies the example env and manifest only if absent
   `genesis.sh:101` `cp .env.example`, then fills blanks only: the Postgres password, the audit
   HMAC key and an ed25519 device-lease seed. Secret generation returns early
   when a value already exists `genesis.sh:70` `] && return 0`, which is what makes a crashed
   run resumable. It then derives the database URL from the Postgres variables so
   the two cannot disagree `genesis.sh:111` `postgresql+asyncpg://${PGUSER}:${PGPW}@postgres:5432/${PGDB}`. Superadmin identity is required,
   never defaulted `genesis.sh:94` `SUPERADMIN_EMAIL is required; no personal default is bundled`.
3. **Phase 1, datastores.** Brings up postgres and redis, then waits for postgres
   healthy with a 90-second bound. Creates the Hatchet database out of band if
   absent `genesis.sh:132` `compose exec -T postgres createdb -U`. Failure branch: the wait returns 1 and the shell's
   errexit aborts.
4. **Phase 2, full stack.** Builds and starts everything, then waits for the
   kernel healthy with a 120-second bound. On a fresh volume no migration is
   needed because the first-boot hook loads the schema; an upgrade runs the
   migrate target separately `genesis.sh:138` `# migration is needed on a clean box; an UPGRADE of an existing box runs`.
5. **Phase 3, Hatchet token.** Mints a client token against the built-in tenant
   id `genesis.sh:30` `${HATCHET_TENANT_ID:-707d0855-80ab-4e1f-a156-f1c4546cbf52}` and restarts only the fleet worker. The failure branch is
   explicitly a warning, not an abort `genesis.sh:153` `WARNING: could not mint a hatchet token; the fleet falls back to the local executor (P9)`.
6. **Phase 4, superadmin.** Runs the one-shot initiate command inside the kernel
   container and matches either outcome `genesis.sh:162` `grep -qiE 'seated`. The command exists in
   the image via `pyproject.toml:126` `boltrig.api.cli:main`.
7. **Phase 5, verify.** Probes liveness and a real login against
   `genesis.sh:171` `http://localhost:${WORKER_PORT:-8082}`. Failure branch prints a warning and exits 0
   `genesis.sh:185` `== GENESIS finished with warnings (health=$HZ login=$LOGIN) - check 'compose logs' ==`, so a failed verification does not fail the script. See
   RISKS for the port mismatch this probe has against two of the three targets.

### 5.2 The daily dev bring-up

`scripts/dev-up.sh` layers the dev overlay and the gateway profile
`scripts/dev-up.sh:14` `COMPOSE=(docker compose --profile gateway -f docker-compose.yml -f deploy/compose.dev.yml)`, brings up five named services plus their dependencies
`scripts/dev-up.sh:17` `up -d --build kernel fleet-worker ui bifrost caddy`, polls liveness thirty times at two-second intervals
`scripts/dev-up.sh:20` `for i in $(seq 1 30); do`, then publishes one tailnet origin with three served
paths `scripts/dev-up.sh:27` `tailscale serve --bg --https=10000 --set-path=/v1 http://127.0.0.1:8000/v1 >/dev/null`. Failure branch: the poll has no else clause, so the
statement after the loop is the publish itself `scripts/dev-up.sh:25` `exposing one tailnet origin`, and the script publishes whether or not the
kernel ever answered.

### 5.3 The release train, end to end

Two halves that must not be confused: the **protected workflow** (cut, build,
scan, sign, attest, promote) in GitHub Actions, and the **operator admission**
(validate, pull, start, verify) on the target host.

**Half one, `.github/workflows/release.yml`.**

1. **Trigger.** A pushed tag `.github/workflows/release.yml:4` `push:`, serialised on
   one group that never cancels in progress `.github/workflows/release.yml:9` `group: boltrig-release`.
2. **Mode.** Preflight demands exactly one of `core` or `full` from the protected
   environment variable `.github/workflows/release.yml:42` `$(python3 scripts/validate_release_mode.py`, and the parser
   refuses anything decorated `boltrig/release_mode.py:14` `if value not in VALID_RELEASE_MODES:`.
3. **Registry write probe before the ten-minute builds.** It opens and cancels a
   blob upload per package `.github/workflows/release.yml:91` `https://ghcr.io/v2/$owner/$pkg/blobs/uploads/` rather than
   pushing, because a push probe would create the package with the wrong owner;
   a denial is reported in words `.github/workflows/release.yml:116` `$image: DENIED (HTTP ${code:-no-response})`.
4. **Ancestry and CI gates.** The tag's commit must be reachable from the default
   branch `.github/workflows/release.yml:152` `git merge-base --is-ancestor` and both canonical workflows must
   have succeeded for that exact sha `.github/workflows/release.yml:188` `require_successful_workflow ci.yml 'ci / quality'`.
5. **Draft.** A draft-only GitHub release is created or reused.
6. **Candidates, one job per image, four images.** The matrix begins at
   `.github/workflows/release.yml:326` `- image: kernel`. Each job builds locally, blocks on
   fixable high and critical findings using the SAME acceptances the security
   gate reads `.github/workflows/release.yml:421` `trivyignores: .trivyignore.yaml`, emits a CycloneDX SBOM,
   pushes only a run-scoped candidate tag `.github/workflows/release.yml:341` `CANDIDATE_TAG: candidate-${{ github.run_id }}-${{ github.run_attempt }}`,
   keylessly signs the digest, attests the SBOM and writes SLSA provenance.
7. **Publish.** Verifies all evidence, fetches each signed manifest and proves
   its bytes hash to the signed digest before publishing anything
   `.github/workflows/release.yml:1281` `sha256:$(sha256sum manifest.bin`, writes the immutable public tags only
   where absent and refuses where an existing tag disagrees
   `.github/workflows/release.yml:1303` `$image_name:$tag changed to $existing_digest after preflight`, emits exactly four digest lines into
   the image environment `.github/workflows/release.yml:1163` `$(wc -l <`, attaches it
   immutably through the release-asset helper, and finally flips the draft
   `.github/workflows/release.yml:1352` `--draft=false \`. Only a stable full release may become
   Latest `.github/workflows/release.yml:1348` `latest=(--latest)`.

**Half two, on the target host.**

8. **Exact tree.** Check out the protected tag with no modified tracked files;
   the runbook makes this blocking `docs/PROD-CUTOVER-RUNBOOK.md:77` `4. **Exact deployment tree:** the host is checked out at the protected tag with`.
9. **The validation target** `Makefile:316` `release-validate: ## Validate a downloaded, signed, attested release environment` runs four steps in order: the image
   environment validator; a JSON render of base plus release plus secure piped
   into the release compose validator; then the runtime validator, which verifies
   every digest before Docker may pull it and runs the production doctor inside
   an ephemeral image assembled from the signed fleet bytes `Makefile:326` `$(PY) scripts/validate_release_runtime.py $(RELEASE_IMAGES_ENV) \`.
   Failure branch: any step exits non-zero and make stops with nothing pulled or
   started.
10. **The start target** depends on the validation target `Makefile:330` `release-up: release-validate ## Pull and start signed release images (secure + backup)`, so
    validation reruns, then pull, then start with no build `Makefile:338` `-f deploy/compose.secure.yml up -d --no-build`.
11. **Verify at the destination.** `docs/PROD-CUTOVER-RUNBOOK.md:189` `Require and record:` lists
    eight acceptance items including liveness and readiness through the real
    edge, the packaged Alembic head, an intact audit chain and one durable
    pause and resume.

### 5.4 The legacy roll path

`scripts/roll-release.sh` is explicitly NOT the production path in the pinned
tree: `docs/DEPLOYMENT.md:377` `predates the four-image signature/SBOM/provenance gate` and `docs/PROD-CUTOVER-RUNBOOK.md:219` `is retained only for legacy/dev investigation. It`. It is
nevertheless a complete, gated, canary-first procedure and is specified here
because it is the only migrate-then-deploy automation in the tree.

1. **Self-check.** The script asserts that its OWN checkout contains the tag
   being rolled, before anything else `scripts/roll-release.sh:55` `merge-base --is-ancestor`, and dies if
   the directory is not a git checkout at all `scripts/roll-release.sh:59` `$SCRIPT_REPO is not a git checkout - cannot prove this script matches $VERSION`. The
   recorded reason is a v0.4.46 roll from a 170-commit-behind branch that
   reported success while silently leaving both hatchet-workers on the previous
   release `scripts/roll-release.sh:35` `, 170 commits behind the tag and`.
2. **Operator coordinates required, never defaulted.** Four variables each abort
   if empty `scripts/roll-release.sh:66` `ROLL_HOST is required`.
3. **Digest resolution, bounded wait.** Forty attempts at fifteen seconds for all
   three digests, parsing with awk because buildx 0.30.1 ignores the Go template
   `scripts/roll-release.sh:85` `digest_of() { docker buildx imagetools inspect`. Failure branch: three separate aborts naming
   which image never resolved.
4. **Source-first repin.** The overlay is edited in the TRACKED source tree, not
   on the box `scripts/roll-release.sh:120` `no tracked source for $rel at $src - the box copy is not authoritative, so refusing to edit it`; the diff is asserted to be exactly
   two lines per matching image line `scripts/roll-release.sh:146` `source diff for $rel is $n changed lines; expected $expected (2 per image line) or 0 (already pinned)`; then it is
   copied over and proven by checksum `scripts/roll-release.sh:158` `propagated $rel but the box checksum differs ($a vs $b)`. Remote
   backups are swept to the most recent three `scripts/roll-release.sh:171` `ls -1t ${remote}.bak-roll-* 2>/dev/null`.
5. **Migration gate, per stack, immediately before that stack's deploy.** The
   staging step copies the alembic chain and the gate script to the box
   `scripts/roll-release.sh:221` `$H:/tmp/roll-mig/migrate-stack.sh`; the gate is a FILE and not a heredoc because
   a heredoc once arrived empty and passed silently
   `scripts/roll-migrate-stack.sh:12` `# and on 2026-08-06 that heredoc reached the remote bash EMPTY: the ssh ran, returned 0,`. The gate reads the head from the TARGET
   IMAGE, not the checkout `scripts/roll-migrate-stack.sh:49` `python -c 'from boltrig.api.readiness import EXPECTED_ALEMBIC_HEAD as h; print(h)' 2>/dev/null`, reads the
   database URL out of the running kernel container rather than interpolating it
   into an ssh command line `scripts/roll-migrate-stack.sh:52` `printenv DATABASE_URL 2>/dev/null)`, and runs
   alembic in a throwaway container joined to that stack's own network
   `scripts/roll-migrate-stack.sh:56` `docker run --rm -i --network`, upgrading to the image's head
   `scripts/roll-migrate-stack.sh:78` `python -m alembic upgrade '$WANT'`. Failure branches: no chain staged, image
   unobtainable, head unreadable `scripts/roll-migrate-stack.sh:50` `could not read EXPECTED_ALEMBIC_HEAD from the target image`, no
   database URL, or a post-migration head that still differs
   `scripts/roll-migrate-stack.sh:82` `ABORT: schema is ${AFTER:-<empty>}, image asserts $WANT.`, which prints the rollback instruction
   `scripts/roll-migrate-stack.sh:83` `If the database is AHEAD, this is a rollback: it needs a human and a` and exits non-zero
   `scripts/roll-migrate-stack.sh:85` `exit 1`. Migrate-then-deploy is back-to-back and
   per stack because readiness is strict equality in both directions
   `scripts/roll-release.sh:193` `# db 0066 + image expecting 0067 -> 503, the NEW image is unready`.
6. **Bring up exactly four services with no dependencies**
   `scripts/roll-release.sh:179` `docker compose -f $COMPOSE -f $1 -p $2 up -d --no-deps kernel fleet-worker hatchet-worker ui`. The hatchet worker is in that list because it
   had been bounced by hand after every roll since v0.4.32.
7. **The gate.** Per stack: the kernel must reach healthy within 24 five-second
   polls `scripts/roll-release.sh:255` `$k never became healthy: '$st'` and must not be restarting
   `scripts/roll-release.sh:251` `$k is RESTARTING: $st`; the fleet worker must be running; BOTH must
   print an expected addons substring `scripts/roll-release.sh:266` `$k addons line is '$ka', expected to contain '$WANT'`; the
   kernel's running image must contain the version; and the ui container must
   reach healthy AND report the version `scripts/roll-release.sh:292` `$u is running '$uimg', not $VERSION`, because
   a container that never restarted reports healthy while serving the old bundle
   `scripts/roll-release.sh:279` `# that never restarted reports healthy while serving the old bundle.`.
8. **Canary is a gate, not a delay.** The canary stack rolls first and the tenant
   is touched only after it passes `scripts/roll-release.sh:308` `CANARY GATE PASSED - only now is the tenant touched`. The
   canary-only flag stops there and says the fleet is now uneven by design
   `scripts/roll-release.sh:337` `fleet is now UNEVEN by design; 'make fleet-drift-all' will say so.`.
9. **Post-roll alarm.** The unclaimed-bearer warning count must be zero on the
   tenant, with the exit-on-zero-matches trap of a counting grep folded inside
   `scripts/roll-release.sh:357` `docker logs --since 20m cv-boltrig-kernel-1 2>&1`.

### 5.5 A backup run

`scripts/backup.sh` produces one complete recovery point.

1. **Validate configuration before touching anything.** The retention count must
   be an integer, the database list must be a safe comma list
   `scripts/backup.sh:50` `=~ ^[A-Za-z0-9_-]+(,[A-Za-z0-9_-]+)*$ ]] \`, the dump, restore and checksum tools must exist, and
   if a state directory is set then tar, openssl and a passphrase are mandatory
   `scripts/backup.sh:60` `BACKUP_STATE_DIR contains sensitive state and requires BACKUP_PASSPHRASE`.
2. **Announce the off-box posture.** Unset remote warns and continues
   `scripts/backup.sh:128` `WARNING: BACKUP_REMOTE unset - off-box copy skipped (local-only backup)`; set-but-no-rclone dies immediately
   `scripts/backup.sh:125` `BACKUP_REMOTE=${BACKUP_REMOTE} set but rclone not found (install rclone or bake it into the sidecar image)`.
3. **Per database: dump, prove non-empty, prove parseable, publish.** The parse
   gate is `scripts/backup.sh:147` `pg_restore --list`. The literal default database keeps the
   historical short name; every other name is encoded into the artifact
   `scripts/backup.sh:139` `$BACKUP_DIR/boltrig-${database}-${ts}.dump`.
4. **Publish is atomic and verified.** The digest is computed from the temp file,
   the sidecar is written to a temp name, both are moved, then re-checked, and
   both are deleted on mismatch `scripts/backup.sh:83` `rm -f --`. Only then is the pair
   copied off-box.
5. **Optional encryption.** AES-256-CBC with PBKDF2 and a salt, passphrase read
   from the environment rather than the command line `scripts/backup.sh:112` `openssl enc -aes-256-cbc -pbkdf2 -salt -in`,
   and an empty ciphertext is a failure. Mandatory encryption refuses to publish
   at all without a passphrase `scripts/backup.sh:117` `refusing to publish signing state without BACKUP_PASSPHRASE`.
6. **Stack file state.** Tar is piped straight into the encrypter so no plaintext
   archive ever lands on disk, and the ciphertext is decrypted and listed as a
   verification before publish.
7. **The commit marker is uploaded LAST** `scripts/backup.sh:170` `# artifact and sidecar, so a partial remote run has no complete-set marker.`, after every
   artifact and sidecar `scripts/backup.sh:180` `off-box recovery-set marker copy to ${BACKUP_REMOTE} failed`, so a partial remote run has no
   complete-set marker.
8. **Prune whole recovery sets, not files**, with a while-read loop rather than
   the bash 4 array builtin, because bash 3.2 aborted the prune silently while
   the backup itself had already succeeded `scripts/backup.sh:187` `. mapfile is a bash 4 builtin and macOS still`.
9. **Freshness marker last of all**, written atomically `scripts/backup.sh:216` `mv --`,
   which is what the sidecar healthcheck and the kernel's read-only mount both
   consult.

The loop is deliberately dumb `scripts/backup-loop.sh:19` `$backup_command` under strict shell
options, so a failed run exits PID 1 and the restart policy makes it visible
rather than swallowing it `scripts/backup-loop.sh:2` `# Run backups on a fixed interval. A failed backup is intentionally not caught:`.

### 5.6 A restore

The executable procedure, from `docs/backup-restore.md:163` `Restore order for a full rebuild, inside a maintenance window with all writers`.

1. Select ONLY a timestamp that has a completion marker.
2. Run the recovery verifier with the marker path `Makefile:346` `recovery-verify: ## Verify one encrypted recovery set without decrypting or restoring it`. The target
   refuses to run without the variable `Makefile:348` `set RECOVERY_MARKER=/path/to/boltrig-<UTC>.recovery.sha256`.
3. Decrypt each encrypted artifact and prove each dump with a listing before
   restoring.
4. Bring up ONLY postgres. A NEW data volume runs the first-boot hook and creates
   the Hatchet database; an existing cluster never reruns it
   `deploy/postgres-init-hatchet.sh:5` `# existing deployment is never mutated by Compose startup; operators upgrading an`.
5. Restore both dumps, cleaning and ignoring absent objects, into their matching
   databases.
6. With the Hatchet engine STOPPED, restore the config volume, and restore
   Knowledge, libraries and the manifest to their deployment-owned paths
   preserving ownership and modes.
7. Start the engine, then kernel, fleet worker and hatchet worker
   `docs/backup-restore.md:175` `, then kernel,`. Existing client tokens survive ONLY if the
   matching config archive was restored `docs/backup-restore.md:176` `values remain valid only when the matching`.
8. Require readiness 200, a healthy fleet receipt and one real durable staging
   run before returning traffic.

`verify_recovery_set.py` is the read-only gate for step 2 and it is strict in
nine ways: the marker filename must match the exact pattern
`scripts/verify_recovery_set.py:11` `^boltrig-(\d{8}T\d{6}Z)\.recovery\.sha256$`; no symlinks anywhere
`scripts/verify_recovery_set.py:98` `if artifact.is_symlink() or not artifact.is_file():`; no repeated artifact or logical database;
every database artifact must be encrypted `scripts/verify_recovery_set.py:86` `database artifact {name} is not encrypted`;
no foreign artifact from another timestamp; no empty file; the digest must match
the marker; the sidecar must be byte-consistent with the marker line; and each
encrypted artifact must carry the OpenSSL salt header
`scripts/verify_recovery_set.py:110` `if handle.read(8) != b`. Missing required databases
`scripts/verify_recovery_set.py:114` `if missing:`, unexpected extra databases
`scripts/verify_recovery_set.py:117` `if unexpected:` and missing stack state are each a
distinct refusal.

## 6. Data

### 6.1 Backup artifact naming

| artifact | shape |
| --- | --- |
| default application dump | boltrig, timestamp, dump, optional enc suffix |
| any other logical database | boltrig, database name, timestamp, dump, optional enc suffix |
| stack file state | boltrig-state, timestamp, tar.gz.enc, always encrypted |
| per-artifact sidecar | the artifact name plus a sha256 suffix, holding digest and basename |
| set marker | boltrig, timestamp, recovery.sha256 |

The timestamp is a UTC compact form `scripts/backup.sh:64` `$(date -u +%Y%m%dT%H%M%SZ)`.

### 6.2 Recovery-set contents

The release backup overlay defines what complete means, and it is more than the
databases: `deploy/compose.release.yml:65` `- hatchet_config:/backup-state/hatchet-config:ro`, `deploy/compose.release.yml:66` `- knowledge_data:/backup-state/knowledge:ro`,
`deploy/compose.release.yml:67` `- ./manifest.yaml:/backup-state/deployment/manifest.yaml:ro` and `deploy/compose.release.yml:68` `- ./libraries:/backup-state/deployment/libraries:ro`, all
under a mandatory-encryption state directory `deploy/compose.release.yml:59` `BACKUP_STATE_DIR: /backup-state`.
Redis append-only state is explicitly OUT of the logical recovery set
`docs/backup-restore.md:18` `Redis AOF contains bounded relay/counter state, not the recovery authority for`, as are connector volumes such as Bifrost, Signal
and WhatsApp, which the document says the deployment must add to its own policy
`docs/backup-restore.md:20` `optional Bifrost, Signal, WhatsApp, or other connector state is enabled, add its`.

### 6.3 Schema bootstrap versus migration

Two distinct paths, and confusing them is destructive.

- **Fresh volume:** the schema file is bind-mounted into the init directory
  `docker-compose.yml:61` `- ./boltrig/store/schema.sql:/docker-entrypoint-initdb.d/01-schema.sql:ro` and runs once, after the Hatchet database hook
  `docker-compose.yml:58` `- ./deploy/postgres-init-hatchet.sh:/docker-entrypoint-initdb.d/00-hatchet-db.sh:ro`.
- **Existing deployment:** Alembic only `docs/DEPLOYMENT.md:712` `Alembic is the authoritative production upgrade path.`, applied by
  `Makefile:481` `$(PY) -m alembic upgrade head`. Parity between the two is checked by `Makefile:343` `migration-parity: ## Compare Alembic head with schema.sql on disposable PostgreSQL`.
- **Irreversibility:** revision 0022 fails its own downgrade on purpose
  `docs/DEPLOYMENT.md:728` `fails closed because an automated reverse migration`; crossing it backwards is a restore, never a
  downgrade.

### 6.4 The deployment tree is data too

Bind mounts carry bytes that no image digest covers. The complete set in the base
model:

| container | mounted from the tree |
| --- | --- |
| kernel | the manifest and the libraries tree `docker-compose.yml:174` `- ./manifest.yaml:/app/manifest.yaml:ro` |
| fleet-worker | the manifest and the libraries tree `docker-compose.yml:293` `- ./manifest.yaml:/app/manifest.yaml:ro` |
| browser-executor | the manifest and the libraries tree `docker-compose.yml:353` `- ./manifest.yaml:/app/manifest.yaml:ro` |
| hatchet-worker | the manifest and the libraries tree `docker-compose.yml:406` `- ./manifest.yaml:/app/manifest.yaml:ro` |
| postgres | the Hatchet init hook and the schema file |
| backup | the backup script in the base model only `docker-compose.yml:733` `- ./scripts/backup.sh:/usr/local/bin/backup.sh:ro`, the backups directory `docker-compose.yml:734` `- ${BACKUP_DIR:-./backups}:/backups` and the rclone config `docker-compose.yml:738` `- ${RCLONE_CONFIG_DIR:-./deploy/rclone}:/root/.config/rclone:ro` |
| local-model | the model cache directory |

`docs/DEPLOYMENT.md:358` `mounted from the deployment tree` lists only kernel, fleet-worker and postgres
(`docs/DEPLOYMENT.md:360` `(the skills the agents load)`) and therefore under-reports the surface by two
services. The doctrine around it is right and is stated in the strongest terms
available `docs/DEPLOYMENT.md:363` `**A bind-mounted directory is a deployment surface exactly like an image tag, and`, with a measured incident: a tenant 57
commits behind on the libraries tree for three days. The gate that answers it is
`Makefile:168` `fleet-drift: ## Is what is RUNNING what we pinned? (needs a box; not a CI gate)`, which the Makefile itself flags as needing a box and not being
a CI gate, plus `Makefile:177` `fleet-drift-all: ## Drift + bind-mount staleness for EVERY prod tenant` for both tenants at once.

## 7. Configuration surface

### 7.1 Required, the stack refuses to start without them

| variable | default | what breaks |
| --- | --- | --- |
| the Postgres password | none, required-var form `docker-compose.yml:51` `POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?set POSTGRES_PASSWORD (see .env.example)}` | Compose refuses to render the model at all. Also required by the backup service `docker-compose.yml:717` `PGPASSWORD: ${POSTGRES_PASSWORD:?set POSTGRES_PASSWORD (see .env.example)}`. |
| the four release image variables | none, required-var form `deploy/compose.release.yml:16` `image: ${BOLTRIG_KERNEL_IMAGE:?set BOLTRIG_KERNEL_IMAGE to an image@sha256 digest}` | the release model cannot render, and the image validator refuses missing, extra or tag-based values. |
| the release mode | none, required-var form `deploy/compose.release.yml:19` `BOLTRIG_RELEASE_MODE: ${BOLTRIG_RELEASE_MODE:?set BOLTRIG_RELEASE_MODE to exactly core or full}` | release compose will not render, and the validator requires all four runtime services to agree `scripts/validate_release_compose.py:70` `release services disagree on BOLTRIG_RELEASE_MODE`. It is NOT in the example env. Bounded: `grep -n BOLTRIG_RELEASE_MODE .env.example` returns nothing, 2026-08-24, pinned tree. |

### 7.2 Topology and ports

| variable | default | effect if wrong |
| --- | --- | --- |
| the env-file selector | the conventional dotfile `docker-compose.yml:158` `env_file: ${BOLTRIG_ENV_FILE:-.env}` | validation points at the example instead `Makefile:14` `COMPOSE_VALIDATE_ENV ?= .env.example`; a wrong path gives every service a different environment. |
| the kernel port | 8000, all interfaces | on a shared box with dev-auth this is an impersonation surface, which is why the dev overlay moves it `deploy/compose.dev.yml:39` `# headers with no verification, so an all-interfaces :8000 on a shared box is`. |
| the worker port | 8082 for the base ui service, but 8080 for the dev overlay's Caddy `deploy/compose.dev.yml:21` `127.0.0.1:${WORKER_PORT:-8080}:80` | the two defaults disagree; `.env.example:127` `WORKER_PORT=8082` is what keeps them consistent in practice. |
| the dev kernel port | 18001, dev overlay only `deploy/compose.dev.yml:48` `127.0.0.1:${BOLTRIG_DEV_KERNEL_PORT:-18001}:8000` | a collision with another local stack. |
| the VM worker port | 8080, VM overlay only `docker-compose.vm.yml:118` `0.0.0.0:${VM_WORKER_PORT:-8080}:8080` | the Mac-side tunnel cannot reach the VM's Worker. |
| the three Hatchet ports | 7077, 8888, 8889, all loopback | binding off loopback exposes a cleartext gRPC control plane and an unauthenticated dashboard; the deploy lint refuses it. |
| the gateway port | 8081, loopback | provider keys live behind that admin surface. |
| the local-model port, model and cache | 8001 loopback, a Qwen default, a repo-relative cache | a non-loopback bind publishes an unauthenticated sensitive-data model. |
| the Hatchet database name | `hatchet` | the first-boot hook creates the wrong database and the engine never boots; the hook validates the name shape `deploy/postgres-init-hatchet.sh:10` `=~ ^[A-Za-z0-9_-]+$ ]]`. |
| the Hatchet database URL | derived from the Postgres variables `docker-compose.yml:436` `DATABASE_URL: ${HATCHET_DATABASE_URL:-postgresql://${POSTGRES_USER:-boltrig}:${POSTGRES_PASSWORD}@postgres:5432/${HATCHET_DATABASE_NAME:-hatchet}?sslmode=disable}` | an override that drifts from the password breaks the engine silently. |
| the Hatchet cookie domain and server URL | localhost and a loopback URL | the engine refuses to boot without a cookie domain `docker-compose.yml:443` `# cookie domain). The engine is internal (loopback / compose network only),`. |
| the engine gRPC port | pinned to 7077 in the service `docker-compose.yml:441` `SERVER_GRPC_PORT:` | the engine binds 7070 by default and every SDK connect is reset. |

### 7.3 Security posture

| variable | default | effect |
| --- | --- | --- |
| the domain | localhost in the secure overlay, a bare port in the dev overlay `deploy/compose.dev.yml:26` `BOLTRIG_DOMAIN: ${BOLTRIG_DOMAIN:-:80}` | the bare-port form serves plain HTTP with no auto-HTTPS redirect; a real domain gets auto-TLS. |
| the Postgres data host path | the named volume `deploy/compose.secure.yml:81` `- ${PGDATA_HOST:-pgdata}:/var/lib/postgresql/data` | encryption at rest is an operator decision made here, not in the image. |
| the CA bundle file and in-container path | a repo-relative default and unset | the secure overlay mounts the file into the containers; the in-container variable must then name that path or outbound calls will not trust the internal CA. |
| the three proxy variables | empty, empty, a service-name list `.env.example:119` `NO_PROXY=localhost,127.0.0.1,postgres,redis,kernel,hatchet-engine,bifrost,local-model,langfuse` | passed as build args AND read at runtime; omitting a service name routes intra-stack traffic through the corporate proxy. |
| the air-gapped flag | false | with the local profile this is the offline posture. |
| the trusted Codex flag | forced off in the dev overlay `deploy/compose.dev.yml:53` `BOLTRIG_CODEX_TRUSTED:` | the trusted lane is deliberately unavailable in ordinary dev containers. |
| the dev-auth flag | on in the dev overlay | must be unset in production `docs/DEPLOYMENT.md:1021` `- [ ] real OIDC configured (`. |
| the reflection flag | empty, defaulted off deliberately `docker-compose.yml:281` `BOLTRIG_REFLECT: ${BOLTRIG_REFLECT:-}` | the only automatic memory writer in the stack; switching it on is a data-retention decision. |
| the knowledge vault path | the same value on kernel and worker `docker-compose.yml:291` `BOLTRIG_KNOWLEDGE_VAULT: ${BOLTRIG_KNOWLEDGE_VAULT:-/var/lib/boltrig/knowledge}` | a divergent root seeds two vaults, and on a read-only rootfs the per-user fallback is a hard boot failure. |

### 7.4 Backup

| variable | default | effect if wrong |
| --- | --- | --- |
| the interval | 86400 | must be a positive integer or the loop refuses to start `scripts/backup-loop.sh:10` `backup: ERROR: BACKUP_INTERVAL must be a positive integer`; it also sets the staleness window. |
| the health grace | 3600 | the sidecar is unhealthy once the marker is older than interval plus grace `scripts/backup-healthcheck.sh:18` `$((interval + grace))`. |
| the retention count | 7 | zero disables pruning; a non-integer aborts the whole run. |
| the database list | the application and Hatchet databases `docker-compose.yml:721` `BACKUP_DATABASES: ${BACKUP_DATABASES:-${POSTGRES_DB:-boltrig},${HATCHET_DATABASE_NAME:-hatchet}}` | omitting Hatchet yields a recovery point that cannot resume durable runs, and the verifier refuses it against the default required set. |
| the backups directory | a repo-relative default `docker-compose.yml:734` `- ${BACKUP_DIR:-./backups}:/backups` | must be on encrypted media `docs/DEPLOYMENT.md:622` `) on the same encrypted media.`. |
| the off-box remote | unset | unset means local-only with a warning; set and broken exits non-zero. |
| the passphrase | unset | unset means unencrypted database dumps, and it is mandatory once a state directory is configured. Losing it makes a restore impossible. |
| the state directory | unset in base, set in the release overlay | when set, adds the encrypted stack-state archive to the recovery set. |
| the health file | the shared volume path `docker-compose.yml:728` `BACKUP_HEALTH_FILE: /backup-health/last-success` | the kernel reads that path read-only. |
| the rclone config directory | a repo-relative default | mounted read-only; the directory is git-ignored and docker-ignored. |
| the recovery marker and database set | none and the two-database default `Makefile:24` `RECOVERY_DATABASES ?= boltrig,hatchet` | a custom application database name needs the exact set passed or verification refuses the set. |

### 7.5 Release and roll

| variable | default | effect |
| --- | --- | --- |
| the release env and image env | the conventional dotfile `Makefile:25` `RELEASE_ENV ?= .env` and the release env file | the operator inputs to validation. |
| the release profiles | the backup profile `Makefile:29` `RELEASE_PROFILES ?= --profile backup` | see RISKS: emptying it removes the backup service from the merged model, which the validator requires. |
| the release tag | unset | disambiguates when several protected tags point at one commit. |
| the five roll variables | none for the first four, the script's own repo root for the last | all four of the first are hard-required. |
| the canary-only flag | 0 | 1 rolls the canary and stops. |
| the four drift variables | empty host, a default project, operator paths | the host is deliberately empty so no production box is bundled. |
| the two validation variables | the example env `Makefile:14` `COMPOSE_VALIDATE_ENV ?= .env.example` and a validation-only password `Makefile:15` `COMPOSE_VALIDATE_POSTGRES_PASSWORD ?= boltrig-compose-validation-only` | validation must work from a clean checkout. |

### 7.6 Disk hygiene

The watched path defaults to the root filesystem, the warn threshold to 80, the
prune threshold to 85, the retention window to 168 hours, and the escalation
ladder to three shorter windows `scripts/docker-disk-hygiene.sh:41` `${RETAIN_LADDER:-72 24 6}`. Emptying
the ladder disables escalation, which is exactly the configuration that let a
host walk to 100 percent `scripts/docker-disk-hygiene.sh:76` `# Six hours later the host reached 100% and a client tenant's UI crash-looped on`.

## 8. PROCESS

### 8.1 Bring the stack up

| intent | command | what it layers |
| --- | --- | --- |
| whole stack, build from source | the up target `Makefile:38` `up: ## Build + start the whole stack (add ARGS=` | base only, build and start |
| with on-box inference | the up target with the local profile | base plus the local profile |
| TLS terminator, production-shaped | the secure-up target `Makefile:41` `secure-up: ## Start with the TLS / encrypted-at-rest overlay (deploy/compose.secure.yml)` | base plus secure |
| dev, single loopback origin | the dev-up script | base plus dev, gateway profile |
| founder ceremony on a fresh box | genesis with a target word | per target, plus gateway |
| signed release | validate, then start | base plus release plus secure, backup profile |
| the OrbStack Linux VM on the M4 | base plus the VM overlay, as used by `scripts/activate-sensing.sh:74` `-f docker-compose.yml -f docker-compose.vm.yml` | base plus vm |
| attach to the Opbox network | base plus the opbox-link overlay `deploy/compose.opbox-link.yml:10` `- default` | adds an external network to the kernel |
| single-tenant in-process Codex | base plus the inprocess overlay `deploy/compose.inprocess.yml:25` `10001:10001` | runs the kernel as uid 10001 |

Stop with the down target `Makefile:44` `down: ## Stop the stack (keep the postgres volume)`, which keeps volumes.

### 8.2 Validate a change to any manifest

The compose-validate target `Makefile:265` `compose-validate: ## Validate base and secure Compose configurations` runs six config renders (base; base
plus the channels profile; base plus secure; base plus dev; base plus inprocess;
base plus opbox-link) plus the release image validator against a checked fixture
and two release renders piped into the release compose validator. It runs with
the example env file and a validation-only password so it works from a clean
checkout.

The gate-coverage gate keeps that list honest: it globs the overlays plus the
root compose file and requires each to be an input to some config recipe
`scripts/check_gate_coverage.py:155` `found = {p.relative_to(ROOT).as_posix() for p in (ROOT /`, deriving the list rather than restating
it `scripts/check_gate_coverage.py:35` `here - so adding a seventh compose manifest or a ninth`.

### 8.3 Roll a release to a fleet (the legacy path)

Set the four required roll variables, run the roll script with a version tag, and
run the fleet-drift target for both tenants afterwards. The canary-only flag
stops after the canary and leaves the fleet uneven on purpose.

Afterwards, the deployment verifier answers the question a container healthcheck
cannot: is this stack SERVING, and does the running image demonstrably contain
the change `scripts/verify-deployment.sh:13` `# finished when readyz says ready AND the running image demonstrably contains the`. It exits non-zero if readiness is
not ready or a named symbol is absent `scripts/verify-deployment.sh:97` `VERIFY FAILED: ${CONTAINER} is running but not serving what you think`, and it
can run over ssh.

### 8.4 Migrate

The migrate target `Makefile:480` `migrate: ## Apply the authoritative ordered Alembic migration chain` is the local form. During a roll the
migration is NOT to the checkout's head: it is to the target image's asserted
head, because the repository can be ahead of the release being rolled. The
pre-migration checklist is five steps at `docs/DEPLOYMENT.md:716` `Before every production migration:`.

### 8.5 Back up, verify and rehearse

The five operator commands are the backup target, the backup-schedule target, the
restore target, the recovery-verify target with a marker path, and the
recovery-rehearsal target.

The rehearsal refuses a remote Docker daemon before it creates anything
`Makefile:354` `$(PY) scripts/require_local_docker.py`, and the guard accepts only local socket schemes or a loopback
tcp host `scripts/require_local_docker.py:19` `} and parsed.hostname in {`, raising otherwise
`scripts/require_local_docker.py:26` `recovery rehearsal requires a local Docker endpoint;`. It also strips any ambient test database
URL `Makefile:355` `env -u BOLTRIG_TEST_DATABASE_URL scripts/with_test_postgres.sh \` so it cannot select an operator database.

A systemd-timer alternative to the sidecar is given verbatim at
`docs/backup-restore.md:104` `# /etc/systemd/system/boltrig-backup.service`; that path requires the dump, copy and encryption
tools on the host.

### 8.6 Keep the host able to deploy

The disk-hygiene script reports every run and prunes only over threshold. Order:
builder prune, image prune, an all-images prune at the long window, then
escalation through the ladder while still over
`scripts/docker-disk-hygiene.sh:86` `docker image prune -a --filter`. If still over after all of that it prints
what the disk-usage report actually says `scripts/docker-disk-hygiene.sh:118` `$(date -u '+%Y-%m-%dT%H:%M:%SZ') docker-disk-hygiene STILL ${after_pct}% after pruning; ${img_reclaimable} of images are STILL reclaimable - they are in use, or newer than the shortest window tried (until=${last_window}h). Lower RETAIN_LADDER or stop the containers holding them`
and exits non-zero so cron mails it `scripts/docker-disk-hygiene.sh:121` `exit 1`.

The wheelhouse builder downloads one requirement at a time so a truncated wheel
costs one package rather than the whole download
`scripts/build-wheelhouse.sh:50` `if docker run --rm --network=host -v`, five passes, exiting non-zero
`scripts/build-wheelhouse.sh:63` `exit 1` if anything is still outstanding
`scripts/build-wheelhouse.sh:62` `WHEELHOUSE INCOMPLETE: $(ls`. The kernel image picks it up through an
OPTIONAL bracket-glob copy that is a no-op when the directory is absent
`deploy/kernel.Dockerfile:68` `COPY deploy/wheelhous[e] /wheelhouse/`, and the hash contract is identical in both
branches `deploy/kernel.Dockerfile:71` `pip install --require-hashes --no-index --find-links=/wheelhouse -r /app/requirements-lock.txt; \`. The directory is git-ignored
`.gitignore:74` `deploy/wheelhouse/` and is not present in the pinned tree.

### 8.7 The Ubuntu 24.04 host preflight

On Ubuntu 24.04 and later the Codex cell-wall proof needs a named AppArmor
profile installed on the host before the three Codex-composing services will
start `docs/DEPLOYMENT.md:466` `sudo cp deploy/apparmor/boltrig-codex /etc/apparmor.d/boltrig-codex`. Its allow list is eight bare
rules: network, capability, file, umount `deploy/apparmor/boltrig-codex:25` `umount,`,
mount, userns `deploy/apparmor/boltrig-codex:27` `userns,`, pivot_root
`deploy/apparmor/boltrig-codex:28` `pivot_root,` and signal, followed by a deny block
covering proc writes, sysrq-trigger, kcore and the /sys tree
`deploy/apparmor/boltrig-codex:31` `deny @{PROC}/* w,`. How far that departs from
docker-default is UNCERTAIN, and the tree gives two answers: the profile header
says two lines `deploy/apparmor/boltrig-codex:13` `Differs from docker-default in exactly two lines`, and the
profile's own README says three additions, counting pivot_root
`deploy/apparmor/README.md:88` `with three additions:`. docker-default is generated by
the Docker daemon and is not a file in this tree (bounded: `grep -rn docker-default . --exclude-dir=.git --exclude-dir=brownfield-spec`
over the pinned tree, 2026-08-24, hits only those two files), so this corpus
cannot adjudicate the counts; diffing the daemon-generated profile from a host at
a named Docker version would. It must stay NAMED and never be unconfined,
which loses 24.04's allowance for confined docker profiles
`deploy/apparmor/boltrig-codex:10` `LOSES that allowance - measured,`. On the M4's OrbStack VM the equivalent
relaxation is syscall filtering only, on kernel and fleet-worker
`docker-compose.vm.yml:70` `- seccomp:unconfined`, and the file records that OrbStack's own Docker
engine needed full privileged mode while Docker inside the Linux VM needed only
the seccomp relaxation `docker-compose.vm.yml:15` `# Docker inside this Linux VM : seccomp=unconfined is ENOUGH.`.

## 9. Failure modes and fail-open/fail-closed posture

| guard | direction | proof |
| --- | --- | --- |
| the Postgres password unset | fail-closed, the model will not render | `docker-compose.yml:51` `POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?set POSTGRES_PASSWORD (see .env.example)}` |
| release image env missing, extra or tag-based | fail-closed | `scripts/validate_release_images.py:50` `.join(mutable)` |
| a build key surviving into a release model | fail-closed | `scripts/validate_release_compose.py:84` `release service {name} still has a build definition` |
| channels profile active in a release model | fail-closed | `scripts/validate_release_compose.py:49` `release channels posture is not admitted` |
| the browser executor publishing a host port | fail-closed | `scripts/validate_release_compose.py:96` `release browser executor publishes a host port` |
| the hatchet worker not on the fleet digest | fail-closed | `scripts/validate_release_compose.py:90` `release Hatchet worker does not use the fleet-worker image digest` |
| a release backup service with a source mount | fail-closed | `scripts/validate_release_compose.py:125` `release backup service replaces signed code with a source mount` |
| unexpected variables in the image env | fail-closed | `scripts/validate_release_images.py:45` `unexpected release image variables: {', '.join(unexpected)}` |
| roll script older than the tag it rolls | fail-closed | `scripts/roll-release.sh:56` `rev-parse --abbrev-ref HEAD)) does not contain $VERSION - this script would be older than the release it is rolling. Check out a commit that contains the tag.` |
| migration gate cannot read the target head | fail-closed | `scripts/roll-migrate-stack.sh:50` `could not read EXPECTED_ALEMBIC_HEAD from the target image` |
| database found ahead of its image | fail-closed, and named a rollback | `scripts/roll-migrate-stack.sh:85` `exit 1` |
| canary kernel never healthy or restarting | fail-closed, tenant untouched | `scripts/roll-release.sh:255` `$k never became healthy: '$st'` |
| backup dump unparseable or empty | fail-closed, no marker written | `scripts/backup.sh:148` `pg_restore could not parse the ${database} archive` |
| a configured off-box copy fails | fail-closed, PID 1 exits non-zero | `scripts/backup.sh:91` `off-box copy to ${BACKUP_REMOTE} failed` |
| off-box remote unset | fail-open BY DESIGN, warns and continues | `scripts/backup.sh:128` `WARNING: BACKUP_REMOTE unset - off-box copy skipped (local-only backup)` |
| stack state without a passphrase | fail-closed | `scripts/backup.sh:117` `refusing to publish signing state without BACKUP_PASSPHRASE` |
| backup marker missing, malformed or stale | fail-closed, unhealthy | `scripts/backup-healthcheck.sh:12` `$health_file` |
| recovery set incomplete, tampered, symlinked or unencrypted | fail-closed | `scripts/verify_recovery_set.py:114` `if missing:` |
| recovery rehearsal against a remote daemon | fail-closed | `scripts/require_local_docker.py:26` `recovery rehearsal requires a local Docker endpoint;` |
| a release asset already present and byte-different | fail-closed, never clobbers | `scripts/release_asset.sh:131` `immutable release asset $asset_name differs from this run` |
| registry push permission missing | fail-fast in preflight, before the builds | `.github/workflows/release.yml:116` `$image: DENIED (HTTP ${code:-no-response})` |
| a public tag that moved after preflight | fail-closed, promotion stops | `.github/workflows/release.yml:1303` `$image_name:$tag changed to $existing_digest after preflight` |
| disk still over threshold after every window | fail-loud, exit non-zero with real numbers | `scripts/docker-disk-hygiene.sh:121` `exit 1` |
| wheelhouse incomplete after five passes | fail-closed | `scripts/build-wheelhouse.sh:63` `exit 1` |
| genesis cannot mint a Hatchet token | fail-open BY DESIGN, falls back to the local executor | `genesis.sh:153` `WARNING: could not mint a hatchet token; the fleet falls back to the local executor (P9)` |
| genesis verification fails | **fail-open**, prints warnings and exits 0 | `genesis.sh:185` `== GENESIS finished with warnings (health=$HZ login=$LOGIN) - check 'compose logs' ==` |
| dev-up kernel health poll never succeeds | **fail-open**, publishes the origin anyway | `scripts/dev-up.sh:25` `exposing one tailnet origin` |

Two structural failure modes worth naming separately.

**A recreate of the Hatchet engine is a fleet-wide outage** unless its config is
persistent. The engine generates its signing keyset into its config directory on
first boot; without a volume, every recreate mints a new keyset and instantly
invalidates every client token `docker-compose.vm.yml:56` `# container mints a new keyset and instantly invalidates whatever`. The base file now
persists it `docker-compose.yml:460` `- hatchet_config:/config`, and `docs/DEPLOYMENT.md:514` `### Keep Hatchet identity and recovery state together` makes
database plus config plus token one recovery point.

**A container restart does not reload an env file.** It replays the container's
baked environment; the file is read once at create time
`docs/DEPLOYMENT.md:134` `.** It replays the container's`. The consequence is that a config change looks like it
did nothing while liveness stays green. Recreate, never restart.

## 10. What is proven

| invariant | what it binds here | tests |
| --- | --- | --- |
| SEC-64 | the hardening anchor's six properties on kernel and fleet-worker, and a non-root final user in both first-party Dockerfiles | `tests/security/test_round_seventeen.py:24` `def test_app_containers_are_hardened():` and `tests/security/test_round_seventeen.py:40` `def test_app_images_run_non_root():` |
| SEC-70 | Hatchet engine, dashboard and local-model loopback-only in base, dropped in secure, and no literal Postgres password | `tests/deploy/test_compose_hardening.py:72` `def test_hatchet_ports_are_loopback_only_in_base_compose():`, `tests/deploy/test_compose_hardening.py:87` `def test_secure_overlay_drops_hatchet_host_ports():`, `tests/deploy/test_compose_hardening.py:98` `def test_local_model_port_is_loopback_only_and_removed_from_secure_compose():`, `tests/deploy/test_compose_hardening.py:107` `def test_postgres_password_has_no_literal_default():` |
| SEC-71 | the whole backup and recovery contract | `tests/deploy/test_compose_hardening.py:143` `def test_backup_sidecar_ships_profile_gated():`, `tests/deploy/test_compose_hardening.py:182` `def test_fresh_postgres_boot_creates_the_separate_hatchet_database() -> None:`, `tests/deploy/test_backup_scripts.py:149` `def test_backup_verifies_dump_checksum_and_remote_pair(tmp_path: Path) -> None:` onward, `tests/deploy/test_recovery_set_verifier.py:44` `def test_recovery_set_verifier_accepts_complete_encrypted_evidence_read_only(` onward |
| SEC-136 | backup credentials excluded from git AND every image context | `tests/deploy/test_compose_hardening.py:333` `def test_backup_credentials_are_excluded_from_git_and_image_contexts():` |
| SEC-137 | the four-image signed release train and the no-build release overlay | `tests/deploy/test_compose_hardening.py:380` `def test_release_publishes_only_scanned_signed_digest_images_with_sboms():`, `tests/deploy/test_compose_hardening.py:456` `def test_release_requires_canonical_success_for_the_exact_commit():`, `tests/deploy/test_compose_hardening.py:473` `def test_release_compose_uses_only_required_digest_images_without_builds():` |
| IAC-002 | hash-locked installs with no unlocked build environment | `tests/deploy/test_compose_hardening.py:342` `def test_python_images_do_not_invoke_unlocked_build_isolation():` |
| IAC-003 | pinned, offline, blocking IaC scanning | `tests/deploy/test_iac_scan_policy.py:35` `def test_iac_scan_is_pinned_offline_blocking_and_ci_enforced() -> None:` |
| IAC-005 | the release workflow can actually publish and fails fast when it cannot | `tests/deploy/test_release_asset_reuse.py:144` `def test_exact_asset_retry_reuses_bytes_and_refuses_replacement(tmp_path: Path) -> None:` and the release-can-publish suite |
| FR-OPS-02 | compose validation reproducible from a clean checkout | `tests/deploy/test_compose_hardening.py:120` `def test_compose_validation_is_clean_checkout_safe():` |
| FR-OPS-06 | fleet-drift sees bind-mounted trees, not only digests | the nine tests in `tests/deploy/test_fleet_drift_sees_bind_mounts.py` |
| FR-HOST-11 | browser CLI state is stack-owned, executor-isolated and never mounted into the callers | `tests/deploy/test_compose_hardening.py:200` `def test_browser_cli_state_is_stack_owned_in_compose():`, `tests/deploy/test_compose_hardening.py:212` `browser-egress`, `tests/deploy/test_compose_hardening.py:225` `~/.local` |
| FR-HOST-13 | no personal browser-cloud variable in compose or the example env | `tests/deploy/test_compose_hardening.py:351` `def test_browser_cli_cloud_policy_is_stack_prefixed_in_deploy_config():` |
| KNO-04 | Knowledge and Cognee have stack-owned persistent storage in compose and image | `tests/deploy/test_compose_hardening.py:241` `def test_knowledge_and_bundled_cognee_have_stack_owned_persistent_storage():` |
| FR-RUN-01 | retired agent CLIs absent from first-party images | `tests/deploy/test_compose_hardening.py:366` `def test_retired_agent_clis_are_absent_from_first_party_images():` |

Also proven without an invariant id: disk-hygiene escalation and its reporting
branches (`tests/deploy/test_disk_hygiene_escalates.py:123` `def test_escalates_when_the_window_protects_the_garbage(tmp_path: Path) -> None:` and
`tests/deploy/test_disk_hygiene_escalates.py:148` `def test_reports_remaining_reclaimable_instead_of_denying_it(tmp_path: Path) -> None:`), and that every container
removal in the repo passes the volumes flag
(`tests/deploy/test_docker_rm_removes_anonymous_volumes.py:101` `def test_every_container_removal_takes_the_volumes_flag() -> None:`).

**What is NOT proven.** No test in the pinned tree asserts any service's restart
policy, any dependency edge, or sandbox network membership. Bounded:
`rg -n "unless-stopped|restart_policy|depends_on" tests/ scripts/` returns only
unrelated hits in `tests/test_verb_binding_ownership.py`,
`tests/security/test_run_cancel.py`, `tests/integration/test_ultracode_run.py`
and `tests/unit/test_mastra_compiler.py`, 2026-08-24, pinned tree. No test covers
the roll script, the migration gate, genesis, dev-up, the wheelhouse builder or
the deployment verifier. Bounded:
`rg -n "roll-release|roll-migrate-stack|genesis.sh|dev-up.sh|build-wheelhouse|verify-deployment" tests/`
returns two hits, both asserting one substring and nothing about behaviour, at
`tests/security/test_round_six.py:167` `--profile gateway`.

## 11. RISKS

RISK: The container-hardening deploy-lint covers only two of the six services
that merge the anchor, so browser-executor, hatchet-worker, channel-gateway and
whatsapp-bridge could each silently drop the read-only rootfs, the dropped
capabilities, the pids limit or the memory limit and stay green.
`tests/security/test_round_seventeen.py:19` `_APP_SERVICES = (`.

RISK: The deployment checklist requires all three first-party runtime services to
execute as uid 10001 and says not to override it to root, but the committed base
compose runs the kernel at uid 0 with two capabilities re-added. An operator
following the checklist literally would either fail the check or revert a
deliberate posture. `docs/DEPLOYMENT.md:478` `The image's service user is uid 10001. Do not override it to root: with` versus `docker-compose.yml:119` `user:`.

RISK: The deployment document states that the base compose backs the two
per-worker browser-CLI home variables with named volumes. It does not: neither
variable appears in any compose file, and a test actively asserts the browser
volume is NOT mounted into those services. `docs/DEPLOYMENT.md:647` `The base compose file backs these with named volumes. The first-party images` versus
`tests/deploy/test_compose_hardening.py:225` `~/.local`. Both variables exist only as
commented lines at `.env.example:202` `# BOLTRIG_FLEET_BROWSER_CLI_HOME=/var/lib/boltrig/browser-cli/fleet-worker`.

RISK: The VM overlay reaches no validation step at all. The gate-coverage check
globs the deploy overlays plus the root compose file and cannot see it
`scripts/check_gate_coverage.py:155` `found = {p.relative_to(ROOT).as_posix() for p in (ROOT /`, and neither can the health-claim gate
`scripts/check_health_claims.py:26` `registers a readiness path (/readyz, /ready, /readiness), the healthcheck is`. Bounded: `rg -n "docker-compose.vm" .`
over the pinned tree returns three hits, none a Makefile target or a test. This
is the same class of defect the gate-coverage docstring was written to close for
the other overlays.

RISK: The VM overlay justifies persisting the Hatchet config on a premise that is
now false: it says the base compose has no such volume, but the base file mounts
one. The overlay is harmless, but its stated reason no longer holds and a reader
would draw the wrong conclusion about the base file.
`docker-compose.vm.yml:56` `# container mints a new keyset and instantly invalidates whatever` versus `docker-compose.yml:460` `- hatchet_config:/config`.

RISK: Genesis verifies against port 8082 read from its OWN shell rather than from
the env file it just wrote. For the secure target the ui host port is removed
entirely `deploy/compose.secure.yml:52` `ports: !override []`, so the verification cannot succeed
there; for the dev target the Caddy default is 8080, not 8082
`deploy/compose.dev.yml:21` `127.0.0.1:${WORKER_PORT:-8080}:80`, and the two coincide only because the example env
pins 8082. `genesis.sh:171` `http://localhost:${WORKER_PORT:-8082}`.

RISK: A failed genesis verification does not fail the script. Both probes can be
empty and genesis still exits 0 with a warning, so an automation caller reading
the exit code would record a successful founding ceremony on a stack that never
answered. `genesis.sh:185` `== GENESIS finished with warnings (health=$HZ login=$LOGIN) - check 'compose logs' ==`.

RISK: The deployment document tells an operator they may empty the release
profiles variable when backup scheduling is externally provided. Doing so drops
the backup service from the merged model, and the release compose validator
requires it as one of six first-party services, so validation would then fail.
Not measured, since no compose run was performed on this host, but the two
statements cannot both be right. `docs/DEPLOYMENT.md:77` `only when backup scheduling is provided and` versus
`scripts/validate_release_compose.py:34` `"backup",`.

RISK: The release mode is required by the release overlay and by four services'
environments and appears nowhere in the example env. An operator who builds their
env file from the example gets a fail-closed refusal at the first release command
with no example line to copy. Bounded:
`grep -n BOLTRIG_RELEASE_MODE .env.example` returns nothing, 2026-08-24.

RISK: The dockerignore re-inclusion is broader than its own comment claims.
`.dockerignore:36` `docs` excludes the docs tree and `.dockerignore:42` `!docs/` re-includes
the entire directory before the three narrow token exceptions are reached, so the
whole 22MB docs tree is a build-context input for every image rather than the
three CSS files the comment names. Image CONTENTS are unaffected, since both
first-party Dockerfiles copy explicit paths, so this is context size and transfer
rather than shipped bytes. Not measured: no docker build was run.

RISK: The deployment-tree table under-reports the bind-mount surface by two
services. The browser executor and the hatchet worker both mount the manifest and
the libraries tree, and the table lists only kernel, fleet-worker and postgres.
`docs/DEPLOYMENT.md:360` `(the skills the agents load)` versus `docker-compose.yml:406` `- ./manifest.yaml:/app/manifest.yaml:ro`.

RISK: The base compose header still names a retired Pi sidecar as a consumer of
the hardening anchor and as a service carrying a healthy-kernel dependency. No
such service exists in the pinned tree. Bounded:
`grep -rn "pi_sidecar|pi-sidecar" docker-compose.yml deploy/` returns three hits,
all comments. `docker-compose.yml:26` `# /tmp. Merged into the kernel / fleet-worker / pi_sidecar services below.`. The same header's service list omits six
services that do exist: browser-executor, hatchet-worker, channel-gateway,
signal-cli, whatsapp-bridge and backup. `docker-compose.yml:11` `# Services:`.

RISK: The README quickstart tells the reader the console UI comes up on port 8080
while the shipped example env puts it on 8082, so following the README's own
two-command sequence lands on a port the README does not name. `README.md:138` `run in every environment; only`
versus `docker-compose.yml:492` `${WORKER_PORT:-8082}:8080`.

RISK: The base stack publishes both kernel and ui on ALL interfaces, and the dev
overlay's own comment says why that is dangerous on a shared box, yet nothing
prevents an operator running the plain up target on such a box.
`deploy/compose.dev.yml:38` `# ${KERNEL_PORT}:8000 on all interfaces, but dev-auth trusts x-boltrig-*`.

RISK: The example Caddyfile routes only the API prefix and liveness to the
kernel; readiness falls through to the Worker upstream
`deploy/Caddyfile.example:31` `handle /healthz {`. It works only because the Worker's own nginx
proxies readiness onward `apps/worker/nginx.conf:55` `location = /readyz {`, which means the
cutover-acceptance requirement that readiness succeed through the real edge is
answered by a path that dies if the ui container is down, even when the kernel is
perfectly ready.

RISK: The hatchet worker depends on the engine with a started condition because
the engine declares no healthcheck, so the worker can start against an engine
that has not finished booting and will crash-loop rather than wait.
`docker-compose.yml:415` `condition: service_started`.

RISK: The signed release set is four images; the three channels services are
first-party but unsigned, and their credential-bearing volumes are outside the
standard recovery set. The release validator refuses the profile outright, which
is the right posture, but a development or acceptance deployment running that
profile has credential volumes with no backup policy.
`docs/backup-restore.md:20` `optional Bifrost, Signal, WhatsApp, or other connector state is enabled, add its`.

RISK: The only migrate-then-deploy automation in the tree is declared
non-production, and the canonical runbook's migration step is prose
`docs/PROD-CUTOVER-RUNBOOK.md:169` `only with writers stopped.`, which is exactly the argument the roll
script makes against itself `scripts/roll-release.sh:200` `# next to the deploy - a runbook cannot hold two steps together.`.

RISK: The dev bring-up script publishes the stack on a tailnet origin regardless
of whether the kernel ever became healthy. The poll is a bounded loop with no
else clause `scripts/dev-up.sh:20` `for i in $(seq 1 30); do` and the next statement
executed is the publish `scripts/dev-up.sh:25` `exposing one tailnet origin`.

RISK: The tree carries two different accounts of what the named AppArmor profile
adds over docker-default, and the smaller one is in the profile itself. The
header says two lines `deploy/apparmor/boltrig-codex:13` `Differs from docker-default in exactly two lines`; the
README says three additions, naming pivot_root `deploy/apparmor/README.md:88` `with three additions:`;
and the body does carry it `deploy/apparmor/boltrig-codex:28` `pivot_root,`. An operator
auditing the host posture from the profile header under-counts the grant by one.

## 12. OPEN QUESTIONS

1. **Does the opbox-link overlay keep the kernel on the sandbox network?** The
   overlay declares a two-entry network list `deploy/compose.opbox-link.yml:10` `- default`,
   and Compose's merge rule for the service-level networks key decides whether
   the sandbox membership survives. What would settle it: rendering base plus
   that overlay and reading the kernel's network set. Not run here.

2. **Is the dockerignore docs re-inclusion real in practice?** The reasoning
   above follows Docker's last-matching-pattern rule with parent-path matching,
   but the exact behaviour of a bare directory exception after a directory
   exclusion is implementation detail. What would settle it: a plain-progress
   build and the transferred context size, or tarring the context through the
   same matcher.

3. **What actually happens to the release validation with an empty profiles
   variable?** Compose's default omission of inactive-profile services is the
   premise. What would settle it: rendering the release model with and without
   the profile flag and checking whether the backup service appears.

4. **Which of the fifteen services actually restart after a host reboot?** The
   restart policy is declared on all fifteen, but the answer also depends on the
   Docker daemon being enabled at boot and on no operator having stopped a
   container by hand. Nothing in the tree asserts either. What would settle it: a
   daemon enablement check plus a reboot rehearsal on a target host.

5. **Is the wheelhouse ever populated on the release runners?** The workflow build
   step passes no wheelhouse and the directory is git-ignored, so signed release
   images are presumably built through the network branch. Not verified: only the
   workflow text was read, never a runner's filesystem.

6. **Does the ui service's sandbox membership matter outside the channels
   profile?** Its only sandbox peer is the channel gateway, for the voice proxy.
   Under the secure overlay the sandbox becomes internal, which does not remove
   the ui's default-network egress. Whether the membership is load-bearing
   otherwise is not settled by anything in this area's files.

7. **What is the intended posture for the ui and backup services under the
   hardening anchor?** Both are first-party and neither merges it, and unlike
   signal-cli neither carries a comment saying why. The backup service runs as
   root by construction; the ui drops to nginx in its image. Whether the omission
   is deliberate for both, or debt for one, is not answerable from the tree.

8. **Does the named AppArmor profile add two grants over docker-default or
   three?** The profile header and the profile's README disagree and the body
   carries pivot_root. What would settle it: diffing the daemon-generated
   docker-default profile from a host at a named Docker version against
   `deploy/apparmor/boltrig-codex`.

9. **Which stack does the roll script still serve?** It hard-codes a canary
   project name and a tenant path shape, and both deployment documents call it
   non-production. Whether it is still executed on any box is a fact about the
   estate, not about this tree, and nothing in the pinned tree settles it.

## 13. Requirements table

| id | statement | status | evidence | invariant |
| --- | --- | --- | --- | --- |
| BT-REQ-1900 | The base Compose model declares fifteen services and every one carries restart unless-stopped, so no service is left without a restart policy. | IMPLEMENTED-UNTESTED | `docker-compose.yml:45` `restart: unless-stopped` | - |
| BT-REQ-1901 | Three services run the one built fleet image and differ only by command. | IMPLEMENTED | `docker-compose.yml:385` `boltrig.fleet.hatchet_worker` | SEC-137 |
| BT-REQ-1902 | Every third-party image in the Compose model is pinned to a tag plus an explicit sha256 digest. | IMPLEMENTED-UNTESTED | `docker-compose.yml:44` `image: pgvector/pgvector:pg16@sha256:131dcf7ff6a900545df8e7e092c270aa8c6db2f2c818e408cb45ec21316b74e6` | IAC-002 |
| BT-REQ-1903 | The hardening anchor sets a read-only rootfs, a tmpfs, all capabilities dropped, no-new-privileges, a pids limit and a memory limit. | IMPLEMENTED | `docker-compose.yml:27` `x-app-hardening: &app-hardening` | SEC-64 |
| BT-REQ-1904 | Six services merge the hardening anchor: kernel, fleet-worker, browser-executor, hatchet-worker, channel-gateway and whatsapp-bridge. | IMPLEMENTED-UNTESTED | `docker-compose.yml:97` `<<: *app-hardening` | SEC-64 |
| BT-REQ-1905 | The hardening deploy-lint asserts the six properties on only kernel and fleet-worker, leaving the other four merged services unguarded against a regression. | IMPLEMENTED | `tests/security/test_round_seventeen.py:19` `_APP_SERVICES = (` | SEC-64 |
| BT-REQ-1906 | The kernel service runs at uid 0 with SETUID and SETGID re-added after all capabilities are dropped. | IMPLEMENTED-UNTESTED | `docker-compose.yml:120` `cap_add:` | - |
| BT-REQ-1907 | The kernel entrypoint forks a uid-0 spawner, drops the API process to uid 10001 and proves the drop from proc before exec. | IMPLEMENTED | `scripts/kernel-entrypoint.py:91` `drop_privileges(API_UID, API_GID)` | - |
| BT-REQ-1908 | When the capability is absent the kernel entrypoint execs the given command unchanged, introducing no new failure mode. | IMPLEMENTED | `scripts/kernel-entrypoint.py:78` `if not per_cell_uid_mode_available():` | - |
| BT-REQ-1909 | The kernel declares one shared cell root plus four per-slot tmpfs mounts owned by distinct cell uids, all noexec, nosuid and nodev. | IMPLEMENTED-UNTESTED | `docker-compose.yml:150` `- /var/lib/boltrig/codex-cells/slot-0:mode=0700,uid=20001,gid=20001,noexec,nosuid,nodev` | - |
| BT-REQ-1910 | The fleet worker and the hatchet worker declare the same cell-root tmpfs as the kernel because all three run the same boot-time sandbox probe. | IMPLEMENTED-UNTESTED | `docker-compose.yml:247` `- /var/lib/boltrig/codex-cells:mode=0711,uid=10001,gid=10001,noexec,nosuid,nodev` | - |
| BT-REQ-1911 | The kernel container healthcheck probes readiness rather than liveness, so an unapplied migration head makes the container unhealthy. | IMPLEMENTED | `docker-compose.yml:213` `import urllib.request; urllib.request.urlopen('http://localhost:8000/readyz')` | FR-OPS-03 |
| BT-REQ-1912 | The fleet-worker healthcheck reads back the signed stack-tool receipt rather than importing a module. | IMPLEMENTED | `docker-compose.yml:320` `- python -m boltrig.api.cli fleet-health` | FR-OPS-05 |
| BT-REQ-1913 | The hatchet-worker healthcheck probes the SDK listener heartbeat server on container loopback, green only after the worker connected and heartbeated. | IMPLEMENTED | `docker-compose.yml:421` `import urllib.request; urllib.request.urlopen('http://127.0.0.1:8001/health', timeout=3)` | SEC-137 |
| BT-REQ-1914 | The browser-executor healthcheck is a Unix-socket self-probe and the release validator requires it. | IMPLEMENTED | `scripts/validate_release_compose.py:110` `release browser executor has no Unix-socket healthcheck` | SEC-137 |
| BT-REQ-1915 | The hatchet worker depends on the engine with a started condition because the engine declares no healthcheck. | IMPLEMENTED-UNTESTED | `docker-compose.yml:415` `condition: service_started` | - |
| BT-REQ-1916 | The browser executor is the sole member of the browser-egress network, publishes no host port and owns the only Chromium in the deployment. | IMPLEMENTED | `tests/deploy/test_compose_hardening.py:212` `browser-egress` | FR-HOST-11 |
| BT-REQ-1917 | Kernel, fleet worker and hatchet worker reach the browser only through a read-only socket volume and never mount browser state or a personal profile. | IMPLEMENTED | `tests/deploy/test_compose_hardening.py:225` `~/.local` | FR-HOST-11 |
| BT-REQ-1918 | The Hatchet engine and its unauthenticated dashboard publish only on loopback in the base model. | IMPLEMENTED | `tests/deploy/test_compose_hardening.py:72` `def test_hatchet_ports_are_loopback_only_in_base_compose():` | SEC-70 |
| BT-REQ-1919 | The sensitive-data local-model port is loopback-only in base and removed entirely by the secure overlay. | IMPLEMENTED | `tests/deploy/test_compose_hardening.py:98` `def test_local_model_port_is_loopback_only_and_removed_from_secure_compose():` | SEC-70 |
| BT-REQ-1920 | The Postgres password uses the required-var form so the stack refuses to render unset, and the Hatchet connection string interpolates it rather than hardcoding a credential. | IMPLEMENTED | `tests/deploy/test_compose_hardening.py:107` `def test_postgres_password_has_no_literal_default():` | SEC-70 |
| BT-REQ-1921 | The kernel and ui services publish on all host interfaces in the base model; only the dev and secure overlays narrow or remove those bindings. | IMPLEMENTED-UNTESTED | `docker-compose.yml:172` `${KERNEL_PORT:-8000}:8000` | - |
| BT-REQ-1922 | Four profiles keep the model gateway, the on-box model, the channels trio and the backup sidecar out of a bare bring-up. | IMPLEMENTED | `docker-compose.yml:709` `profiles: [` | SEC-71 |
| BT-REQ-1923 | The sandbox network is a plain bridge in the base model and only the secure overlay makes it internal, which the base file states in terms. | IMPLEMENTED-UNTESTED | `docker-compose.yml:751` `# a local gateway. For production, ALWAYS use the secure overlay` | SEC-48 |
| BT-REQ-1924 | The Hatchet config directory is a named volume in the base model so a container recreate cannot mint a new signing keyset. | IMPLEMENTED | `docker-compose.yml:460` `- hatchet_config:/config` | SEC-71 |
| BT-REQ-1925 | The kernel mounts the backup freshness marker read-only and can never read a backup artifact. | IMPLEMENTED | `docker-compose.yml:181` `- backup_health:/run/boltrig-backup-health:ro` | SEC-71 |
| BT-REQ-1926 | A fresh Postgres volume creates the separate Hatchet database through a first-boot hook that validates the name and skips a duplicate create. | IMPLEMENTED | `tests/deploy/test_compose_hardening.py:182` `def test_fresh_postgres_boot_creates_the_separate_hatchet_database() -> None:` | SEC-71 |
| BT-REQ-1927 | The schema file is a first-boot bootstrap only and Alembic is the authoritative upgrade path for an existing deployment. | IMPLEMENTED | `Makefile:343` `migration-parity: ## Compare Alembic head with schema.sql on disposable PostgreSQL` | - |
| BT-REQ-1928 | Redis persists with append-only mode and everysec fsync so relay and counter state survives a container restart. | IMPLEMENTED-UNTESTED | `docker-compose.yml:78` `--appendfsync` | - |
| BT-REQ-1929 | The secure overlay adds a TLS terminator and removes the host ports of kernel, ui, both Hatchet services, the gateway and the local model. | IMPLEMENTED | `tests/deploy/test_compose_hardening.py:87` `def test_secure_overlay_drops_hatchet_host_ports():` | SEC-70 |
| BT-REQ-1930 | The secure overlay makes the sandbox network internal so a sandbox-only service has no route to any external address. | IMPLEMENTED-UNTESTED | `deploy/compose.secure.yml:85` `# Enforce no arbitrary egress for the Pi sidecar (SEC-48). internal: true means` | SEC-48 |
| BT-REQ-1931 | The secure overlay parameterises the Postgres data directory so encryption at rest is a deployment choice with no image change. | IMPLEMENTED-UNTESTED | `deploy/compose.secure.yml:81` `- ${PGDATA_HOST:-pgdata}:/var/lib/postgresql/data` | - |
| BT-REQ-1932 | The dev overlay binds the kernel API to loopback on a non-default port and removes the ui host port so Caddy is the single front door. | IMPLEMENTED-UNTESTED | `deploy/compose.dev.yml:48` `127.0.0.1:${BOLTRIG_DEV_KERNEL_PORT:-18001}:8000` | - |
| BT-REQ-1933 | The dev overlay forces the trusted Codex lane off on both kernel and fleet worker so a namespace restriction cannot become a crash loop. | IMPLEMENTED-UNTESTED | `deploy/compose.dev.yml:53` `BOLTRIG_CODEX_TRUSTED:` | - |
| BT-REQ-1934 | The in-process overlay runs the kernel as uid 10001 and is documented as a single-tenant dev convenience that must not reach a client deployment. | IMPLEMENTED-UNTESTED | `deploy/compose.inprocess.yml:25` `10001:10001` | - |
| BT-REQ-1935 | The VM overlay relaxes only syscall filtering on kernel and fleet worker, retaining the read-only rootfs, the dropped capabilities, no-new-privileges and both resource caps. | IMPLEMENTED-UNTESTED | `docker-compose.vm.yml:70` `- seccomp:unconfined` | - |
| BT-REQ-1936 | The VM overlay enables IPv6 on the app networks because outbound address pinning otherwise selects an address a v4-only container cannot route. | IMPLEMENTED-UNTESTED | `docker-compose.vm.yml:44` `enable_ipv6: true` | - |
| BT-REQ-1937 | The VM overlay is an input to no config step and no test, so it is the one compose manifest that reaches no gate. | IMPLEMENTED | `scripts/check_gate_coverage.py:155` `found = {p.relative_to(ROOT).as_posix() for p in (ROOT /` | - |
| BT-REQ-1938 | Compose validation renders base, base plus channels, secure, dev, inprocess and opbox-link, and pipes two release renders into the release compose validator. | IMPLEMENTED | `tests/deploy/test_compose_hardening.py:120` `def test_compose_validation_is_clean_checkout_safe():` | FR-OPS-02 |
| BT-REQ-1939 | Compose validation runs from a clean checkout using the example env and a validation-only database password, never a developer env file. | IMPLEMENTED | `Makefile:15` `COMPOSE_VALIDATE_POSTGRES_PASSWORD ?= boltrig-compose-validation-only` | FR-OPS-02 |
| BT-REQ-1940 | The gate-coverage gate derives the compose manifest list by globbing rather than listing it, so a new overlay fails the gate on the commit that adds it. | IMPLEMENTED-UNTESTED | `scripts/check_gate_coverage.py:35` `here - so adding a seventh compose manifest or a ninth` | - |
| BT-REQ-1941 | The health-claim gate fails any first-party service whose healthcheck probes liveness on an application that also serves a readiness route. | IMPLEMENTED-UNTESTED | `scripts/check_health_claims.py:26` `registers a readiness path (/readyz, /ready, /readiness), the healthcheck is` | - |
| BT-REQ-1942 | The release overlay resets every first-party build definition, pins each image to a required digest variable and sets an always pull policy. | IMPLEMENTED | `tests/deploy/test_compose_hardening.py:473` `def test_release_compose_uses_only_required_digest_images_without_builds():` | SEC-137 |
| BT-REQ-1943 | The release overlay pins the fleet worker, the browser executor and the hatchet worker to the one signed fleet digest and the validator refuses any divergence. | IMPLEMENTED | `scripts/validate_release_compose.py:90` `release Hatchet worker does not use the fleet-worker image digest` | SEC-137 |
| BT-REQ-1944 | The release overlay removes the developer bind mount of the backup script so the signed backup image cannot execute mutable host source. | IMPLEMENTED | `scripts/validate_release_compose.py:125` `release backup service replaces signed code with a source mount` | SEC-137 |
| BT-REQ-1945 | The release compose validator rejects any active channels-profile service because those images are not in the signed release set. | IMPLEMENTED | `scripts/validate_release_compose.py:49` `release channels posture is not admitted: channel-gateway/` | SEC-137 |
| BT-REQ-1946 | The release image environment must contain exactly four variables, each an immutable digest reference, with no missing and no extra keys. | IMPLEMENTED | `scripts/validate_release_images.py:45` `unexpected release image variables: {', '.join(unexpected)}` | SEC-137 |
| BT-REQ-1947 | The release mode must be exactly core or full and all four release runtime services must agree on the same value. | IMPLEMENTED | `scripts/validate_release_compose.py:70` `release services disagree on BOLTRIG_RELEASE_MODE` | SEC-137 |
| BT-REQ-1948 | The release mode is required by the release overlay and by the runbook but has no line in the example env file. | IMPLEMENTED-UNTESTED | `deploy/compose.release.yml:19` `BOLTRIG_RELEASE_MODE: ${BOLTRIG_RELEASE_MODE:?set BOLTRIG_RELEASE_MODE to exactly core or full}` | - |
| BT-REQ-1949 | The release start target depends on the validation target, so validation reruns immediately before the pull and the start. | IMPLEMENTED | `Makefile:330` `release-up: release-validate ## Pull and start signed release images (secure + backup)` | SEC-137 |
| BT-REQ-1950 | The release start target uses no-build so production can never rebuild mutable source on the target host. | IMPLEMENTED | `Makefile:338` `-f deploy/compose.secure.yml up -d --no-build` | SEC-137 |
| BT-REQ-1951 | The release workflow triggers only on a version tag, serialises on one concurrency group and never cancels in progress. | IMPLEMENTED | `.github/workflows/release.yml:9` `group: boltrig-release` | SEC-137 |
| BT-REQ-1952 | The release preflight requires the tag's commit to be an ancestor of the default branch and both canonical workflows to have succeeded for that exact sha. | IMPLEMENTED | `tests/deploy/test_compose_hardening.py:456` `def test_release_requires_canonical_success_for_the_exact_commit():` | SEC-137 |
| BT-REQ-1953 | The release preflight proves registry write access by opening and cancelling a blob upload, before spending ten minutes on candidate builds. | IMPLEMENTED | `.github/workflows/release.yml:91` `https://ghcr.io/v2/$owner/$pkg/blobs/uploads/` | IAC-005 |
| BT-REQ-1954 | Each candidate image is vulnerability-scanned with the same acceptance file the security gate uses, so the two gates cannot disagree about one image. | IMPLEMENTED | `.github/workflows/release.yml:421` `trivyignores: .trivyignore.yaml` | IAC-005 |
| BT-REQ-1955 | Candidates are pushed only under a run-scoped tag until every digest is signed, SBOM-attested and provenance-bound. | IMPLEMENTED | `.github/workflows/release.yml:341` `CANDIDATE_TAG: candidate-${{ github.run_id }}-${{ github.run_attempt }}` | SEC-137 |
| BT-REQ-1956 | Promotion fetches each signed manifest and refuses to publish unless the bytes hash to the signed digest. | IMPLEMENTED | `.github/workflows/release.yml:1281` `sha256:$(sha256sum manifest.bin` | SEC-137 |
| BT-REQ-1957 | An existing public tag whose digest changed after preflight stops promotion rather than being overwritten. | IMPLEMENTED | `.github/workflows/release.yml:1303` `$image_name:$tag changed to $existing_digest after preflight` | SEC-137 |
| BT-REQ-1958 | The release asset helper never clobbers: an exact retry compares bytes and refuses a difference, and semantic modes verify the attestation for the exact digest. | IMPLEMENTED | `tests/deploy/test_release_asset_reuse.py:144` `def test_exact_asset_retry_reuses_bytes_and_refuses_replacement(tmp_path: Path) -> None:` | IAC-005 |
| BT-REQ-1959 | Only a stable full release may be marked Latest, so a core release or a prerelease cannot displace the desktop updater's manifest. | IMPLEMENTED-UNTESTED | `.github/workflows/release.yml:1348` `latest=(--latest)` | - |
| BT-REQ-1960 | The roll script refuses to run unless its own checkout contains the tag being rolled. | IMPLEMENTED-UNTESTED | `scripts/roll-release.sh:55` `merge-base --is-ancestor` | - |
| BT-REQ-1961 | The roll repins the tracked overlay source, propagates it, and proves the box copy matches by checksum before bringing anything up. | IMPLEMENTED-UNTESTED | `scripts/roll-release.sh:158` `propagated $rel but the box checksum differs ($a vs $b)` | - |
| BT-REQ-1962 | The roll migrates each stack to the head its target image asserts, immediately before that stack's deploy, and never to the checkout's head. | IMPLEMENTED-UNTESTED | `scripts/roll-migrate-stack.sh:49` `python -c 'from boltrig.api.readiness import EXPECTED_ALEMBIC_HEAD as h; print(h)' 2>/dev/null` | - |
| BT-REQ-1963 | A database found ahead of its image is left untouched and the migration gate exits non-zero, naming the situation a rollback that needs a human and a dump. | IMPLEMENTED-UNTESTED | `scripts/roll-migrate-stack.sh:82` `ABORT: schema is ${AFTER:-<empty>}, image asserts $WANT.` | - |
| BT-REQ-1964 | The roll gate asserts kernel health, worker liveness, an expected addons line on both, the running kernel image version, and ui health plus version before proceeding. | IMPLEMENTED-UNTESTED | `scripts/roll-release.sh:292` `$u is running '$uimg', not $VERSION` | - |
| BT-REQ-1965 | The canary stack is rolled and gated before the tenant is touched, and the canary-only flag stops after the canary while saying the fleet is now uneven. | IMPLEMENTED-UNTESTED | `scripts/roll-release.sh:308` `CANARY GATE PASSED - only now is the tenant touched` | - |
| BT-REQ-1966 | The roll script is declared a non-production path in both deployment documents and the canonical procedure is the cutover runbook. | IMPLEMENTED-UNTESTED | `docs/PROD-CUTOVER-RUNBOOK.md:219` `is retained only for legacy/dev investigation. It` | - |
| BT-REQ-1967 | The deployment verifier asserts readiness and the presence of named symbols inside the running container, exiting non-zero if either fails. | IMPLEMENTED-UNTESTED | `scripts/verify-deployment.sh:97` `VERIFY FAILED: ${CONTAINER} is running but not serving what you think` | - |
| BT-REQ-1968 | The backup sidecar ships profile-gated in the base compose, mounts the backup script and a backups directory, and runs the loop as its command. | IMPLEMENTED | `tests/deploy/test_compose_hardening.py:143` `def test_backup_sidecar_ships_profile_gated():` | SEC-71 |
| BT-REQ-1969 | Each backup run refuses any dump the restore tool cannot parse and refuses an empty archive, before any artifact is published. | IMPLEMENTED | `tests/deploy/test_backup_scripts.py:346` `def test_backup_refuses_unparseable_dump_without_success_marker(tmp_path: Path) -> None:` | SEC-71 |
| BT-REQ-1970 | Every backup artifact gets a checksum sidecar that is re-verified after publish, and both files are deleted on a mismatch. | IMPLEMENTED | `tests/deploy/test_backup_scripts.py:149` `def test_backup_verifies_dump_checksum_and_remote_pair(tmp_path: Path) -> None:` | SEC-71 |
| BT-REQ-1971 | The stack-state archive is refused without a passphrase because it carries Hatchet signing material and user Knowledge. | IMPLEMENTED | `tests/deploy/test_backup_scripts.py:329` `def test_backup_refuses_unencrypted_hatchet_signing_state(tmp_path: Path) -> None:` | SEC-71 |
| BT-REQ-1972 | The stack-state tar is piped straight into the encrypter so a killed run can never leave a plaintext archive on disk. | IMPLEMENTED | `tests/deploy/test_backup_scripts.py:268` `def test_sigkill_during_stack_state_backup_never_leaves_a_plaintext_archive(` | SEC-71 |
| BT-REQ-1973 | The recovery-set completion marker is uploaded off-box last, after every artifact and sidecar, so a partial remote run has no complete-set marker. | IMPLEMENTED | `scripts/backup.sh:170` `# artifact and sidecar, so a partial remote run has no complete-set marker.` | SEC-71 |
| BT-REQ-1974 | A configured off-box copy that fails exits non-zero and leaves no success marker, so a broken remote cannot pass silently. | IMPLEMENTED | `tests/deploy/test_backup_scripts.py:362` `def test_backup_remote_failure_leaves_no_success_marker(tmp_path: Path) -> None:` | SEC-71 |
| BT-REQ-1975 | An unset off-box remote warns and continues with a local-only backup, the only deliberately fail-open branch of the backup path. | IMPLEMENTED-UNTESTED | `scripts/backup.sh:128` `WARNING: BACKUP_REMOTE unset - off-box copy skipped (local-only backup)` | SEC-71 |
| BT-REQ-1976 | Retention prunes whole recovery sets rather than individual files, using a while-read loop because the array builtin is unavailable on bash 3.2. | IMPLEMENTED | `scripts/backup.sh:187` `. mapfile is a bash 4 builtin and macOS still` | SEC-71 |
| BT-REQ-1977 | The backup loop lets a failed run exit PID 1 so the restart policy surfaces the failure instead of masking it until the next interval. | IMPLEMENTED | `tests/deploy/test_backup_scripts.py:409` `def test_backup_loop_exits_nonzero_instead_of_masking_failure(tmp_path: Path) -> None:` | SEC-71 |
| BT-REQ-1978 | The backup healthcheck is unhealthy on a missing, malformed, or older-than-interval-plus-grace success marker. | IMPLEMENTED | `tests/deploy/test_backup_scripts.py:425` `def test_backup_healthcheck_rejects_missing_malformed_and_stale_success(tmp_path: Path) -> None:` | SEC-71 |
| BT-REQ-1979 | The recovery-set verifier is read-only and refuses symlinks, tampering, inconsistent sidecars, empty files, unencrypted dumps and foreign artifacts. | IMPLEMENTED | `tests/deploy/test_recovery_set_verifier.py:89` `def test_recovery_set_verifier_rejects_tampering_and_inconsistent_sidecars(` | SEC-71 |
| BT-REQ-1980 | The verifier requires the exact configured database set and refuses both a missing required database and an unexpected extra one. | IMPLEMENTED | `scripts/verify_recovery_set.py:117` `if unexpected:` | SEC-71 |
| BT-REQ-1981 | Every encrypted artifact must carry the OpenSSL salt header or the recovery set is refused. | IMPLEMENTED | `scripts/verify_recovery_set.py:110` `if handle.read(8) != b` | SEC-71 |
| BT-REQ-1982 | The recovery rehearsal refuses a remote or ambiguous Docker endpoint before creating any container. | IMPLEMENTED | `tests/deploy/test_recovery_set_verifier.py:142` `def test_recovery_rehearsal_refuses_remote_docker_and_ambient_database() -> None:` | SEC-71 |
| BT-REQ-1983 | The recovery rehearsal strips any ambient test database URL so it cannot select an operator database. | IMPLEMENTED | `Makefile:355` `env -u BOLTRIG_TEST_DATABASE_URL scripts/with_test_postgres.sh \` | SEC-71 |
| BT-REQ-1984 | The signed release backup archives Hatchet config, Knowledge, libraries and the manifest together under one mandatory-encryption state directory. | IMPLEMENTED | `deploy/compose.release.yml:65` `- hatchet_config:/backup-state/hatchet-config:ro` | SEC-71 |
| BT-REQ-1985 | Redis append-only state is explicitly outside the logical recovery set and connector credential volumes are the deployment's own responsibility. | IMPLEMENTED-UNTESTED | `docs/backup-restore.md:18` `Redis AOF contains bounded relay/counter state, not the recovery authority for` | - |
| BT-REQ-1986 | Restore order requires postgres alone first, both dumps restored, the Hatchet config restored with the engine stopped, then engine, kernel and workers, then readiness. | IMPLEMENTED-UNTESTED | `docs/backup-restore.md:175` `, then kernel,` | - |
| BT-REQ-1987 | The Postgres first-boot hook never reruns against an existing data volume, so an upgraded cluster needs the Hatchet database created explicitly. | IMPLEMENTED | `deploy/postgres-init-hatchet.sh:5` `# existing deployment is never mutated by Compose startup; operators upgrading an` | SEC-71 |
| BT-REQ-1988 | Genesis fills only blank secrets and derives the database URL from the Postgres variables so the two cannot disagree. | IMPLEMENTED-UNTESTED | `genesis.sh:111` `postgresql+asyncpg://${PGUSER}:${PGPW}@postgres:5432/${PGDB}` | - |
| BT-REQ-1989 | Genesis requires an explicit superadmin email and password and bundles no personal or default identity. | IMPLEMENTED-UNTESTED | `genesis.sh:94` `SUPERADMIN_EMAIL is required; no personal default is bundled` | - |
| BT-REQ-1990 | Genesis exits zero after a failed health or login verification, so its exit code does not distinguish a founded stack from a broken one. | IMPLEMENTED-UNTESTED | `genesis.sh:185` `== GENESIS finished with warnings (health=$HZ login=$LOGIN) - check 'compose logs' ==` | - |
| BT-REQ-1991 | Genesis verifies against port 8082 from its own shell, which is not the ui port under the dev overlay's default and does not exist under the secure overlay. | IMPLEMENTED-UNTESTED | `genesis.sh:171` `http://localhost:${WORKER_PORT:-8082}` | - |
| BT-REQ-1992 | The dev bring-up script publishes the tailnet origin whether or not the kernel health poll ever succeeded. | IMPLEMENTED-UNTESTED | `scripts/dev-up.sh:25` `exposing one tailnet origin` | - |
| BT-REQ-1993 | The disk-hygiene script prunes least-destructively first and escalates through shorter retention windows only while still over the threshold. | IMPLEMENTED | `tests/deploy/test_disk_hygiene_escalates.py:123` `def test_escalates_when_the_window_protects_the_garbage(tmp_path: Path) -> None:` | - |
| BT-REQ-1994 | The disk-hygiene script reads the actual reclaimable figure before reporting a cause, and exits non-zero when still over threshold. | IMPLEMENTED | `tests/deploy/test_disk_hygiene_escalates.py:148` `def test_reports_remaining_reclaimable_instead_of_denying_it(tmp_path: Path) -> None:` | - |
| BT-REQ-1995 | The wheelhouse builder downloads one requirement at a time under hash verification and exits non-zero if any requirement is still missing after five passes. | IMPLEMENTED-UNTESTED | `scripts/build-wheelhouse.sh:63` `exit 1` | - |
| BT-REQ-1996 | The kernel image consumes an optional wheelhouse through a bracket-glob copy that is a no-op when the directory is absent, with an identical hash contract in both branches. | IMPLEMENTED-UNTESTED | `deploy/kernel.Dockerfile:68` `COPY deploy/wheelhous[e] /wheelhouse/` | IAC-002 |
| BT-REQ-1997 | Backup credentials are excluded from git and from every Docker build context by matching both the directory and any rclone config at depth. | IMPLEMENTED | `tests/deploy/test_compose_hardening.py:333` `def test_backup_credentials_are_excluded_from_git_and_image_contexts():` | SEC-136 |
| BT-REQ-1998 | The dockerignore exception for the docs directory re-admits the whole tree rather than only the three token files its comment names. | UNCERTAIN | `.dockerignore:42` `!docs/` | - |
| BT-REQ-1999 | The named AppArmor profile's allow list carries mount, umount, userns and pivot_root, and the profile must never be replaced by an unconfined one. | IMPLEMENTED-UNTESTED | `deploy/apparmor/boltrig-codex:28` `pivot_root,` | - |
