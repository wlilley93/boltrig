#!/usr/bin/env bash
# Healthy only after a complete backup run and while that success remains fresh.
set -euo pipefail

backup_dir="${BACKUP_DIR:-/backups}"
health_file="${BACKUP_HEALTH_FILE:-${backup_dir}/.last-success}"
interval="${BACKUP_INTERVAL:-86400}"
grace="${BACKUP_HEALTH_GRACE:-3600}"

[[ "$interval" =~ ^[1-9][0-9]*$ ]] || exit 1
[[ "$grace" =~ ^[0-9]+$ ]] || exit 1
[[ -s "$health_file" ]] || exit 1

IFS= read -r last_success <"$health_file"
[[ "$last_success" =~ ^[0-9]+$ ]] || exit 1
now="$(date +%s)"
age="$((now - last_success))"
maximum_age="$((interval + grace))"

[[ "$age" -ge 0 && "$age" -le "$maximum_age" ]]
