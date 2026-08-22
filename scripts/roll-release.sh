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

say() { echo; echo "=== $* ==="; }
die() { echo "ABORT: $*" >&2; exit 1; }

VERSION="${1:-}"
[ -n "$VERSION" ] || { echo "usage: $0 <version>   e.g. $0 v0.4.19" >&2; exit 2; }

# Deployment coordinates are operator inputs, never repository defaults.
H="${ROLL_HOST:-}"
TEN="${ROLL_TENANTS:-}"
COMPOSE="${ROLL_COMPOSE:-}"
[ -n "$H" ] || die "ROLL_HOST is required"
[ -n "$TEN" ] || die "ROLL_TENANTS is required"
[ -n "$COMPOSE" ] || die "ROLL_COMPOSE is required"
# BOTH stacks' compose project working_dir is the base compose file's directory
# (verified via com.docker.compose.project.working_dir). Running from anywhere
# else re-resolves the base file's relative binds against a different root.
PROJECT_DIR="$(dirname "$COMPOSE")"
STAMP=$(date +%Y%m%d-%H%M%S)

say "digests for $VERSION, read from the registry"
# WAIT, do not abort on the first miss. Tagging and rolling is ONE operator
# motion, and the release workflow takes minutes to publish - so the natural
# `git push --tags && roll` sequence hit "digest not resolvable" every single
# time, which reads like a broken release rather than a race. Bounded (~10min),
# so a release that never publishes still fails rather than hanging.
#
# awk, not `--format`: buildx 0.30.1 ignores the Go template here and prints its
# default multi-line block, which a naive capture swallows whole and then writes
# into a live overlay as a malformed pin.
digest_of() { docker buildx imagetools inspect "$1" 2>/dev/null | awk '/^Digest:/{print $2; exit}'; }
KD=""; FD=""; UD=""
for i in $(seq 1 40); do
  KD=$(digest_of "ghcr.io/wlilley93/boltrig-kernel:$VERSION")
  FD=$(digest_of "ghcr.io/wlilley93/boltrig-fleet:$VERSION")
  UD=$(digest_of "ghcr.io/wlilley93/boltrig-ui:$VERSION")
  [[ "$KD" == sha256:* && "$FD" == sha256:* && "$UD" == sha256:* ]] && break
  [ "$i" = 1 ] && echo "  waiting for $VERSION to publish (the release workflow is probably still running)"
  sleep 15
done
echo "  kernel $KD"
echo "  fleet  $FD"
echo "  worker $UD"
[[ "$KD" == sha256:* ]] || die "kernel digest for $VERSION never became resolvable - did the release succeed?"
[[ "$FD" == sha256:* ]] || die "fleet digest for $VERSION never became resolvable - did the release succeed?"
# Worker is rolled with the kernel and fleet so the browser surface cannot drift
# behind the signed release.
[[ "$UD" == sha256:* ]] || die "Worker digest for $VERSION never became resolvable - did the release succeed?"

# SOURCE-FIRST. The overlay is TRACKED in wlilley93/Opbox
# (boltrig-tenants/), and the box's copy is DERIVED. This used to sed the file on
# the box, which meant the digest a tenant was actually running existed only on
# that box, in a directory that is not a git repository: nothing recorded which
# image a client ran, and a rebuilt box would have silently reverted the pin.
#
# So: edit the SOURCE, verify it, copy it to the box, and prove the two match by
# checksum before anything is brought up. A pin that is not in the source is not
# a pin, it is a local edit waiting to be lost.
SRC_ROOT="${ROLL_SRC:-}"
[ -n "$SRC_ROOT" ] || die "ROLL_SRC is required"

repin() { # $1=overlay path ON THE BOX (its basename-relative path under SRC_ROOT)
  local remote="$1"
  local rel="${remote#*/boltrig-tenants/}"
  local src="$SRC_ROOT/$rel"
  [ -f "$src" ] || die "no tracked source for $rel at $src - the box copy is not authoritative, so refusing to edit it"

  cp -a "$src" "$src.bak-roll-$STAMP"
  python3 - "$src" "$VERSION" "$KD" "$FD" "$UD" <<'PY'
import re, sys
p, version, kd, fd, ud = sys.argv[1:6]
s = open(p).read()
s = re.sub(r'ghcr\.io/wlilley93/boltrig-kernel:[^\s"]+', f'ghcr.io/wlilley93/boltrig-kernel:{version}@{kd}', s)
s = re.sub(r'ghcr\.io/wlilley93/boltrig-fleet:[^\s"]+',  f'ghcr.io/wlilley93/boltrig-fleet:{version}@{fd}',  s)
s = re.sub(r'ghcr\.io/wlilley93/boltrig-ui:[^\s"]+', f'ghcr.io/wlilley93/boltrig-ui:{version}@{ud}', s)
open(p, 'w').write(s)
PY

  local n expected image_lines
  n=$(diff "$src.bak-roll-$STAMP" "$src" | grep -c '^[<>]' || true)
  diff "$src.bak-roll-$STAMP" "$src" || true
  # The overlays repeat images (fleet serves fleet-worker AND hatchet-worker),
  # so the expected diff is 2 lines per MATCHING IMAGE LINE IN THIS FILE - a
  # hardcoded 6 aborted every roll of a 4-image-line overlay and forced the
  # hand-pin-first workaround. Counting what the regex actually rewrites keeps
  # the property the 6 was for: an omitted service line still fails loudly.
  image_lines=$(grep -cE 'ghcr\.io/wlilley93/boltrig-(kernel|fleet|ui):' "$src" || true)
  expected=$((2 * image_lines))
  case "${n:-0}" in
    "$expected") echo "  [ok] repinned $image_lines image lines IN THE SOURCE ($rel)" ;;
    0) echo "  [ok] source already pinned at $VERSION (safe no-op re-run)" ;;
    *) die "source diff for $rel is $n changed lines; expected $expected (2 per image line) or 0 (already pinned)" ;;
  esac
  rm -f "$src.bak-roll-$STAMP"

  # Propagate, then PROVE the box carries exactly the source. scp reporting
  # success is not the same as the bytes matching - and this is the one file that
  # decides which image a client runs.
  ssh "$H" "cp -a $remote $remote.bak-roll-$STAMP" || die "backup failed for $remote"
  scp -q "$src" "$H:$remote" || die "propagate failed for $rel"
  local a b
  a=$(sha256sum "$src" | cut -d" " -f1)
  b=$(ssh "$H" "sha256sum $remote" | cut -d" " -f1)
  [ "$a" = "$b" ] || die "propagated $rel but the box checksum differs ($a vs $b)"
  echo "  [ok] box matches source (sha256 ${a:0:12})"

  # SWEEP THE BOX'S OWN BACKUPS. The LOCAL backup is removed above once the diff
  # is asserted, but the REMOTE one never was - so every roll left a file behind
  # forever. By 2026-07-29 each tenant directory held a dozen-plus
  # `.bak-roll-*`, the real config was hard to pick out of the noise, and anyone
  # copying a tenant dir as a template for a new stack inherited the confusion.
  #
  # Keep the most recent 3: enough to reconstruct what a roll changed, bounded
  # so it cannot grow without limit. The SOURCE is tracked in git and is the
  # authority for the pin, so these are a convenience, never the record - which
  # is exactly why they may be swept without ceremony.
  ssh "$H" "ls -1t ${remote}.bak-roll-* 2>/dev/null | tail -n +4 | xargs -r rm -f" || true
}

bring_up() { # $1=overlay $2=project
  # hatchet-worker rides the fleet image and was bounced BY HAND after every
  # roll since v0.4.32 split it out - a manual step is a forgotten step.
  ssh "$H" "cd $PROJECT_DIR && \
    docker compose -f $COMPOSE -f $1 -p $2 pull kernel fleet-worker hatchet-worker ui && \
    docker compose -f $COMPOSE -f $1 -p $2 up -d --no-deps kernel fleet-worker hatchet-worker ui" \
    || die "compose up failed for $2"
}

# THE MIGRATION GATE.
#
# THIS SCRIPT USED TO DEPLOY IMAGES AND NEVER TOUCH THE SCHEMA, and on the v0.4.30
# roll (2026-08-06) that put both kernels on an 0067-expecting image over an 0066
# database. `/readyz` answered 503 with `checks.migration: head_mismatch` and the
# canary gate aborted - correctly, but only after the canary was already down.
#
# WHY IT MUST BE THE SCRIPT AND NOT A RUNBOOK STEP. The readiness check is STRICT
# EQUALITY, so there is no ordering that avoids an unready window:
#
#     db 0066 + image expecting 0067  ->  503, the NEW image is unready
#     db 0067 + image expecting 0066  ->  503, the OLD image is unready
#
# Migrating every stack up-front therefore takes the OTHER stacks down until their
# images follow. That is not a hypothetical: doing exactly that by hand put a live
# client (cv) into 503 for the minutes between its migration and its deploy. The only
# safe shape is migrate-then-deploy BACK-TO-BACK, PER STACK, which means it belongs
# next to the deploy - a runbook cannot hold two steps together.
#
# The migration docstring's promise that running kernels carry a "tolerant reader" is
# about the job-name ROW MAPPING, not the head assertion. It does not save the old
# image, and reading it as though it did is what cost the window.
#
# It migrates to the head THE TARGET IMAGE EXPECTS, not to the checkout's head: this
# repo can be ahead of the release being rolled, and `upgrade head` would then apply
# a revision no deployed image asserts. A database AHEAD of its image is left alone
# and fails loudly - that is a rollback, and it needs a human and a dump.
MIGRATION_SRC="${ROLL_MIGRATIONS:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

GATE_SCRIPT="$(dirname "${BASH_SOURCE[0]}")/roll-migrate-stack.sh"

stage_migrations() {
  [ -f "$MIGRATION_SRC/alembic.ini" ] || die "no alembic.ini under $MIGRATION_SRC (set ROLL_MIGRATIONS)"
  [ -d "$MIGRATION_SRC/migrations/versions" ] || die "no migrations/versions under $MIGRATION_SRC"
  [ -f "$GATE_SCRIPT" ] || die "missing $GATE_SCRIPT - the migration gate cannot run"
  ssh "$H" 'rm -rf /tmp/roll-mig && mkdir -p /tmp/roll-mig' || die "could not stage migrations on $H"
  scp -q "$MIGRATION_SRC/alembic.ini" "$H:/tmp/roll-mig/alembic.ini" || die "alembic.ini copy failed"
  scp -qr "$MIGRATION_SRC/migrations" "$H:/tmp/roll-mig/migrations" || die "migrations copy failed"
  scp -q "$GATE_SCRIPT" "$H:/tmp/roll-mig/migrate-stack.sh" || die "gate script copy failed"
  echo "  staged the alembic chain + migration gate from $MIGRATION_SRC"
}

migrate_stack() { # $1=compose project prefix (container = $1-kernel-1, network = $1_default)
  local P=$1
  local IMG="ghcr.io/wlilley93/boltrig-kernel:${VERSION}@${KD}"
  # The gate's body lives in scripts/roll-migrate-stack.sh and is COPIED to the box by
  # stage_migrations, not fed over stdin. It was a heredoc first and that heredoc arrived
  # EMPTY: the ssh returned 0, printed nothing, and the gate silently passed over an
  # unmigrated database while the roll carried on. The same body run as a file worked
  # first time. A gate that can no-op without saying so is worse than no gate.
  ssh "$H" "bash /tmp/roll-mig/migrate-stack.sh '$P' '$IMG'" \
    || die "migration gate failed for $P - NOTHING was deployed for this stack"
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

  # THE WORKER, asserted on the same terms as the kernel. Bringing a service up
  # without gating it is how it drifts unnoticed in the first place: the roll now
  # moves the Worker, so a Worker that comes back on the wrong image, or does not come
  # back at all, has to fail the roll rather than be discovered twelve releases
  # later. Asserting the IMAGE and not merely `healthy` is the point - a container
  # that never restarted reports healthy while serving the old bundle.
  local u="$P-ui-1"
  local us=""
  for i in $(seq 1 24); do
    us=$(ssh "$H" "docker ps --filter name=^/$u\$ --format '{{.Status}}'" 2>/dev/null)
    case "$us" in *Restarting*) die "$u is RESTARTING: $us" ;; esac
    case "$us" in *healthy*) break ;; esac
    sleep 5
  done
  case "$us" in *healthy*) echo "  [ok] $u $us" ;; *) die "$u never became healthy: '$us'" ;; esac

  local uimg
  uimg=$(ssh "$H" "docker ps --filter name=^/$u\$ --format '{{.Image}}'")
  [[ "$uimg" == *"$VERSION"* ]] || die "$u is running '$uimg', not $VERSION"
  echo "  [ok] $u running $uimg"
}

say "stage the alembic chain (the migration gate needs it on the box)"
stage_migrations

say "roll the CANARY (solo boltrig: must report NO addons)"
repin "$TEN/boltrig-io.override.yml"
# Migrate IMMEDIATELY before the deploy, not in a batch with the tenant: between
# these two lines the stack is unready by construction, and that window is the
# thing being minimised.
migrate_stack "boltrig"
bring_up "$TEN/boltrig-io.override.yml" "boltrig"
sleep 20
gate "boltrig" "(none)"
echo "CANARY GATE PASSED - only now is the tenant touched"

# CANARY_ONLY=1 stops here, having rolled solo boltrig and nothing else.
#
# Added 2026-08-06 because there was no supported way to roll the fleet PARTIALLY,
# and the alternatives were all worse: run the script and update a client that had
# been explicitly excluded; hand-type the canary half, which this script exists to
# stop ("a canary you do not assert on is not a canary, it is a delay"); or point
# ROLL_TENANTS at a directory without cv/ so the tenant step dies on a missing
# file - deliberately breaking a safety script mid-run on production.
#
# Use it when the tenant must be held back for a reason OUTSIDE this script: no
# verified backup of the tenant's database, an unresolved incident on that stack,
# or an operator instruction to move the canary only. This box has no PITR and a
# prod wipe on record, so "no verified dump" is a real reason to hold a migration.
#
# NOTE WHAT THIS DOES NOT DO: it leaves the fleet UNEVEN, which is the state
# `make fleet-drift-all` exists to report. Run it afterwards and expect the tenant
# to show as behind - that finding is correct, not noise, until cv is rolled too.
#
# And note what it is NOT for: papering over a dump you could not take. On the
# v0.4.30 roll cv's dump failed four times with 'password authentication failed',
# which looked like a credential problem and was not - `postgres` is a PER-NETWORK
# docker alias, and from opbox-prod_backend it names Opbox-Postgres, which does not
# contain cvboltrig at all. cv's own postgres holds it and the password was right
# from the first attempt. Diagnose the target before reaching for this flag.
if [ "${CANARY_ONLY:-0}" = "1" ]; then
  echo
  echo "CANARY_ONLY=1 - stopping after solo boltrig. The tenant was NOT touched."
  echo "  fleet is now UNEVEN by design; 'make fleet-drift-all' will say so."
  exit 0
fi

say "roll CLASSICAL VISAS (opbox-provisioned: must report opbox/)"
repin "$TEN/cv/compose.override.yml"
# The tenant's schema is migrated HERE, after the canary gate has passed, and not
# earlier with the canary's. Migrating both up-front is what took cv down on
# 2026-08-06: its 0066-expecting kernel went unready the moment its database reached
# 0067, and stayed that way until this deploy. If the canary gate refuses, cv is left
# entirely alone - old image, old schema, still serving.
migrate_stack "cv-boltrig"
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
