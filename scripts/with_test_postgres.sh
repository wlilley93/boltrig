#!/usr/bin/env bash
# Run a command with an isolated pgvector/PostgreSQL test database.
set -euo pipefail

if (( $# == 0 )); then
  echo "usage: $0 <command> [args ...]" >&2
  exit 2
fi

# CI and operators may provide a managed disposable database. Never replace it.
if [[ -n "${BOLTRIG_TEST_DATABASE_URL:-}" ]]; then
  exec "$@"
fi

command -v docker >/dev/null 2>&1 || {
  echo "docker is required when BOLTRIG_TEST_DATABASE_URL is unset" >&2
  exit 2
}

image="pgvector/pgvector:pg16@sha256:131dcf7ff6a900545df8e7e092c270aa8c6db2f2c818e408cb45ec21316b74e6"
name="boltrig-quality-postgres-$$-${RANDOM}"

cleanup() {
  docker rm -f "$name" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

docker run --detach --rm \
  --name "$name" \
  --env POSTGRES_PASSWORD=boltrig-quality \
  --env POSTGRES_DB=boltrig_test \
  --publish 127.0.0.1::5432 \
  "$image" >/dev/null

ready=0
for _ in $(seq 1 30); do
  if docker exec "$name" pg_isready -U postgres -d boltrig_test >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 1
done
if (( ready == 0 )); then
  docker logs "$name" >&2
  echo "quality PostgreSQL did not become ready" >&2
  exit 1
fi

port="$(docker port "$name" 5432/tcp | head -n 1)"
port="${port##*:}"
export BOLTRIG_TEST_DATABASE_URL="postgresql://postgres:boltrig-quality@127.0.0.1:${port}/boltrig_test"

"$@"
