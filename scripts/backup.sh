#!/usr/bin/env bash
# Boltrig scheduled backup (M10, SEC-70).
#
# One backup run: pg_dump the durable Postgres state to a timestamped file,
# verify that pg_restore can parse it, optionally encrypt it, write and verify a
# SHA-256 sidecar, prune old local copies, and (when a remote is configured) copy
# both files off-box. Designed for the profile-gated `backup` sidecar in
# docker-compose.yml, but it also runs standalone (cron / systemd timer) - see
# docs/backup-restore.md.
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
#   BACKUP_HEALTH_FILE last-success epoch marker   (default BACKUP_DIR/.last-success)
set -Eeuo pipefail

BACKUP_DIR="${BACKUP_DIR:-/backups}"
BACKUP_KEEP="${BACKUP_KEEP:-7}"
PGDATABASE="${PGDATABASE:-boltrig}"
PGUSER="${PGUSER:-boltrig}"
BACKUP_HEALTH_FILE="${BACKUP_HEALTH_FILE:-${BACKUP_DIR}/.last-success}"

log() { echo "backup: $*"; }
die() { echo "backup: ERROR: $*" >&2; exit 1; }

temporary_files=()
cleanup() {
  local path
  for path in "${temporary_files[@]}"; do
    rm -f -- "$path"
  done
}
trap cleanup EXIT

[[ "$BACKUP_KEEP" =~ ^[0-9]+$ ]] || die "BACKUP_KEEP must be a non-negative integer"
for command in pg_dump pg_restore sha256sum; do
  command -v "$command" >/dev/null 2>&1 || die "$command not found on PATH"
done
mkdir -p "$BACKUP_DIR"

ts="$(date -u +%Y%m%dT%H%M%SZ)"
dump="$BACKUP_DIR/boltrig-${ts}.dump"
dump_tmp="${dump}.tmp.$$"
temporary_files+=("$dump_tmp")

# pg_dump custom format (-Fc): supports selective + parallel restore. PGPASSWORD
# is read from the environment; it is never echoed.
log "dumping ${PGDATABASE} -> ${dump}"
pg_dump -h "${PGHOST:-postgres}" -U "$PGUSER" -d "$PGDATABASE" -Fc -f "$dump_tmp" \
  || die "pg_dump failed"
[[ -s "$dump_tmp" ]] || die "pg_dump produced an empty archive"
log "verifying custom-format archive"
pg_restore --list "$dump_tmp" >/dev/null || die "pg_restore could not parse the archive"

artifact="$dump"
artifact_tmp="$dump_tmp"
if [ -n "${BACKUP_PASSPHRASE:-}" ]; then
  command -v openssl >/dev/null 2>&1 || die "BACKUP_PASSPHRASE set but openssl not found"
  enc="${dump}.enc"
  enc_tmp="${enc}.tmp.$$"
  temporary_files+=("$enc_tmp")
  log "encrypting -> ${enc}"
  openssl enc -aes-256-cbc -pbkdf2 -salt -in "$dump_tmp" -out "$enc_tmp" \
    -pass "env:BACKUP_PASSPHRASE" || die "encryption failed"
  [[ -s "$enc_tmp" ]] || die "encryption produced an empty archive"
  artifact="$enc"
  artifact_tmp="$enc_tmp"
fi

checksum="${artifact}.sha256"
checksum_tmp="${checksum}.tmp.$$"
temporary_files+=("$checksum_tmp")
digest="$(sha256sum "$artifact_tmp")" || die "checksum generation failed"
digest="${digest%% *}"
printf '%s  %s\n' "$digest" "$(basename "$artifact")" >"$checksum_tmp"
mv -- "$artifact_tmp" "$artifact"
mv -- "$checksum_tmp" "$checksum"
if ! (cd "$BACKUP_DIR" && sha256sum --check --status "$(basename "$checksum")"); then
  rm -f -- "$artifact" "$checksum"
  die "checksum verification failed"
fi
log "checksum verified ($(basename "$checksum"))"

# Off-box copy (optional). Skipped cleanly in dev; loud when configured.
if [ -n "${BACKUP_REMOTE:-}" ]; then
  command -v rclone >/dev/null 2>&1 \
    || die "BACKUP_REMOTE=${BACKUP_REMOTE} set but rclone not found (install rclone or bake it into the sidecar image)"
  log "copying archive and checksum off-box -> ${BACKUP_REMOTE}"
  rclone copy "$artifact" "$BACKUP_REMOTE" || die "off-box copy to ${BACKUP_REMOTE} failed"
  rclone copy "$checksum" "$BACKUP_REMOTE" || die "off-box checksum copy to ${BACKUP_REMOTE} failed"
  log "off-box copy ok"
else
  log "WARNING: BACKUP_REMOTE unset - off-box copy skipped (local-only backup)"
fi

# Prune: keep the newest BACKUP_KEEP local archives (dumps + encrypted dumps).
if [ "$BACKUP_KEEP" -gt 0 ]; then
  # A while-read loop, NOT `mapfile`. mapfile is a bash 4 builtin and macOS still
  # ships bash 3.2, where this aborted the prune with
  # "scripts/backup.sh: line 106: mapfile: command not found". The backup itself
  # had already been written at that point, so the visible symptom was not a
  # failed backup: it was archives quietly accumulating forever while every run
  # reported success. Found 2026-08-06 by tests/deploy/test_backup_scripts.py on
  # the M4, which is the only reason it surfaced at all.
  #
  # The loop body is `old+=(...)` and nothing in it reads stdin, so the redirect
  # cannot be eaten out from under the loop.
  old=()
  while IFS= read -r _stale; do
    old+=("$_stale")
  done < <(ls -1t "$BACKUP_DIR"/boltrig-*.dump "$BACKUP_DIR"/boltrig-*.dump.enc 2>/dev/null | tail -n +"$((BACKUP_KEEP + 1))")
  if [ "${#old[@]}" -gt 0 ]; then
    log "pruning ${#old[@]} old archive(s) (keeping ${BACKUP_KEEP})"
    for stale in "${old[@]}"; do
      rm -f -- "$stale" "${stale}.sha256"
    done
  fi
fi

health_tmp="${BACKUP_HEALTH_FILE}.tmp.$$"
temporary_files+=("$health_tmp")
mkdir -p "$(dirname "$BACKUP_HEALTH_FILE")"
date +%s >"$health_tmp"
mv -- "$health_tmp" "$BACKUP_HEALTH_FILE"

log "done (${artifact}; checksum ${checksum})"
