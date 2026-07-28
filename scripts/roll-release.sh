#!/usr/bin/env bash
# Roll a released boltrig version to the fleet: CANARY FIRST, and the canary is a GATE.
#
#   scripts/roll-release.sh v0.4.19
#
# WHY THIS EXISTS. The roll recipe lived in one person's head and in a memory
# file, and it was re-typed per release. Every re-typing lost a check. On
# 2026-07-28 the hand-written version printed the canary's health and its addon
# line and then rolled the live client REGARDLESS - a canary you do not assert on
# is not a canary, it is a delay. This encodes the checks so the next roll cannot
# quietly skip them.
#
# WHAT IT ASSERTS, per stack, before touching the next one:
#   * the overlay diff is EXACTLY the two image lines (or already at this pin)
#   * the kernel reaches `healthy` and is not Restarting
#   * the fleet-worker is running
#   * BOTH report the expected `addons active:` line - the deployments differ
#     deliberately (opbox tenants carry the addon, solo boltrig carries none),
#     so this is where an accidental sameness would show up
#   * the kernel is genuinely running the target version
#
# The addons assertion is load-bearing precisely because that log line did not
# exist before v0.4.19: it cannot be satisfied by a stale container still up.
set -uo pipefail

VERSION="${1:-}"
[ -n "$VERSION" ] || { echo "usage: $0 <version>   e.g. $0 v0.4.19" >&2; exit 2; }

H="${ROLL_HOST:-jellytot-prod}"
TEN="${ROLL_TENANTS:-/home/jellytot/Projects/opbox-prod/boltrig-tenants}"
COMPOSE="${ROLL_COMPOSE:-/home/jellytot/Projects/boltrig-main/docker-compose.yml}"
# BOTH stacks' compose project working_dir is the base compose file's directory
# (verified via com.docker.compose.project.working_dir). Running from anywhere
# else re-resolves the base file's relative binds against a different root.
PROJECT_DIR="$(dirname "$COMPOSE")"
STAMP=$(date +%Y%m%d-%H%M%S)

say() { echo; echo "=== $* ==="; }
die() { echo "ABORT: $*" >&2; exit 1; }

say "digests for $VERSION, read from the registry"
# awk, not `--format`: buildx 0.30.1 ignores the Go template here and prints its
# default multi-line block, which a naive capture swallows whole and then writes
# into a live overlay as a malformed pin.
KD=$(docker buildx imagetools inspect "ghcr.io/wlilley93/boltrig-kernel:$VERSION" 2>/dev/null | awk '/^Digest:/{print $2; exit}')
FD=$(docker buildx imagetools inspect "ghcr.io/wlilley93/boltrig-fleet:$VERSION"  2>/dev/null | awk '/^Digest:/{print $2; exit}')
echo "  kernel $KD"
echo "  fleet  $FD"
[[ "$KD" == sha256:* ]] || die "kernel digest for $VERSION is not resolvable"
[[ "$FD" == sha256:* ]] || die "fleet digest for $VERSION is not resolvable"

repin() { # $1=overlay
  ssh "$H" "cp -a $1 $1.bak-roll-$STAMP" || die "backup failed for $1"
  ssh "$H" "python3 - <<'PY'
import re
p='$1'; s=open(p).read()
s=re.sub(r'ghcr\.io/wlilley93/boltrig-kernel:[^\s\"]+','ghcr.io/wlilley93/boltrig-kernel:$VERSION@$KD',s)
s=re.sub(r'ghcr\.io/wlilley93/boltrig-fleet:[^\s\"]+', 'ghcr.io/wlilley93/boltrig-fleet:$VERSION@$FD', s)
open(p,'w').write(s)
PY"
  local n
  n=$(ssh "$H" "diff $1.bak-roll-$STAMP $1 | grep -c '^[<>]' || true" | head -1)
  ssh "$H" "diff $1.bak-roll-$STAMP $1 || true"
  case "${n:-0}" in
    4) echo "  [ok] repinned both image lines" ;;
    0) echo "  [ok] already pinned at $VERSION (safe no-op re-run)" ;;
    *) die "overlay diff for $1 is $n changed lines; expected 4 (repin) or 0 (already pinned)" ;;
  esac
}

bring_up() { # $1=overlay $2=project
  ssh "$H" "cd $PROJECT_DIR && \
    docker compose -f $COMPOSE -f $1 -p $2 pull kernel fleet-worker && \
    docker compose -f $COMPOSE -f $1 -p $2 up -d --no-deps kernel fleet-worker" \
    || die "compose up failed for $2"
}

# THE GATE.
gate() { # $1=project $2=expected `addons active:` substring
  # NOTE: separate `local` statements. Bash expands EVERY argument to `local`
  # before performing ANY assignment, so `local P=$1 k="$P-kernel-1"` reads an
  # unset P and dies under `set -u` - which is how this gate first shipped, and
  # it crashed before asserting anything.
  local P=$1
  local WANT=$2
  local k="$P-kernel-1"
  local w="$P-fleet-worker-1"
  local st=""
  local i
  for i in $(seq 1 24); do
    st=$(ssh "$H" "docker ps --filter name=^/$k\$ --format '{{.Status}}'" 2>/dev/null)
    case "$st" in *Restarting*) die "$k is RESTARTING: $st" ;; esac
    case "$st" in *healthy*) break ;; esac
    sleep 5
  done
  case "$st" in *healthy*) echo "  [ok] $k $st" ;; *) die "$k never became healthy: '$st'" ;; esac

  local ws
  ws=$(ssh "$H" "docker ps --filter name=^/$w\$ --format '{{.Status}}'" 2>/dev/null)
  case "$ws" in *Restarting*|"") die "$w is not running: '$ws'" ;; *) echo "  [ok] $w $ws" ;; esac

  local ka wa
  ka=$(ssh "$H" "docker logs $k 2>&1 | grep -o 'addons active: .*' | tail -1")
  wa=$(ssh "$H" "docker logs $w 2>&1 | grep -o 'addons active: .*' | tail -1")
  echo "  $k -> $ka"
  echo "  $w -> $wa"
  [[ "$ka" == *"$WANT"* ]] || die "$k addons line is '$ka', expected to contain '$WANT'"
  [[ "$wa" == *"$WANT"* ]] || die "$w addons line is '$wa', expected to contain '$WANT'"

  local img
  img=$(ssh "$H" "docker ps --filter name=^/$k\$ --format '{{.Image}}'")
  [[ "$img" == *"$VERSION"* ]] || die "$k is running '$img', not $VERSION"
  echo "  [ok] $k running $img"
}

say "roll the CANARY (solo boltrig: must report NO addons)"
repin "$TEN/boltrig-io.override.yml"
bring_up "$TEN/boltrig-io.override.yml" "boltrig"
sleep 20
gate "boltrig" "(none)"
echo "CANARY GATE PASSED - only now is the tenant touched"

say "roll CLASSICAL VISAS (opbox-provisioned: must report opbox/)"
repin "$TEN/cv/compose.override.yml"
bring_up "$TEN/cv/compose.override.yml" "cv-boltrig"
sleep 20
gate "cv-boltrig" "opbox/"

say "the unclaimed-bearer alarm must be SILENT on the tenant"
# `grep -c` EXITS 1 on zero matches, so `$(cmd || echo 0)` yields "0\n0" and an
# equality test fails on the HEALTHY path - an alarm that cries wolf is the same
# blindness as no alarm. Fold the failure inside, take the first line.
n=$(ssh "$H" "docker logs --since 20m cv-boltrig-kernel-1 2>&1 | grep -c 'NO adapter claims it' || true" | head -1)
[ "${n:-0}" = "0" ] || die "$n unclaimed-bearer warnings: permission parity is OFF"
echo "  [ok] no unclaimed-bearer warning"

say "BOTH STACKS ROLLED AND GATED"
ssh "$H" "docker ps --format '{{.Names}}\t{{.Image}}\t{{.Status}}' | grep -E '(cv-)?boltrig-(kernel|fleet-worker)-1'"
