#!/usr/bin/env bash
# Bring ONE stack's schema to the head its TARGET IMAGE asserts. Runs ON the box.
#
#   roll-migrate-stack.sh <compose-project-prefix> <target-kernel-image>
#     e.g. roll-migrate-stack.sh cv-boltrig ghcr.io/.../boltrig-kernel:v0.4.30@sha256:...
#
# Called by scripts/roll-release.sh immediately before that stack's `compose up`.
# Expects the alembic chain already staged at /tmp/roll-mig (alembic.ini + migrations/),
# which roll-release.sh's stage_migrations() does once per run.
#
# WHY THIS IS A FILE AND NOT A HEREDOC INSIDE roll-release.sh. It was a heredoc first,
# and on 2026-08-06 that heredoc reached the remote bash EMPTY: the ssh ran, returned 0,
# printed nothing, and the gate silently did nothing while reporting success. The
# identical body run as a file worked immediately. A safety gate that can no-op without
# saying so is the exact failure mode this script exists to prevent - it would have
# reported a rolled fleet with an unmigrated database - so the plumbing is now the one
# that is proven to work on this estate: write a file, copy it, execute it.
#
# WHY IT MIGRATES TO THE IMAGE'S HEAD, NOT `upgrade head`. This repo can be ahead of the
# release being rolled, and `upgrade head` would then apply a revision no deployed image
# asserts. A database found AHEAD of its image is left untouched and this exits non-zero:
# that is a rollback, and it needs a human and a verified dump.
#
# WHY A THROWAWAY CONTAINER. The kernel runs ReadonlyRootfs=true, so `docker cp` into it
# fails outright; and the database publishes no host port, so the container must join the
# stack's own network to resolve `postgres` - a name that resolves to a DIFFERENT server
# on other networks of this same box. alembic and psycopg are already in the image; only
# alembic.ini and migrations/ are absent, which /tmp/roll-mig supplies. migrations/env.py
# rewrites the +asyncpg driver to +psycopg itself.
#
# DATABASE_URL is read into a variable HERE and never interpolated into an ssh command
# line: doing that silently corrupted the credential repeatedly during this migration.
set -uo pipefail

P="${1:-}"
IMG="${2:-}"
[ -n "$P" ] && [ -n "$IMG" ] || { echo "usage: $0 <project-prefix> <kernel-image>" >&2; exit 2; }

C="$P-kernel-1"
NET="${P}_default"
MIG=/tmp/roll-mig

[ -f "$MIG/alembic.ini" ] || { echo "  no alembic chain staged at $MIG"; exit 1; }

docker image inspect "$IMG" >/dev/null 2>&1 || docker pull -q "$IMG" >/dev/null 2>&1 \
  || { echo "  could not obtain $IMG"; exit 1; }

WANT=$(docker run --rm "$IMG" \
  python -c 'from boltrig.api.readiness import EXPECTED_ALEMBIC_HEAD as h; print(h)' 2>/dev/null | tr -d '\r')
[ -n "$WANT" ] || { echo "  could not read EXPECTED_ALEMBIC_HEAD from the target image"; exit 1; }

DBURL=$(docker exec "$C" printenv DATABASE_URL 2>/dev/null)
[ -n "$DBURL" ] || { echo "  no DATABASE_URL on $C"; exit 1; }

run() {
  docker run --rm -i --network "$NET" -v "$MIG":/mig:ro -w /mig \
    -e DATABASE_URL="$DBURL" "$IMG" sh -lc "$1" 2>&1
}

# awk, not `tail -1`: `alembic current` prints banner lines too, and the revision is the
# only 4-digit-prefixed token on the line. Matching the SHAPE means a future banner
# change cannot be mistaken for a revision.
head_now() {
  run 'python -m alembic current' \
    | awk 'match($0,/[0-9]{4}_[a-z0-9_]+/){print substr($0,RSTART,RLENGTH); exit}'
}

HAVE=$(head_now)
echo "  image expects: $WANT"
echo "  database at:   ${HAVE:-<empty>}"

if [ "$HAVE" = "$WANT" ]; then
  echo "  [ok] schema already at the head this image asserts - nothing to apply"
  exit 0
fi

echo "  applying the chain up to $WANT (target-image head, NOT the checkout's head)"
run "python -m alembic upgrade '$WANT'" | tail -6 | sed 's/^/    /'

AFTER=$(head_now)
if [ "$AFTER" != "$WANT" ]; then
  echo "  ABORT: schema is ${AFTER:-<empty>}, image asserts $WANT."
  echo "         If the database is AHEAD, this is a rollback: it needs a human and a"
  echo "         verified dump. alembic upgrade cannot and must not walk backwards."
  exit 1
fi
echo "  [ok] schema now $AFTER, matching the image about to be deployed"
