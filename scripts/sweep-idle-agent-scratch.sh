#!/usr/bin/env bash
# Reclaim agent scratch from a quota-bound /tmp, without touching a live session.
#
# Written after every shell command in a session started returning exit 1 with no
# output - including `true`. The cause was not disk: the filesystem had space. It
# was the per-user QUOTA on a tmpfs /tmp. The agent harness captures each
# command's stdout to a file under /tmp, so once the quota is reached that
# capture fails with EDQUOT and the tool reports a bare exit 1 for everything.
# The failure mode gives no clue what it is, which is why this exists.
#
# The safety rule is the whole design: a session directory is removed ONLY when
# its most recently written file is older than IDLE_HOURS. A live session writes
# constantly, so it can never be selected. Do not "improve" this into a
# size-ordered sweep: the largest directories are usually the busiest, which is
# exactly backwards.
#
# Usage:  sweep-idle-agent-scratch.sh [--dry-run]
# Env:
#   SCRATCH_GLOB  session dirs to consider (default /tmp/claude-*/*/*/)
#   IDLE_HOURS    remove only if untouched this long (default 24)

set -uo pipefail

SCRATCH_GLOB="${SCRATCH_GLOB:-/tmp/claude-*/*/*/}"
IDLE_HOURS="${IDLE_HOURS:-24}"
DRY=0
[ "${1:-}" = "--dry-run" ] && DRY=1

now=$(date +%s)
cutoff=$(( IDLE_HOURS * 3600 ))
freed=0
kept=0

for dir in $SCRATCH_GLOB; do
    [ -d "$dir" ] || continue
    newest=$(find "$dir" -type f -printf '%T@\n' 2>/dev/null | sort -rn | head -1 | cut -d. -f1)
    size=$(du -sk "$dir" 2>/dev/null | cut -f1)
    [ -z "$size" ] && size=0
    # No files at all is a leftover skeleton, not a session idle since the epoch.
    # Say so, rather than reporting an age computed from a zero timestamp.
    if [ -z "$newest" ]; then
        label="empty"
        stale=1
    else
        label="idle $(( (now - newest) / 3600 ))h"
        stale=0
        [ "$(( now - newest ))" -ge "$cutoff" ] && stale=1
    fi
    if [ "$stale" -eq 1 ]; then
        if [ "$DRY" -eq 1 ]; then
            echo "would remove ${dir} (${label}, $(( size / 1024 ))MB)"
        else
            rm -rf "$dir" && echo "removed ${dir} (${label}, $(( size / 1024 ))MB)"
        fi
        freed=$(( freed + size ))
    else
        kept=$(( kept + 1 ))
    fi
done

echo "$(date -u '+%Y-%m-%dT%H:%M:%SZ') sweep-idle-agent-scratch: reclaimed $(( freed / 1024 ))MB, kept ${kept} active session(s), threshold ${IDLE_HOURS}h"
df -h /tmp 2>/dev/null | tail -1
