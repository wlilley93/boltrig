#!/usr/bin/env bash
# Keep a Docker host off the cliff, and say so BEFORE it falls off.
#
# Written after a production host hit 100% (150G, ZERO bytes free) mid-roll, with
# 141.7GB of images of which 108.5GB was reclaimable. A production host at zero
# bytes cannot write Postgres, rotate a log, or pull an image, and the first
# symptom was a one-line `cp` failing during an unrelated deploy. Nothing had
# warned, because nothing was looking.
#
# Deliberately conservative about what it deletes:
#   - build cache and dangling layers are always safe: nothing references them.
#   - images are only pruned once they are older than RETAIN_HOURS (default 7
#     days), so the last week of tags survives as rollback targets. That matters
#     here: rolling back is done by re-pinning a previous digest, and pruning it
#     turns a 30-second rollback into a rebuild.
#   - `docker image prune -a` NEVER removes an image a container references, so
#     running and stopped containers are unaffected either way.
#
# It reports every time and prunes only when over the threshold, so a routine run
# is a health line rather than a surprise deletion.
#
# Usage:  docker-disk-hygiene.sh [--force]
#   --force  prune regardless of the current usage threshold
#
# Env:
#   DISK_PATH      filesystem to watch          (default /)
#   WARN_PCT       report loudly at or above    (default 80)
#   PRUNE_PCT      prune at or above            (default 85)
#   RETAIN_HOURS   keep images newer than this  (default 168, i.e. 7 days)

set -euo pipefail

DISK_PATH="${DISK_PATH:-/}"
WARN_PCT="${WARN_PCT:-80}"
PRUNE_PCT="${PRUNE_PCT:-85}"
RETAIN_HOURS="${RETAIN_HOURS:-168}"
FORCE=0
[ "${1:-}" = "--force" ] && FORCE=1

usage_pct() { df --output=pcent "$DISK_PATH" | tail -1 | tr -dc '0-9'; }
avail_h()   { df -h --output=avail "$DISK_PATH" | tail -1 | tr -d ' '; }

before_pct="$(usage_pct)"
before_avail="$(avail_h)"
stamp="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"

if [ "$FORCE" -eq 0 ] && [ "$before_pct" -lt "$PRUNE_PCT" ]; then
    level="ok"
    [ "$before_pct" -ge "$WARN_PCT" ] && level="warn"
    echo "$stamp docker-disk-hygiene $level ${DISK_PATH} ${before_pct}% used, ${before_avail} free (prune at ${PRUNE_PCT}%)"
    exit 0
fi

echo "$stamp docker-disk-hygiene pruning: ${DISK_PATH} ${before_pct}% used, ${before_avail} free"

# Least destructive first, so a run that only needed the cheap sweep stops there.
docker builder prune -f >/dev/null 2>&1 || true
if [ "$(usage_pct)" -ge "$PRUNE_PCT" ] || [ "$FORCE" -eq 1 ]; then
    docker image prune -f >/dev/null 2>&1 || true
fi
if [ "$(usage_pct)" -ge "$PRUNE_PCT" ] || [ "$FORCE" -eq 1 ]; then
    docker image prune -a --filter "until=${RETAIN_HOURS}h" -f >/dev/null 2>&1 || true
fi

after_pct="$(usage_pct)"
after_avail="$(avail_h)"
echo "$(date -u '+%Y-%m-%dT%H:%M:%SZ') docker-disk-hygiene done: ${before_pct}% -> ${after_pct}% used, ${before_avail} -> ${after_avail} free (kept images newer than ${RETAIN_HOURS}h)"

# Still over after pruning means the problem is not reclaimable images: volumes,
# logs, or something outside Docker. Exit non-zero so cron mails it rather than
# letting a host walk to zero while a "cleanup ran" line scrolls past.
if [ "$after_pct" -ge "$PRUNE_PCT" ]; then
    echo "$(date -u '+%Y-%m-%dT%H:%M:%SZ') docker-disk-hygiene STILL ${after_pct}% after pruning; reclaimable images are not the cause" >&2
    docker system df >&2 || true
    exit 1
fi
