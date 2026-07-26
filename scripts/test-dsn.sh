#!/usr/bin/env bash
# Print the DSN for the local throwaway test database, derived, never remembered.
#
# The Postgres tests need BOLTRIG_TEST_DATABASE_URL, and the dev container
# publishes no host port, so the only route to it is its address on the compose
# network - which CHANGES every time the stack restarts. Hardcoding it has now
# produced two runs of ~137 connection errors that read exactly like real test
# failures, on two different days.
#
# Worse than the churn: 127.0.0.1:5432 IS listening on this kind of box, and it is
# a DIFFERENT Postgres. Reaching for localhost as the obvious fix silently points
# the suite at the wrong server; here it refuses the password, but a box where it
# did not would run the whole store suite against someone else's database.
#
# So: ask Docker, every time, and fail loudly rather than emit a guess.
#
# Usage:  export BOLTRIG_TEST_DATABASE_URL="$(scripts/test-dsn.sh)"
#         make test BOLTRIG_TEST_DATABASE_URL="$(scripts/test-dsn.sh)"
set -euo pipefail

CONTAINER="${BOLTRIG_TEST_PG_CONTAINER:-boltrig-postgres-1}"
DB="${BOLTRIG_TEST_PG_DATABASE:-boltrig_test}"
USER_NAME="${BOLTRIG_TEST_PG_USER:-boltrig}"
PASSWORD="${BOLTRIG_TEST_PG_PASSWORD:-boltrig}"

if ! docker inspect "$CONTAINER" >/dev/null 2>&1; then
    echo "test-dsn: no container '$CONTAINER'. Start the dev stack (make up), or set" >&2
    echo "          BOLTRIG_TEST_PG_CONTAINER to the one holding '$DB'." >&2
    exit 1
fi

ip="$(docker inspect "$CONTAINER" \
    --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{"\n"}}{{end}}' \
    | grep -v '^$' | head -1)"

if [ -z "$ip" ]; then
    echo "test-dsn: '$CONTAINER' has no network address; is it running?" >&2
    exit 1
fi

# A DSN that resolves is not the same as one that reaches the RIGHT database, and
# the wrong one here is silent. Prove the target exists before handing it out.
if ! docker exec "$CONTAINER" psql -U "$USER_NAME" -d postgres -tAc \
        "SELECT 1 FROM pg_database WHERE datname='$DB'" 2>/dev/null | grep -q 1; then
    echo "test-dsn: '$CONTAINER' has no database '$DB'. Create the THROWAWAY one:" >&2
    echo "          docker exec $CONTAINER psql -U $USER_NAME -d postgres -c 'CREATE DATABASE $DB;'" >&2
    echo "          Never point this at a database a running stack serves; these tests write." >&2
    exit 1
fi

printf 'postgresql://%s:%s@%s:5432/%s\n' "$USER_NAME" "$PASSWORD" "$ip" "$DB"
