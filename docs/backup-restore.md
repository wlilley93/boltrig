# Backup and restore

Boltrig's durable state lives in one PostgreSQL database (work items, registry,
audit, HITL, library metadata, budgets). Backing that up plus the library
artefacts restores the fleet (DoD item 7). Put backups on encrypted media (see
`DEPLOYMENT.md`).

## What to back up

1. **PostgreSQL** - the whole `boltrig` database (the durable Store, S6).
2. **Library artefacts** - `libraries/` (skills, workflows, prompts) and
   `manifest.yaml`. These are data, version them in git or snapshot them.
3. **Secret store** - backed up by Vault/KMS itself, not here. The app DB holds
   only references (SEC-04).

## Backup

```bash
make backup                 # -> ./backups/boltrig.dump (pg_dump custom format)
# or explicitly:
docker compose exec -T postgres pg_dump -U boltrig -d boltrig -Fc > backups/boltrig.dump
```

The custom format (`-Fc`) supports selective, parallel restore.

## Scheduled off-box backup (M10, SEC-70)

`make backup` is a manual, same-host dump. For a self-hosted deployment with a
durable audit chain, a single disk failure between manual runs is total loss, so
the stack ships a scheduled + off-box path: the profile-gated `backup` sidecar in
`docker-compose.yml`, which loops `scripts/backup.sh`.

It is profile-gated, so the default (dev) stack is unaffected. Enable it with:

```bash
docker compose --profile backup up -d backup
```

Each run does: `pg_dump -Fc` to a temporary file under `BACKUP_DIR`, refuses the
archive unless `pg_restore --list` can parse it, atomically promotes it, applies
optional passphrase encryption, writes and rechecks a portable `.sha256` sidecar,
prunes to the newest `BACKUP_KEEP` archive/checksum pairs, and (when
`BACKUP_REMOTE` is set) copies both files off-box via rclone.

Configure it in `.env` (see `.env.example`):

| Var | Meaning | Default |
| --- | --- | --- |
| `BACKUP_INTERVAL` | seconds between runs | `86400` (24h) |
| `BACKUP_HEALTH_GRACE` | extra age allowed before health is stale | `3600` (1h) |
| `BACKUP_KEEP` | local archives to retain | `7` |
| `BACKUP_DIR` | host dir for dumps (bind-mounted) | `./backups` |
| `BACKUP_REMOTE` | rclone remote path (off-box) | unset (local-only) |
| `RCLONE_CONFIG_DIR` | dir holding `rclone.conf` | `./deploy/rclone` |
| `BACKUP_PASSPHRASE` | openssl AES-256 passphrase | unset (no encryption) |

Off-box copy and encryption are OPTIONAL and fail loudly when misconfigured:

- `BACKUP_REMOTE` **unset** -> the dump is written locally and the run warns that
  the off-box leg was skipped (safe for dev).
- `BACKUP_REMOTE` **set** -> a failed copy (or a missing `rclone`) exits non-zero,
  so a broken remote can never pass silently. Point it at any rclone backend
  (S3, B2, GCS, SFTP, etc.), e.g. `BACKUP_REMOTE=s3:my-bucket/boltrig`, and mount
  your configured `rclone.conf` via `RCLONE_CONFIG_DIR`.

The backup container becomes healthy only after the complete local and configured
off-box run has updated its last-success marker. A missing, malformed, or older
than `BACKUP_INTERVAL + BACKUP_HEALTH_GRACE` marker is unhealthy. Any dump,
verification, encryption, checksum, or upload failure exits PID 1 non-zero; the
Compose restart policy retries the container and the failure is visible as a
restart instead of being hidden until the next interval.

Set `BACKUP_PASSPHRASE` to encrypt each archive at rest before it is written or
copied off-box; keep the passphrase in your secret store (without it a restore is
impossible). The archives are `boltrig-<UTC timestamp>.dump` (or `.dump.enc`).

### systemd-timer alternative

If you would rather not run the sidecar, `scripts/backup.sh` runs standalone with
the same env vars (it uses libpq's `PGHOST`/`PGUSER`/`PGPASSWORD`/`PGDATABASE`).
Drop a unit + timer on the host:

```ini
# /etc/systemd/system/boltrig-backup.service
[Service]
Type=oneshot
EnvironmentFile=/opt/boltrig/.env
Environment=PGHOST=127.0.0.1 BACKUP_DIR=/var/backups/boltrig
ExecStart=/opt/boltrig/scripts/backup.sh

# /etc/systemd/system/boltrig-backup.timer
[Timer]
OnCalendar=daily
Persistent=true
[Install]
WantedBy=timers.target
```

Then `systemctl enable --now boltrig-backup.timer`. `pg_dump`, `rclone` and
`openssl` must be installed on the host for this path.

## Restore

```bash
make restore                # restores ./backups/boltrig.dump into the postgres service
# or explicitly:
docker compose exec -T postgres pg_restore -U boltrig -d boltrig --clean --if-exists < backups/boltrig.dump
```

To restore a sidecar-produced archive, pick the timestamped file and verify its
sidecar before decrypting or restoring it. The sidecar contains only the basename,
so keep both files in the same directory:

```bash
sha256sum --check boltrig-<ts>.dump.enc.sha256
# encrypted archive (.dump.enc) -> plaintext custom-format dump
openssl enc -d -aes-256-cbc -pbkdf2 -in boltrig-<ts>.dump.enc \
  -out boltrig-<ts>.dump -pass env:BACKUP_PASSPHRASE
pg_restore --list boltrig-<ts>.dump >/dev/null
docker compose exec -T postgres pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  --clean --if-exists < boltrig-<ts>.dump
```

For an unencrypted archive, check `boltrig-<ts>.dump.sha256` and run the same
`pg_restore --list` validation directly against the `.dump` before restore.

Restore order for a full rebuild:

1. Bring up `postgres` (the idempotent `schema.sql` initialises an empty DB).
2. `make restore` to load the dump (`--clean --if-exists` replaces objects).
3. Restore `libraries/` + `manifest.yaml` from their snapshot.
4. Start `kernel` and `fleet-worker`.

## In-flight runs after restore

- Work items and the kanban come back with the database, so the board renders the
  restored state immediately.
- Blocking HITL pauses are durable (NFR-REL-01): a pending approval survives the
  restore and resumes on answer.
- Full durable run-resume of long/recursive runs is owned by Hatchet; restore its
  engine database alongside Boltrig's so paused runs continue. Without Hatchet the
  local executor does not resume across a restart (it is the dev fallback).

## Verify a restore

```bash
make backup
docker compose down && docker volume rm $(docker compose config --volumes | head -1) 2>/dev/null || true
docker compose up -d postgres && sleep 5 && make restore
curl -s localhost:8000/v1/work -H 'x-boltrig-tenant: <tenant>' -H 'x-boltrig-role: org-admin'
# the restored work items should be listed
```
