#!/usr/bin/env bash
# Run backups on a fixed interval. A failed backup is intentionally not caught:
# PID 1 exits non-zero and the container restart policy makes the failure visible.
set -Eeuo pipefail

interval="${BACKUP_INTERVAL:-86400}"
backup_command="${BACKUP_COMMAND:-/usr/local/bin/backup.sh}"

[[ "$interval" =~ ^[1-9][0-9]*$ ]] || {
  echo "backup: ERROR: BACKUP_INTERVAL must be a positive integer" >&2
  exit 1
}
[[ -x "$backup_command" ]] || {
  echo "backup: ERROR: backup command is not executable: ${backup_command}" >&2
  exit 1
}

while true; do
  "$backup_command"
  sleep "$interval"
done
