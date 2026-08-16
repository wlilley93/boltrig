# Backup and restore

Boltrig's application state lives in PostgreSQL; durable Hatchet execution uses
a second PostgreSQL database, and several recovery-critical files live outside
both. A production recovery point is therefore a complete set, not one dump.
Put backups on encrypted media (see `DEPLOYMENT.md`).

## What to back up

1. **PostgreSQL** - the `boltrig` application database and, when durability is
   enabled, the separate `hatchet` database.
2. **Stack file state** - `libraries/`, `manifest.yaml`, canonical Knowledge
   originals, and Hatchet's token-signing `/config`. The signed release backup
   image archives these together with mandatory passphrase encryption.
3. **Secret store** - backed up by Vault/KMS itself, not here. The app DB holds
   only references (SEC-04).

Redis AOF contains bounded relay/counter state, not the recovery authority for
work, audit, HITL, or Hatchet runs, and is not in the logical recovery set. If
optional Bifrost, Signal, WhatsApp, or other connector state is enabled, add its
credential-bearing volume to the deployment's encrypted backup policy and test
its provider-specific recovery separately; the standard set does not claim it.

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

Each run dumps every database in `BACKUP_DATABASES` with `pg_dump -Fc`, refuses
each archive unless `pg_restore --list` can parse it, and atomically promotes it.
The signed release path also archives Hatchet config, canonical Knowledge,
`libraries/`, and `manifest.yaml`. That file-state archive is refused unless
`BACKUP_PASSPHRASE` is set. Every artifact gets a verified `.sha256` sidecar.
The off-box leg uploads a `boltrig-<timestamp>.recovery.sha256` completion marker
last, after every artifact and sidecar, so a partial remote copy never looks like
a restorable set. Retention counts complete recovery sets, not individual files.

Configure it in `.env` (see `.env.example`):

| Var | Meaning | Default |
| --- | --- | --- |
| `BACKUP_INTERVAL` | seconds between runs | `86400` (24h) |
| `BACKUP_HEALTH_GRACE` | extra age allowed before health is stale | `3600` (1h) |
| `BACKUP_KEEP` | local archives to retain | `7` |
| `BACKUP_DATABASES` | comma-separated database recovery set | `boltrig,hatchet` |
| `BACKUP_DIR` | host dir for dumps (bind-mounted) | `./backups` |
| `BACKUP_REMOTE` | rclone remote path (off-box) | unset (local-only) |
| `RCLONE_CONFIG_DIR` | dir holding `rclone.conf` | `./deploy/rclone` |
| `BACKUP_PASSPHRASE` | openssl AES-256 passphrase | required by signed release backup |

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
impossible). The signed release backup refuses to copy its stack-state archive
without encryption because it contains Hatchet signing material and user
Knowledge. The default database archives are
`boltrig-<UTC timestamp>.dump.enc` and
`boltrig-hatchet-<UTC timestamp>.dump.enc`. Custom logical database names are
always encoded as `boltrig-<database>-<UTC timestamp>.dump.enc`, including the
application database selected by `PGDATABASE`; this lets the verifier bind each
dump to the exact configured recovery set. Stack files are
`boltrig-state-<UTC timestamp>.tar.gz.enc`.

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

To restore a sidecar-produced recovery point, select only a timestamp that has a
`.recovery.sha256` completion marker. Keep every named file and sidecar in the
same directory, then verify the set before decrypting anything:

```bash
make recovery-verify \
  RECOVERY_MARKER=/secure/path/boltrig-<ts>.recovery.sha256
# encrypted archive (.dump.enc) -> plaintext custom-format dump
openssl enc -d -aes-256-cbc -pbkdf2 -in boltrig-<ts>.dump.enc \
  -out boltrig-<ts>.dump -pass env:BACKUP_PASSPHRASE
openssl enc -d -aes-256-cbc -pbkdf2 -in boltrig-hatchet-<ts>.dump.enc \
  -out boltrig-hatchet-<ts>.dump -pass env:BACKUP_PASSPHRASE
openssl enc -d -aes-256-cbc -pbkdf2 -in boltrig-state-<ts>.tar.gz.enc \
  -out boltrig-state-<ts>.tar.gz -pass env:BACKUP_PASSPHRASE
pg_restore --list boltrig-<ts>.dump >/dev/null
pg_restore --list boltrig-hatchet-<ts>.dump >/dev/null
docker compose exec -T postgres pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  --clean --if-exists < boltrig-<ts>.dump
```

For custom database names, add
`RECOVERY_DATABASES=<application>,<hatchet>` to `make recovery-verify`, matching
the exact `BACKUP_DATABASES` set used to create the recovery point.

`recovery-verify` is deliberately read-only. It requires the Boltrig and Hatchet
database archives and encrypted stack-state archive for one exact timestamp,
rejects symlinks, unexpected artifacts, malformed or duplicate marker entries,
missing/inconsistent sidecars, empty files, checksum mismatches, and encrypted
files without an OpenSSL salt header. It does not need the backup passphrase.

For an unencrypted archive, check `boltrig-<ts>.dump.sha256` and run the same
`pg_restore --list` validation directly against the `.dump` before restore.

Restore order for a full rebuild, inside a maintenance window with all writers
stopped:

1. Bring up only `postgres`. A new data volume runs
   `deploy/postgres-init-hatchet.sh` and creates the separate `hatchet` database;
   create/verify it explicitly when restoring into an existing cluster, because
   official Postgres first-boot hooks never rerun against an existing data volume.
2. Restore both verified dumps with `pg_restore --clean --if-exists` into their
   matching databases.
3. With `hatchet-engine` stopped, restore `hatchet-config/` into the
   `hatchet_config` volume. Restore Knowledge, `libraries/`, and `manifest.yaml`
   to their matching deployment-owned locations. Preserve ownership and modes.
4. Start `hatchet-engine`, then kernel, `fleet-worker`, and `hatchet-worker`.
   Existing `HATCHET_CLIENT_TOKEN` values remain valid only when the matching
   Hatchet config archive was restored.
5. Require `/readyz` 200, a healthy fleet receipt, and a real durable staging run
   before returning traffic.

## In-flight runs after restore

- Work items and the kanban come back with the database, so the board renders the
  restored state immediately.
- Blocking HITL pauses are durable (NFR-REL-01): a pending approval survives the
  restore and resumes on answer.
- Full durable run-resume of long/recursive runs is owned by Hatchet; restore its
  engine database alongside Boltrig's so paused runs continue. Without Hatchet the
  local executor does not resume across a restart (it is the dev fallback).

## Verify a restore

Rehearse on a disposable Compose project and explicitly named disposable
volumes—never remove a volume selected by command substitution from a production
project. Confirm work/audit/HITL rows, Knowledge originals, Hatchet token validity,
and one durable pause/resume flow. Record the recovery timestamp, elapsed restore
time, Alembic head, and acceptance result. A backup that has never completed this
rehearsal is not cutover evidence.

The repository's non-destructive database-contract rehearsal always provisions
its own disposable PostgreSQL container and ignores any ambient test database
URL, so it cannot accidentally select an operator database. It also refuses
remote or ambiguous Docker endpoints before creating the container:

```bash
make recovery-rehearsal
```

That target proves the repository's dump/restore mechanics. Production evidence
still requires restoring the selected encrypted off-box recovery set into a
separately authorised disposable environment and running the acceptance checks
above; the target does not claim to have rehearsed operator data.
