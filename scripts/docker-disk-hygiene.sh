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
#   RETAIN_LADDER  shorter windows to escalate through if still over
#                  (default "72 24 6"; set empty to disable escalation)

set -euo pipefail

DISK_PATH="${DISK_PATH:-/}"
WARN_PCT="${WARN_PCT:-80}"
PRUNE_PCT="${PRUNE_PCT:-85}"
RETAIN_HOURS="${RETAIN_HOURS:-168}"
# Windows to fall back through when the 168h pass reclaims nothing. See the
# escalation block below for why a single window cannot bound disk use.
RETAIN_LADDER="${RETAIN_LADDER:-72 24 6}"
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

# ESCALATE, because one fixed window bounds AGE and the release cadence sets
# VOLUME. On 2026-08-23 this script ran at 03:17, reclaimed nothing (89% -> 89%)
# and reported "reclaimable images are not the cause" while `docker system df`
# on the very next line said 80.89GB of images were reclaimable: fifteen
# releases had been rolled in four days, so every untagged image was newer than
# 168h and the window was protecting precisely the garbage it exists to remove.
# Six hours later the host reached 100% and a client tenant's UI crash-looped on
# `No space left on device` in the middle of a roll.
#
# This cannot pull an image out from under a running container: `prune -a` skips
# images a container references, and nothing here passes `-f` to `rmi`. The only
# thing a shorter window costs is a rollback target, which is the cheaper loss.
last_window="$RETAIN_HOURS"
for window in $RETAIN_LADDER; do
    [ "$(usage_pct)" -ge "$PRUNE_PCT" ] || break
    echo "$(date -u '+%Y-%m-%dT%H:%M:%SZ') docker-disk-hygiene still $(usage_pct)% after until=${last_window}h; escalating to until=${window}h"
    docker image prune -a --filter "until=${window}h" -f >/dev/null 2>&1 || true
    last_window="$window"
done

after_pct="$(usage_pct)"
after_avail="$(avail_h)"
echo "$(date -u '+%Y-%m-%dT%H:%M:%SZ') docker-disk-hygiene done: ${before_pct}% -> ${after_pct}% used, ${before_avail} -> ${after_avail} free (kept images newer than ${RETAIN_HOURS}h)"

# Still over after pruning. Exit non-zero so cron mails it rather than letting a
# host walk to zero while a "cleanup ran" line scrolls past.
#
# READ THE NUMBER, DO NOT ASSERT IT. This used to state flatly that "reclaimable
# images are not the cause" - a conclusion it never tested, printed directly
# above a `docker system df` reporting 80.89GB reclaimable. The one run where
# the message mattered, it pointed the reader away from the actual cause.
if [ "$after_pct" -ge "$PRUNE_PCT" ]; then
    # NO `exit` IN THE AWK. `awk '...{print; exit}'` closes the pipe while
    # `docker system df` is still writing, docker takes SIGPIPE and returns 141,
    # and `set -o pipefail` + `set -e` then kill this script HERE - silently,
    # with the diagnostic below never printed and nothing on stderr to explain
    # it. Whether it fires depends on whether the producer's output fits the pipe
    # buffer, so the short real `docker system df` usually survives and a longer
    # one does not: measured 2026-08-24, the same pipeline exits 141 with a
    # 201-line producer and 0 with a 5-line one. A reporting path that dies
    # under load is worse than the wrong message it replaced.
    # Family: SIGPIPE, same shape as `grep -q` closing its own producer.
    img_reclaimable="$(docker system df --format '{{.Type}}|{{.Reclaimable}}' 2>/dev/null \
        | awk -F'|' '$1=="Images" && !seen {print $2; seen=1}')"
    case "${img_reclaimable:-}" in
        ""|0B*|"0 B"*)
            echo "$(date -u '+%Y-%m-%dT%H:%M:%SZ') docker-disk-hygiene STILL ${after_pct}% after pruning; no reclaimable images remain, so the cause is outside Docker images (volumes, logs, or host files)" >&2 ;;
        *)
            echo "$(date -u '+%Y-%m-%dT%H:%M:%SZ') docker-disk-hygiene STILL ${after_pct}% after pruning; ${img_reclaimable} of images are STILL reclaimable - they are in use, or newer than the shortest window tried (until=${last_window}h). Lower RETAIN_LADDER or stop the containers holding them" >&2 ;;
    esac
    docker system df >&2 || true
    exit 1
fi
