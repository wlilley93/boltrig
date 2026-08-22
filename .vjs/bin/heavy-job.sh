#!/usr/bin/env bash
#
# heavy-job.sh - ONE machine-wide gate in front of every memory-hungry job on a
# box, whichever repo starts it.
#
#   scripts/heavy-job.sh [--floor MB] [--wait SEC] [--label NAME] -- <command> [args...]
#
# WHY THIS EXISTS, MEASURED NOT RECALLED
# 2026-08-19 12:18:17, the beelink (18GB, no GPU):
#
#   Out of memory: Killed process 1710101 (MainThread)
#   total-vm:50191116kB, anon-rss:9316748kB
#   task_memcg=/user.slice/.../tmux-spawn-632b518a-....scope
#
# That was `next build --webpack`. It reached 9.3GB beside a `pre-push` gate
# running `eslint .` at 1.9GB, on a box with 1.3GB free. The build was not the
# casualty that mattered: it died inside a systemd tmux-spawn scope, systemd
# marked the whole scope `Failed with result 'oom-kill'`, and the scope dying took
# the PANE with it. Two Claude sessions vanished mid-sentence. See
# scripts/session-restore.sh for the other half - getting them back.
#
# THE THREE THINGS THAT FAILED, AND WHICH THIS FIXES
#
#   1. THE LOCK WAS REAL BUT NARROW. opbox has scripts/opbox-build-lock, a proper
#      machine-wide flock. Only `docker build` and `npm run build` took it. Its own
#      pre-push ran tsc at an 8GB heap, eslint over the whole repo, and the full
#      vitest suite - none of them taking it. So opbox's gate raced opbox's own
#      build, and no other repo took that lock at all. A lock one repo honours is
#      not a machine-wide lock; it is a convention with one participant.
#
#   2. THERE WAS NO FLOOR. A lock answers "is something else running". It never
#      answers "is there room". Both jobs were entitled to start on a box that had
#      no headroom for either, and neither asked.
#
#   3. THE CEILING WAS NOT THE CEILING. OPBOX_BUILD_HEAP_MB=8192 caps V8's heap.
#      The process that killed the pane reached 9.3GB RSS. A heap cap is not an RSS
#      cap - native allocations, mmap'd source maps and worker threads all sit
#      outside it. Anyone reading `--max-old-space-size=8192` and concluding "so it
#      cannot exceed 8GB" is reading a different guarantee from the one enforced.
#      THIS SCRIPT DOES NOT FIX (3). It cannot: refusing to start is not the same as
#      capping growth, and only a cgroup (systemd-run --scope -p MemoryMax=) can
#      actually bound RSS. That is deliberately out of scope here and said out loud
#      rather than left for someone to assume.
#
# WHAT IT GUARANTEES
#   - Serialised: one heavy job at a time per box, across ALL repos, via one lock.
#   - Floored: the job does not START unless MemAvailable clears --floor.
#   - Loud: if the floor is not met within --wait it FAILS, non-zero, with the
#     numbers. It does not shrug and run anyway, and it does not hang forever.
#
# WHY IT LOCKS FIRST AND CHECKS MEMORY SECOND
# The intuitive order - wait for room, then take the lock - is a race: two jobs
# both see room, both proceed, both start. Holding the lock while waiting is what
# makes the floor mean anything, because the winner is the only candidate.
#
# HOW A REPO JOINS
#   pre-push / Makefile:  scripts/heavy-job.sh -- npx vitest run
#   opbox specifically:   export OPBOX_BUILD_LOCK="$VJS_HEAVY_LOCK"
#     so opbox-build-lock's flock lands on the SAME file as this one. Two lock
#     files is two locks, and two locks is no lock - they must be one path.
#
set -uo pipefail

FLOOR_MB="${VJS_HEAVY_FLOOR_MB:-4000}"
WAIT_SEC="${VJS_HEAVY_WAIT_SEC:-1800}"
LABEL=""
LOCK="${VJS_HEAVY_LOCK:-$HOME/.cache/vjs/heavy.lock}"

while [ $# -gt 0 ]; do
  case "$1" in
    --floor) FLOOR_MB="${2:?--floor needs MB}"; shift 2 ;;
    --wait)  WAIT_SEC="${2:?--wait needs seconds}"; shift 2 ;;
    --label) LABEL="${2:?--label needs a name}"; shift 2 ;;
    --lock)  LOCK="${2:?--lock needs a path}"; shift 2 ;;
    --)      shift; break ;;
    -h|--help) sed -n '2,60p' "$0"; exit 0 ;;
    *) echo "heavy-job: unknown argument '$1' (did you forget --?)" >&2; exit 2 ;;
  esac
done

[ "$#" -gt 0 ] || { echo "heavy-job: no command given. Usage: heavy-job.sh [opts] -- <command>" >&2; exit 2; }
[ -n "$LABEL" ] || LABEL="$1"

mkdir -p "$(dirname "$LOCK")"

# MemAvailable, not "free". `free` excludes reclaimable page cache and so reports
# a box as full when it is not; MemAvailable is the kernel's own estimate of what
# a new allocation can actually get. Reading the wrong line here would make the
# floor fire constantly and get the guard disabled, which protects nothing.
avail_mb() { awk '/MemAvailable/{print int($2/1024); found=1} END{if(!found) print 999999}' /proc/meminfo 2>/dev/null || echo 999999; }

if [ ! -r /proc/meminfo ]; then
  # macOS and anything else without /proc: serialise, but do not pretend to floor.
  # Announcing the absent half is the point - a guard that silently degrades to
  # half a guard is worse than one that says which half it is running.
  echo "[heavy-job] no /proc/meminfo on this platform: serialising only, NO memory floor." >&2
fi

run_it() {
  start_wait=$(date +%s)
  announced=0
  while [ "$(avail_mb)" -lt "$FLOOR_MB" ]; do
    now=$(date +%s)
    elapsed=$(( now - start_wait ))
    if [ "$elapsed" -ge "$WAIT_SEC" ]; then
      now_mb="$(avail_mb)"
      echo "" >&2
      echo "[heavy-job] REFUSING to start '$LABEL'." >&2
      echo "            MemAvailable ${now_mb} MB is below the ${FLOOR_MB} MB floor," >&2
      echo "            and has been for ${elapsed}s (limit ${WAIT_SEC}s)." >&2
      echo "" >&2
      echo "            This is the guard working, not a bug. On 2026-08-19 a job started" >&2
      echo "            in this state reached 9.3GB and the kernel OOM-killer took two" >&2
      echo "            tmux panes with it." >&2
      echo "" >&2
      echo "            Free memory and retry, or override deliberately:" >&2
      echo "              VJS_HEAVY_FLOOR_MB=0 <your command>" >&2
      return 75   # EX_TEMPFAIL: a retry may succeed. Not a failure of the command.
    fi
    if [ "$announced" -eq 0 ]; then
      echo "[heavy-job] '$LABEL' holding: MemAvailable $(avail_mb) MB < floor ${FLOOR_MB} MB. Waiting up to ${WAIT_SEC}s." >&2
      announced=1
    fi
    sleep 10
  done

  [ "$announced" -eq 1 ] && echo "[heavy-job] floor met ($(avail_mb) MB). Starting '$LABEL'." >&2
  "$@"
}

if command -v flock >/dev/null 2>&1; then
  exec 9>"$LOCK" || { echo "heavy-job: cannot open lock $LOCK" >&2; exit 1; }
  if ! flock -n 9; then
    echo "[heavy-job] another heavy job holds $LOCK. Waiting for it before '$LABEL'." >&2
    flock 9 || { echo "heavy-job: could not acquire $LOCK" >&2; exit 1; }
  fi
  run_it "$@"
  status=$?
  exec 9>&-
  exit "$status"
fi

# No flock (macOS without util-linux): a mkdir lock is atomic on every POSIX
# filesystem. It must recover a lock whose owner died - which, given the failure
# this script exists for, is the NORMAL case, not the exotic one.
LOCK_DIR="$LOCK.d"
while ! mkdir "$LOCK_DIR" 2>/dev/null; do
  if [ -r "$LOCK_DIR/pid" ]; then
    owner="$(cat "$LOCK_DIR/pid" 2>/dev/null || true)"
    if [ -n "$owner" ] && ! kill -0 "$owner" 2>/dev/null; then
      echo "[heavy-job] clearing a lock left by dead pid $owner (killed, not exited)." >&2
      rm -f "$LOCK_DIR/pid"; rmdir "$LOCK_DIR" 2>/dev/null || true
      continue
    fi
  fi
  sleep 1
done
printf '%s\n' "$$" >"$LOCK_DIR/pid"
trap 'rm -f "$LOCK_DIR/pid"; rmdir "$LOCK_DIR" 2>/dev/null || true' EXIT HUP INT TERM
run_it "$@"
exit $?
