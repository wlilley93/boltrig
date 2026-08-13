#!/usr/bin/env bash
# Official Postgres first-boot hook: create the separate durable Hatchet database.
#
# This runs only while the Postgres image initializes a new data directory. An
# existing deployment is never mutated by Compose startup; operators upgrading an
# older cluster still create/verify this database explicitly before cutover.
set -Eeuo pipefail

hatchet_database="${HATCHET_DATABASE_NAME:-hatchet}"
[[ "$hatchet_database" =~ ^[A-Za-z0-9_-]+$ ]] || {
  echo "postgres init: unsafe HATCHET_DATABASE_NAME" >&2
  exit 1
}

# POSTGRES_DB is already created by the image entrypoint. The normal Boltrig
# configuration uses a separate database, but avoid a duplicate create when an
# operator deliberately chooses the same database for a disposable environment.
if [ "$hatchet_database" != "${POSTGRES_DB:-$POSTGRES_USER}" ]; then
  createdb --username "$POSTGRES_USER" --owner "$POSTGRES_USER" "$hatchet_database"
fi
