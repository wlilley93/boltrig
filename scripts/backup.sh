#!/usr/bin/env bash
# Boltrig scheduled backup (M10, SEC-70).
#
# One backup run: pg_dump every configured durable Postgres database, verify that
# pg_restore can parse each archive, optionally encrypt it, and (for a release)
# capture stack file state (Hatchet signing config, knowledge, libraries and
# manifest) with mandatory encryption. Each artifact
# gets a SHA-256 sidecar and a recovery-set manifest is uploaded LAST so a partial
# remote upload can never look complete. Designed for the profile-gated sidecar in
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
#   BACKUP_DATABASES   comma-separated DB recovery set (default PGDATABASE)
#   BACKUP_STATE_DIR   stack state to archive; requires BACKUP_PASSPHRASE
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
BACKUP_DATABASES="${BACKUP_DATABASES:-$PGDATABASE}"
BACKUP_STATE_DIR="${BACKUP_STATE_DIR:-}"
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
[[ "$BACKUP_DATABASES" =~ ^[A-Za-z0-9_-]+(,[A-Za-z0-9_-]+)*$ ]] \
  || die "BACKUP_DATABASES must be a comma-separated list of safe database names"
for command in pg_dump pg_restore sha256sum; do
  command -v "$command" >/dev/null 2>&1 || die "$command not found on PATH"
done
if [ -n "$BACKUP_STATE_DIR" ]; then
  command -v tar >/dev/null 2>&1 || die "tar not found on PATH"
  command -v openssl >/dev/null 2>&1 || die "openssl not found on PATH"
  [ -d "$BACKUP_STATE_DIR" ] || die "BACKUP_STATE_DIR is not a directory"
  [ -n "${BACKUP_PASSPHRASE:-}" ] \
    || die "BACKUP_STATE_DIR contains sensitive state and requires BACKUP_PASSPHRASE"
fi
mkdir -p "$BACKUP_DIR"

ts="$(date -u +%Y%m%dT%H%M%SZ)"
recovery_lines=()

publish_prepared_artifact() { # $1=temporary artifact $2=final artifact path
  local artifact_tmp="$1"
  local artifact="$2"
  local checksum
  local checksum_tmp
  local digest

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
  recovery_lines+=("$digest  $(basename "$artifact")")
  log "checksum verified ($(basename "$checksum"))"

  if [ -n "${BACKUP_REMOTE:-}" ]; then
    rclone copy "$artifact" "$BACKUP_REMOTE" \
      || die "off-box copy to ${BACKUP_REMOTE} failed"
    rclone copy "$checksum" "$BACKUP_REMOTE" \
      || die "off-box checksum copy to ${BACKUP_REMOTE} failed"
  fi
}

publish_artifact() { # $1=temporary plaintext $2=final plaintext path $3=must encrypt
  local plaintext_tmp="$1"
  local plaintext="$2"
  local must_encrypt="$3"
  local artifact_tmp="$plaintext_tmp"
  local artifact="$plaintext"
  local encrypted_tmp

  if [ -n "${BACKUP_PASSPHRASE:-}" ]; then
    command -v openssl >/dev/null 2>&1 \
      || die "BACKUP_PASSPHRASE set but openssl not found"
    artifact="${plaintext}.enc"
    encrypted_tmp="${artifact}.tmp.$$"
    temporary_files+=("$encrypted_tmp")
    log "encrypting -> ${artifact}"
    openssl enc -aes-256-cbc -pbkdf2 -salt -in "$plaintext_tmp" -out "$encrypted_tmp" \
      -pass "env:BACKUP_PASSPHRASE" || die "encryption failed"
    [[ -s "$encrypted_tmp" ]] || die "encryption produced an empty archive"
    artifact_tmp="$encrypted_tmp"
  elif [ "$must_encrypt" = 1 ]; then
    die "refusing to publish signing state without BACKUP_PASSPHRASE"
  fi

  publish_prepared_artifact "$artifact_tmp" "$artifact"
}

if [ -n "${BACKUP_REMOTE:-}" ]; then
  command -v rclone >/dev/null 2>&1 \
    || die "BACKUP_REMOTE=${BACKUP_REMOTE} set but rclone not found (install rclone or bake it into the sidecar image)"
  log "recovery set will be copied off-box -> ${BACKUP_REMOTE}"
else
  log "WARNING: BACKUP_REMOTE unset - off-box copy skipped (local-only backup)"
fi

IFS=',' read -r -a databases <<<"$BACKUP_DATABASES"
for database in "${databases[@]}"; do
  # Preserve the historical short name only for the literal default database.
  # A custom PGDATABASE must remain named in the artifact so recovery
  # verification can bind the dump to its configured logical database.
  if [ "$database" = "boltrig" ]; then
    dump="$BACKUP_DIR/boltrig-${ts}.dump"
  else
    dump="$BACKUP_DIR/boltrig-${database}-${ts}.dump"
  fi
  dump_tmp="${dump}.tmp.$$"
  temporary_files+=("$dump_tmp")
  log "dumping ${database} -> ${dump}"
  pg_dump -h "${PGHOST:-postgres}" -U "$PGUSER" -d "$database" -Fc -f "$dump_tmp" \
    || die "pg_dump failed for ${database}"
  [[ -s "$dump_tmp" ]] || die "pg_dump produced an empty archive for ${database}"
  pg_restore --list "$dump_tmp" >/dev/null \
    || die "pg_restore could not parse the ${database} archive"
  publish_artifact "$dump_tmp" "$dump" 0
done

if [ -n "$BACKUP_STATE_DIR" ]; then
  config="$BACKUP_DIR/boltrig-state-${ts}.tar.gz.enc"
  config_tmp="${config}.tmp.$$"
  temporary_files+=("$config_tmp")
  log "archiving and encrypting stack file state -> ${config}"
  tar -C "$BACKUP_STATE_DIR" -czf - . \
    | openssl enc -aes-256-cbc -pbkdf2 -salt -out "$config_tmp" \
        -pass "env:BACKUP_PASSPHRASE" \
    || die "stack state archive encryption failed"
  [[ -s "$config_tmp" ]] || die "stack state archive encryption produced an empty artifact"
  openssl enc -d -aes-256-cbc -pbkdf2 -in "$config_tmp" \
      -pass "env:BACKUP_PASSPHRASE" \
    | tar -tzf - >/dev/null \
    || die "encrypted stack state archive verification failed"
  publish_prepared_artifact "$config_tmp" "$config"
fi

# This manifest is the recovery-set commit marker. Upload it only after every
# artifact and sidecar, so a partial remote run has no complete-set marker.
recovery_manifest="$BACKUP_DIR/boltrig-${ts}.recovery.sha256"
recovery_manifest_tmp="${recovery_manifest}.tmp.$$"
temporary_files+=("$recovery_manifest_tmp")
printf '%s\n' "${recovery_lines[@]}" >"$recovery_manifest_tmp"
mv -- "$recovery_manifest_tmp" "$recovery_manifest"
(cd "$BACKUP_DIR" && sha256sum --check --status "$(basename "$recovery_manifest")") \
  || die "recovery-set verification failed"
if [ -n "${BACKUP_REMOTE:-}" ]; then
  rclone copy "$recovery_manifest" "$BACKUP_REMOTE" \
    || die "off-box recovery-set marker copy to ${BACKUP_REMOTE} failed"
  log "complete recovery set copied off-box"
fi

# Prune complete recovery sets, not individual files: BACKUP_KEEP means recovery
# points even when one point contains multiple databases and signing config.
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
  old_sets=()
  while IFS= read -r _stale; do
    old_sets+=("$_stale")
  done < <(ls -1t "$BACKUP_DIR"/boltrig-*.recovery.sha256 2>/dev/null | tail -n +"$((BACKUP_KEEP + 1))")
  if [ "${#old_sets[@]}" -gt 0 ]; then
    log "pruning ${#old_sets[@]} old recovery set(s) (keeping ${BACKUP_KEEP})"
    for stale_set in "${old_sets[@]}"; do
      while read -r _digest stale_name; do
        rm -f -- "$BACKUP_DIR/$stale_name" "$BACKUP_DIR/${stale_name}.sha256"
      done <"$stale_set"
      rm -f -- "$stale_set"
    done
  fi
fi

health_tmp="${BACKUP_HEALTH_FILE}.tmp.$$"
temporary_files+=("$health_tmp")
mkdir -p "$(dirname "$BACKUP_HEALTH_FILE")"
date +%s >"$health_tmp"
mv -- "$health_tmp" "$BACKUP_HEALTH_FILE"

log "done ($(basename "$recovery_manifest"))"
