#!/usr/bin/env bash
#
# session-restore.sh - find Claude sessions that DIED rather than ended, and
# bring them back into free tmux slots.
#
# WHY THIS EXISTS
# On 2026-08-19 at 12:18:17 the beelink's kernel OOM-killer fired on a
# `next build --webpack` that had reached 9.3GB. The build was not the casualty
# that mattered: it died inside a systemd tmux-spawn scope, systemd marked the
# whole scope `Failed with result 'oom-kill'`, and the scope dying took the PANE
# with it. Two Claude chats vanished from the switcher mid-sentence.
#
# NOTHING WAS LOST. The transcripts under ~/.claude/projects/<slug>/ were intact
# and parsed clean - 0 malformed lines across 8318 records. What was lost was the
# PROCESS, and with it every trace of the chat in the live-session bar, because
# that bar is built from ~/.claude/sessions/<pid>.json - one file per LIVE pid.
# A dead pane leaves no row there. That is why a chat can be perfectly recoverable
# and completely invisible at the same time.
#
# THE DISTINCTION THIS SCRIPT IS BUILT ON
#   ~/.claude/sessions/<pid>.json     LIVE sessions. Disappears the instant a pane dies.
#   ~/.claude/projects/<slug>/*.jsonl THE RECORD. Survives the kill. Resumable.
# Recovery is therefore never "undelete" - it is re-attaching a live process to a
# record that was never damaged. Any tool that talks about "restoring transcripts"
# has misdiagnosed the failure.
#
# WHY IT WAITS FOR MEMORY BEFORE RESUMING
# The naive recovery - resume everything at once, immediately - is the failure
# repeating itself. When this was first done by hand the box was at 277MB free
# with the SAME build still climbing; three Claude processes would have re-run the
# OOM and killed the very chats being restored. So each resume blocks on real
# MemAvailable headroom, staggered, and says so on screen while it waits.
#
#   scripts/session-restore.sh [--list] [--cwd DIR] [--since MIN] [--need MB] [--session ID]
#
#   --list           report only; never opens a window (default when no tmux)
#   --cwd DIR        project whose sessions to consider     (default: $PWD)
#   --since MIN      only sessions written in the last MIN minutes (default: 120)
#   --need MB        MemAvailable floor for the first resume (default: 3800,
#                    +1000 per additional session so they do not all land at once)
#   --session ID     restore exactly this session id, skipping discovery
#   --tmux NAME      tmux session to open windows in (default: current, else first)
#
set -uo pipefail

LIST_ONLY=0
TARGET_CWD="$PWD"
SINCE_MIN=120
NEED_MB=3800
ONLY_SESSION=""
TMUX_SESSION=""

while [ $# -gt 0 ]; do
  case "$1" in
    --list)    LIST_ONLY=1; shift ;;
    --cwd)     TARGET_CWD="${2:?--cwd needs a directory}"; shift 2 ;;
    --since)   SINCE_MIN="${2:?--since needs minutes}"; shift 2 ;;
    --need)    NEED_MB="${2:?--need needs MB}"; shift 2 ;;
    --session) ONLY_SESSION="${2:?--session needs an id}"; shift 2 ;;
    --tmux)    TMUX_SESSION="${2:?--tmux needs a session name}"; shift 2 ;;
    -h|--help) sed -n '2,45p' "$0"; exit 0 ;;
    *) echo "session-restore: unknown argument '$1'" >&2; exit 2 ;;
  esac
done

CLAUDE_HOME="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
PROJECTS="$CLAUDE_HOME/projects"
LIVE="$CLAUDE_HOME/sessions"

[ -d "$PROJECTS" ] || { echo "session-restore: no $PROJECTS" >&2; exit 1; }

# The project slug is the absolute cwd with every non-alphanumeric run collapsed
# to a single '-'. Derived, not stored: a stored copy would go stale the first
# time a repo moved, and this must keep working after a re-home.
slug() { printf '%s' "$1" | sed 's/[^a-zA-Z0-9]/-/g'; }
SLUG="$(slug "$TARGET_CWD")"
DIR="$PROJECTS/$SLUG"

if [ ! -d "$DIR" ]; then
  echo "session-restore: no transcripts for $TARGET_CWD" >&2
  echo "  (looked in $DIR)" >&2
  exit 1
fi

# A session is LIVE if some ~/.claude/sessions/<pid>.json still names it AND that
# pid is still running. The pid check is not paranoia: a SIGKILL leaves the json
# behind, so trusting the file alone reports a dead chat as healthy - which is
# exactly the state an OOM leaves.
live_ids() {
  [ -d "$LIVE" ] || return 0
  for f in "$LIVE"/*.json; do
    [ -e "$f" ] || continue
    python3 - "$f" <<'PY' 2>/dev/null
import json, os, sys
try:
    d = json.load(open(sys.argv[1]))
except Exception:
    sys.exit(0)
pid = d.get("pid")
sid = d.get("sessionId")
if not pid or not sid:
    sys.exit(0)
try:
    os.kill(int(pid), 0)          # signal 0 = existence test, no effect
except (OSError, ValueError):
    sys.exit(0)                   # stale file, dead pid: NOT live
print(sid)
PY
  done
}

LIVE_IDS="$(live_ids | sort -u)"

is_live() { printf '%s\n' "$LIVE_IDS" | grep -qxF "$1"; }

avail_mb() { awk '/MemAvailable/{print int($2/1024)}' /proc/meminfo 2>/dev/null || echo 999999; }

# Discovery: recently-written transcripts with no live process behind them.
# `-mmin` rather than a stored ledger, for the same derive-don't-store reason.
DEAD=()
if [ -n "$ONLY_SESSION" ]; then
  [ -f "$DIR/$ONLY_SESSION.jsonl" ] || { echo "session-restore: no transcript $ONLY_SESSION" >&2; exit 1; }
  DEAD=("$ONLY_SESSION")
else
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    sid="$(basename "$f" .jsonl)"
    is_live "$sid" && continue
    DEAD+=("$sid")
  done < <(find "$DIR" -maxdepth 1 -name '*.jsonl' -mmin "-$SINCE_MIN" 2>/dev/null | sort)
fi

if [ "${#DEAD[@]}" -eq 0 ]; then
  echo "No dead sessions for $TARGET_CWD in the last ${SINCE_MIN}m. Nothing to restore."
  exit 0
fi

# Report before acting. A restore that silently picks its own targets is a restore
# nobody can audit, and the whole point of the record is that it can be read.
echo "Dead sessions for $TARGET_CWD (written within ${SINCE_MIN}m, no live process):"
echo
for sid in "${DEAD[@]}"; do
  f="$DIR/$sid.jsonl"
  python3 - "$f" "$sid" <<'PY'
import json, os, sys, datetime
f, sid = sys.argv[1], sys.argv[2]
recs = []
for line in open(f, errors="replace"):
    line = line.strip()
    if not line:
        continue
    try:
        recs.append(json.loads(line))
    except Exception:
        recs.append({"__bad__": True})
bad = sum(1 for r in recs if r.get("__bad__"))
def text(r):
    m = r.get("message") or {}
    c = m.get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return " ".join(x.get("text", "") for x in c if isinstance(x, dict) and x.get("type") == "text")
    return ""
msgs = [r for r in recs if r.get("type") in ("user", "assistant") and text(r).strip()]
users = [r for r in msgs if r.get("type") == "user"]
first = text(users[0]).strip().replace("\n", " ")[:72] if users else "(no user turn)"
last_ts = max((r.get("timestamp") for r in recs if r.get("timestamp")), default="")
mt = datetime.datetime.fromtimestamp(os.path.getmtime(f)).strftime("%H:%M:%S")
health = "clean" if bad == 0 else "%d MALFORMED LINES" % bad
print("  %s" % sid)
print("     last write %s | %d messages | %d records | transcript %s" % (mt, len(msgs), len(recs), health))
print("     opened with: %s" % first)
PY
done
echo

if [ "$LIST_ONLY" -eq 1 ]; then
  echo "Report only (--list). To bring them back:"
  for sid in "${DEAD[@]}"; do echo "  claude --resume $sid"; done
  exit 0
fi

if ! command -v tmux >/dev/null 2>&1 || ! tmux list-sessions >/dev/null 2>&1; then
  echo "No tmux server, so nothing to open into. Resume by hand:"
  for sid in "${DEAD[@]}"; do echo "  claude --resume $sid"; done
  exit 0
fi

if [ -z "$TMUX_SESSION" ]; then
  TMUX_SESSION="${TMUX:+$(tmux display-message -p '#S' 2>/dev/null)}"
  [ -n "$TMUX_SESSION" ] || TMUX_SESSION="$(tmux list-sessions -F '#{session_name}' | head -1)"
fi

# Free slots only. Pinned orchestrator slots (11-15 on the M4: m4, beelink, m1,
# jellytot-prod, balmoral) are load-bearing UI and are never reused - hence the
# explicit ceiling rather than "next free index".
USED="$(tmux list-windows -t "$TMUX_SESSION" -F '#{window_index}' 2>/dev/null | sort -n)"
next_free() {
  local i
  for i in $(seq 1 10); do
    printf '%s\n' "$USED" | grep -qx "$i" || { echo "$i"; return 0; }
  done
  return 1
}

WAITER="$(mktemp "${TMPDIR:-/tmp}/session-restore-wait.XXXXXX.sh")"
cat > "$WAITER" <<'WAIT'
#!/usr/bin/env bash
need_mb="$1"; sid="$2"; dir="$3"
avail() { awk '/MemAvailable/{print int($2/1024)}' /proc/meminfo 2>/dev/null || echo 999999; }
printf '\n  Restoring session %s\n' "$sid"
printf '  Holding until %s MB is available (now %s MB). Ctrl-C to start anyway.\n\n' "$need_mb" "$(avail)"
while [ "$(avail)" -lt "$need_mb" ]; do
  printf '\r  available %6s MB   need %s MB   %s' "$(avail)" "$need_mb" "$(date +%H:%M:%S)"
  sleep 10
done
printf '\n  Headroom reached (%s MB). Resuming.\n\n' "$(avail)"
cd "$dir" || exit 1
exec claude --resume "$sid"
WAIT
chmod +x "$WAITER"

echo "Opening into tmux session '$TMUX_SESSION' (slots 1-10 only; pinned 11+ untouched):"
n=0
for sid in "${DEAD[@]}"; do
  slot="$(next_free)" || { echo "  no free slot 1-10 left; resume by hand: claude --resume $sid"; continue; }
  USED="$(printf '%s\n%s\n' "$USED" "$slot")"
  need=$(( NEED_MB + n * 1000 ))
  tmux new-window -d -t "$TMUX_SESSION:$slot" -n shell -c "$TARGET_CWD" \
    "bash '$WAITER' $need '$sid' '$TARGET_CWD'"
  echo "  slot $slot  <-  $sid   (resumes at >= ${need} MB available)"
  n=$(( n + 1 ))
done
echo
echo "Now at $(avail_mb) MB available. Each slot resumes itself when its floor is met."
