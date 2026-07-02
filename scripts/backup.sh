#!/usr/bin/env bash
# Boltrig scheduled backup (M10, SEC-70).
#
# One backup run: pg_dump the durable Postgres state to a timestamped file,
# optionally encrypt it, prune old local copies, and (when a remote is
# configured) copy the archive off-box. Designed for the profile-gated `backup`
# sidecar in docker-compose.yml, but it also runs standalone (cron / systemd
# timer) - see docs/backup-restore.md.
#
# Off-box + encryption are OPTIONAL and fail LOUDLY when misconfigured:
#   - BACKUP_REMOTE unset  -> off-box copy is skipped with a warning (dev-safe).
#   - BACKUP_REMOTE set    -> a failed copy (or a missing rclone) exits non-zero,
#                             so a broken remote can never pass silently.
#
# Config (env):
#   PGHOST PGUSER PGPASSWORD PGDATABASE  standard libpq vars (the sidecar sets them)
#   BACKUP_DIR         where dumps land            (default /backups)
#   BACKUP_KEEP        local dumps to retain       (default 7)
#   BACKUP_REMOTE      rclone remote path          (unset => local-only)
#   BACKUP_PASSPHRASE  openssl AES-256 passphrase  (unset => no encryption)
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/backups}"
BACKUP_KEEP="${BACKUP_KEEP:-7}"
PGDATABASE="${PGDATABASE:-boltrig}"
PGUSER="${PGUSER:-boltrig}"

log() { echo "backup: $*"; }
die() { echo "backup: ERROR: $*" >&2; exit 1; }

command -v pg_dump >/dev/null 2>&1 || die "pg_dump not found on PATH"
mkdir -p "$BACKUP_DIR"

ts="$(date -u +%Y%m%dT%H%M%SZ)"
dump="$BACKUP_DIR/boltrig-${ts}.dump"

# pg_dump custom format (-Fc): supports selective + parallel restore. PGPASSWORD
# is read from the environment; it is never echoed.
log "dumping ${PGDATABASE} -> ${dump}"
pg_dump -h "${PGHOST:-postgres}" -U "$PGUSER" -d "$PGDATABASE" -Fc -f "$dump" \
  || die "pg_dump failed"

artifact="$dump"
if [ -n "${BACKUP_PASSPHRASE:-}" ]; then
  command -v openssl >/dev/null 2>&1 || die "BACKUP_PASSPHRASE set but openssl not found"
  enc="${dump}.enc"
  log "encrypting -> ${enc}"
  openssl enc -aes-256-cbc -pbkdf2 -salt -in "$dump" -out "$enc" \
    -pass "env:BACKUP_PASSPHRASE" || die "encryption failed"
  rm -f "$dump"
  artifact="$enc"
fi

# Off-box copy (optional). Skipped cleanly in dev; loud when configured.
if [ -n "${BACKUP_REMOTE:-}" ]; then
  command -v rclone >/dev/null 2>&1 \
    || die "BACKUP_REMOTE=${BACKUP_REMOTE} set but rclone not found (install rclone or bake it into the sidecar image)"
  log "copying $(basename "$artifact") off-box -> ${BACKUP_REMOTE}"
  rclone copy "$artifact" "$BACKUP_REMOTE" || die "off-box copy to ${BACKUP_REMOTE} failed"
  log "off-box copy ok"
else
  log "WARNING: BACKUP_REMOTE unset - off-box copy skipped (local-only backup)"
fi

# Prune: keep the newest BACKUP_KEEP local archives (dumps + encrypted dumps).
if [ "$BACKUP_KEEP" -gt 0 ] 2>/dev/null; then
  mapfile -t old < <(ls -1t "$BACKUP_DIR"/boltrig-*.dump "$BACKUP_DIR"/boltrig-*.dump.enc 2>/dev/null | tail -n +"$((BACKUP_KEEP + 1))")
  if [ "${#old[@]}" -gt 0 ]; then
    log "pruning ${#old[@]} old archive(s) (keeping ${BACKUP_KEEP})"
    rm -f "${old[@]}"
  fi
fi

log "done (${artifact})"
