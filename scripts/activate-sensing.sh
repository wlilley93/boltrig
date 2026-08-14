#!/usr/bin/env bash
# ============================================================================
# activate-sensing.sh -- close the four blockers that keep the sensing bridge
# alive, ONE WATCHED STEP AT A TIME.
#
# WHAT IS WRONG TODAY. capture_policy.camera_gate() returns a GRANT it never
# asked the kernel for, because BOLTRIG_SENSING_UNMANAGED=1 is set on three
# launchd jobs. That bridge exists because FOUR independent things each refuse
# on their own, and fixing only one leaves the other three. This script closes
# them in the only order that does not strand the system, and PROVES each one
# before the next is allowed to run.
#
#   ---------------------------------------------------------------------
#   DRY RUN IS THE DEFAULT. Without --apply this script changes NOTHING.
#   It runs the read-only precondition checks, prints the exact commands and
#   payloads it would use, prints the rollback, and stops. Add --apply only
#   when you have read that output and want it to happen.
#   ---------------------------------------------------------------------
#
#   ./scripts/activate-sensing.sh 0-preflight     read-only; where the four blockers stand
#   ./scripts/activate-sensing.sh key             add BOLTRIG_DEVICE_LEASE_SIGNING_KEY to .env
#   ./scripts/activate-sensing.sh 1-migrate       alembic 0070 -> 0073 on the live DB
#   ./scripts/activate-sensing.sh 2-deploy        rebuild the kernel image and recreate it
#   ./scripts/activate-sensing.sh 3-enrol         mint a device credential (0600)
#   ./scripts/activate-sensing.sh 4-bind          publish the camera binding
#   ./scripts/activate-sensing.sh 5-enable        turn the camera on in the owner's settings
#   ./scripts/activate-sensing.sh 6-verify        read-only; the gate must GRANT from the kernel
#   ./scripts/activate-sensing.sh 7-retire        PRINTS the retirement; performs nothing
#
#   ./scripts/activate-sensing.sh rollback-image     put the previous kernel image back
#   ./scripts/activate-sensing.sh rollback-schema    alembic 0073 -> 0070
#   ./scripts/activate-sensing.sh rollback-sensing   camera off, binding cleared, device revoked
#
# NOTHING RUNS ANOTHER STEP. You type each one. That is deliberate: step 1
# writes to the live database and step 2 takes away a container other sessions
# are using.
#
# WHAT IT WILL NOT DO, AT ALL.
#   * It never touches camerad, presence or the observer. A second camerad
#     contends for the UVC device and recovery is a PHYSICAL REPLUG. Step 7
#     therefore only prints instructions, and stops.
#   * It never edits capture_policy.py and never removes BOLTRIG_SENSING_UNMANAGED
#     from a plist. Step 6 proves the gate works with the bridge STILL IN PLACE,
#     by emptying that variable for ONE short-lived probe process.
#   * It never restarts postgres, redis, hatchet or the fleet worker. `--no-deps`
#     is on the one compose command in this file, and it is load-bearing:
#     hatchet-lite regenerates its keyset on recreate, which would invalidate the
#     worker's token.
#   * It never commits, checks out or cleans anything in git.
#
# "HEALTHY" IS NOT A SUCCESS SIGNAL HERE AND CANNOT BE. boltrig-kernel-1 is
# ALREADY unhealthy for an unrelated reason: /readyz reports model_gateway
# probe_failed with required=true, FailingStreak in the four figures. The
# container healthcheck consults /readyz, so it will still say "unhealthy" after
# a PERFECT rebuild. Every postcondition below therefore checks something that
# actually discriminates: the migration head, a direct grep of the file inside
# the running container, and the HTTP status of the route itself.
#
# Verified against the live kernel, the live database and this Mac's AVFoundation
# camera list on 2026-08-13.
# ============================================================================
set -uo pipefail

# --- coordinates, all read from the live estate -----------------------------

REPO=/Users/williamlilley/Projects/boltrig
OBS=/Users/williamlilley/Projects/companion-observer
VM=boltrig-vm
PROJECT=boltrig                     # com.docker.compose.project on boltrig-kernel-1
CONTAINER=boltrig-kernel-1
PGCONTAINER=boltrig-postgres-1
NETWORK=boltrig_default
IMAGE=boltrig/kernel:0.1.0          # the tag docker-compose.yml pins for the kernel
COMPOSE_FILES="-f docker-compose.yml -f docker-compose.vm.yml"   # from the container's own labels
KERNEL=http://127.0.0.1:18000       # KERNEL_PORT=18000, published by the VM onto Mac loopback
EMAIL=will.lilley93@gmail.com       # the ONE row in users; tenant "default", superadmin
LABEL="mac-mini-m4-pro"
CAMERA_NAME="EMEET PIXY"            # camerad's allowlisted device (pixy-stream/camerad.py CAMERA_NAME)

BASE_HEAD=0070_ai_config_modalities # where the live DB sits today
TARGET_HEAD=0073_agent_model_routes # boltrig/api/readiness.py EXPECTED_ALEMBIC_HEAD

STATE_DIR="$HOME/.boltrig/sensing-activation"   # bookkeeping for this run
CRED="$HOME/.boltrig/sensing-agent.json"        # capture_policy.CREDENTIAL_FILE default

APPLY=0
STEP=""

# --- output -----------------------------------------------------------------

say()  { printf '\n=== %s ===\n' "$*"; }
note() { printf '    %s\n' "$*"; }
cmd()  { printf '    $ %s\n' "$*"; }
die()  { printf '\nABORT: %s\n' "$*" >&2; exit 1; }

applying() { [ "$APPLY" = "1" ]; }

# A precondition that does not hold stops the step before anything moves. It is
# not a rollback situation -- nothing was done -- so it prints no rollback.
precondition_failed() {
  printf '\nPRECONDITION FAILED (%s)\n    %s\n' "$STEP" "$1" >&2
  shift
  for line in "$@"; do printf '    %s\n' "$line" >&2; done
  printf '\nNothing was changed.\n' >&2
  exit 1
}

# A postcondition that does not hold means the step DID something and it did not
# take. Stop dead and print that step's way back.
postcondition_failed() {
  printf '\n############################################################\n' >&2
  printf 'POSTCONDITION FAILED (%s)\n    %s\n' "$STEP" "$1" >&2
  printf '\nThe step ran and did NOT take. Do not run the next step.\n' >&2
  printf '\nROLLBACK FOR THIS STEP:\n' >&2
  rollback_advice "$STEP" >&2
  printf '############################################################\n' >&2
  exit 1
}

rollback_advice() {
  case "$1" in
    key)
      printf '    Delete the BOLTRIG_DEVICE_LEASE_SIGNING_KEY line from %s/.env,\n' "$REPO"
      printf '    or restore the backup in %s/env.bak-*\n' "$STATE_DIR"
      printf '    No container has read it yet, so nothing else is affected.\n'
      ;;
    1-migrate)
      printf '    ./scripts/activate-sensing.sh rollback-schema --apply\n'
      printf '    (0073 -> 0070. 0072 refuses to reverse while a device.file.list lease exists.)\n'
      ;;
    2-deploy)
      printf '    ./scripts/activate-sensing.sh rollback-image --apply\n'
      printf '    That retags the preserved image and recreates the container.\n'
      printf '    NOTE: the schema is at %s and the old image asserts %s.\n' "$TARGET_HEAD" "$BASE_HEAD"
      printf '    It will SERVE, but /readyz gains a migration failure on top of the\n'
      printf '    model_gateway one. Run rollback-schema too to get the old readiness back.\n'
      ;;
    3-enrol)
      printf '    ./scripts/activate-sensing.sh rollback-sensing --apply\n'
      printf '    (revokes the device and moves %s aside)\n' "$CRED"
      printf '    A half-written credential file is WORSE than none: it passes\n'
      printf '    capture_policy._credential()'"'"'s shape check and is then rejected as\n'
      printf '    invalid_device_session, so the host looks provisioned when it is not.\n'
      ;;
    4-bind)
      printf '    There is NO delete route for camera_bindings. The row stays.\n'
      printf '    It is inert: nothing reads a binding that no user setting points at.\n'
      printf '    The withdrawal that counts is clearing the settings binding:\n'
      printf '    ./scripts/activate-sensing.sh rollback-sensing --apply\n'
      ;;
    5-enable)
      printf '    PUT /v1/me/sensing/camera {"enabled": false, "camera_id": null}\n'
      printf '    ./scripts/activate-sensing.sh rollback-sensing --apply\n'
      ;;
    6-verify)
      printf '    Nothing to roll back -- step 6 is read-only.\n'
      printf '    A refusal here means an EARLIER step did not really take. Read the\n'
      printf '    reason it printed, and DO NOT retire the bridge.\n'
      ;;
    *)
      printf '    (no rollback registered for %s)\n' "$1"
      ;;
  esac
}

# --- plumbing ---------------------------------------------------------------

vm()  { orb -m "$VM" bash -lc "$1"; }
dk()  { orb -m "$VM" docker "$@"; }

confirm() {
  applying || return 0
  printf '\n    This will change the live system.\n    Type exactly: %s\n    > ' "$1"
  local typed; read -r typed
  [ "$typed" = "$1" ] || die "not confirmed -- nothing was changed"
}

# Printed at the end of every mutating step in dry-run mode.
dry_stop() {
  say "DRY RUN -- nothing above was executed"
  note "The precondition checks above are real and were run against the live"
  note "system. The actions were only printed."
  note ""
  note "Rollback for this step, if you go ahead:"
  rollback_advice "$STEP"
  note ""
  note "To do it:  ./scripts/activate-sensing.sh $STEP --apply"
  exit 0
}

# require_state must be called in the CURRENT shell, never inside $( ), because
# precondition_failed exits -- and an exit inside a command substitution only
# kills the subshell. That mistake let a step walk straight past its own guard
# with an empty variable, which under --apply would have PUT an empty camera_id.
# So the guard and the read are two separate calls, on purpose.
require_state() {
  local f
  for f in "$@"; do
    [ -f "$STATE_DIR/$f" ] || precondition_failed \
      "missing $STATE_DIR/$f" \
      "Run the earlier step first -- this one has nothing to work from."
  done
}
state() { cat "$STATE_DIR/$1"; }

mkstate() { mkdir -p "$STATE_DIR" && chmod 700 "$STATE_DIR"; }

http_code() { curl -s -o /dev/null -w '%{http_code}' -m 5 "$1"; }

db_head() {
  dk exec "$PGCONTAINER" psql -U boltrig -d boltrig -tAc \
    'select version_num from alembic_version' 2>/dev/null | tr -d '\r' | tr -d '[:space:]'
}

# grep -c exits 1 on zero matches, which is a legitimate answer here, so the
# count is taken from stdout and the exit status is deliberately ignored.
deployed_sensing_count() {
  local n
  n=$(dk exec "$CONTAINER" grep -c sensing /app/boltrig/kernel/camera_agent_routes.py 2>/dev/null | tr -d '\r')
  printf '%s' "${n:-0}"
}

# ---------------------------------------------------------------------------
# camera_probe -- derive the camera_id the kernel will accept. NOT A GUESS.
#
# apps/worker/src-tauri/src/camera_discovery.rs::project_camera computes it as
#     descriptor_fingerprint = sha256_hex(native_key)   # AVCaptureDevice.uniqueID
#     camera_id              = "camera_" + fingerprint[:32]
# and camera_agent_routes._CAMERA_ID enforces ^camera_[0-9A-Fa-f]{32}$.
#
# system_profiler reports the SAME uniqueID AVFoundation does -- checked on this
# machine against a compiled AVCaptureDeviceDiscoverySession probe, byte-identical.
# Enumeration does not OPEN the device, so this does not contend with the ffmpeg
# camerad is holding.
# ---------------------------------------------------------------------------
camera_probe() {
  local sp
  sp=$(system_profiler SPCameraDataType 2>/dev/null)
  UNIQUE_ID=$(printf '%s' "$sp" | awk -v n="$CAMERA_NAME" '$0 ~ n {f=1} f && /Unique ID:/ {print $3; exit}')
  [ -n "${UNIQUE_ID:-}" ] || precondition_failed \
    "no camera named '$CAMERA_NAME' in system_profiler SPCameraDataType" \
    "The Pixy is unplugged, or macOS has not enumerated it. Plug it in and retry."
  MODEL_ID=$(printf '%s' "$sp" | awk -v n="$CAMERA_NAME" '$0 ~ n {f=1} f && /Model ID:/ {sub(/^ *Model ID: */,""); print; exit}')
  FINGERPRINT=$(printf '%s' "$UNIQUE_ID" | shasum -a 256 | cut -d' ' -f1)
  CAMERA_ID="camera_${FINGERPRINT:0:32}"
  note "name        $CAMERA_NAME"
  note "uniqueID    $UNIQUE_ID"
  note "model       ${MODEL_ID:-unknown}"
  note "fingerprint $FINGERPRINT"
  note "camera_id   $CAMERA_ID"
}

# ============================================================================
# 0-preflight -- READ ONLY, ALWAYS. Ignores --apply because there is nothing
# here to apply. Report where all four blockers stand before anything moves.
# ============================================================================
step_0_preflight() {
  say "where the kernel actually comes from"
  dk inspect "$CONTAINER" --format '    project      {{index .Config.Labels "com.docker.compose.project"}}
    config files {{index .Config.Labels "com.docker.compose.project.config_files"}}
    working dir  {{index .Config.Labels "com.docker.compose.project.working_dir"}}
    image        {{.Config.Image}}
    image id     {{.Image}}
    health       {{.State.Health.Status}} (FailingStreak {{.State.Health.FailingStreak}})' \
    || die "cannot reach $CONTAINER in $VM -- is OrbStack running?"
  note "source is BAKED (deploy/kernel.Dockerfile: COPY boltrig/ /app/boltrig/), not"
  note "bind-mounted, so a rebuild is the only way new routes reach the running kernel."

  say "BLOCKER 1 -- the deployed image predates the code"
  local live src
  live=$(deployed_sensing_count)
  src=$(grep -c sensing "$REPO/boltrig/kernel/camera_agent_routes.py" 2>/dev/null); src=${src:-0}
  note "occurrences of 'sensing' in camera_agent_routes.py:  image=$live   source=$src"
  note "GET  /v1/device-agent/x/sensing-config   -> $(http_code "$KERNEL/v1/device-agent/x/sensing-config")   (404 = route absent)"
  note "POST /v1/device-agent/x/camera-bindings  -> $(http_code "$KERNEL/v1/device-agent/x/camera-bindings")   (401/405 = route present)"
  note "register_camera_agent_routes registers BOTH. The image has only one."
  note "=> this is NOT a wiring bug. A REBUILD is the whole fix; no source change."

  say "BLOCKERS 2, 3 and 4 -- the database"
  dk exec "$PGCONTAINER" psql -U boltrig -d boltrig -tAc \
    "select '    devices             = '||count(*) from devices
     union all select '    device_enrollments  = '||count(*) from device_enrollments
     union all select '    camera_bindings     = '||count(*) from camera_bindings
     union all select '    user_settings       = '||count(*) from user_settings
     union all select '    users               = '||count(*) from users
     union all select '    alembic head        = '||version_num from alembic_version" \
    || die "cannot query $PGCONTAINER"
  note "devices=0            -> no credential can be minted (blocker 2)"
  note "camera_bindings=0    -> sensing_policy has no camera_id  -> camera_not_bound (blocker 3)"
  note "user_settings=0      -> DEFAULT_CAMERA_ENABLED is False  -> camera_disabled (blocker 4)"

  say "BLOCKER 5 -- there is no device lease signing key (this one is not on the list)"
  if grep -q '^BOLTRIG_DEVICE_LEASE_SIGNING_KEY=..' "$REPO/.env" 2>/dev/null; then
    note "set in .env -- good"
  else
    note "NOT set in .env, and not in the container's environment."
    note "signer_for() returns None, so BOTH enrolment routes answer 503"
    note "device_leases_unavailable before they look at anything else."
    note "Fixing the deploy and the database still leaves enrolment dead."
    note "=> run the 'key' step, and note it is inert until step 2 recreates the"
    note "   container (env_file is read at container-create time)."
  fi

  say "HAZARD -- the kernel is already unhealthy, for an unrelated reason"
  curl -s -m 5 "$KERNEL/readyz" | python3 -c '
import json,sys
try:
    d=json.load(sys.stdin)
except Exception:
    sys.exit("    /readyz did not return JSON")
c=d.get("checks",{})
print("    /readyz        :", d.get("status"))
print("    migration      :", c.get("migration"))
print("    model_gateway  :", c.get("model_gateway"))
' || note "(could not read /readyz)"
  note ""
  note "READ THIS. model_gateway is required=true and ALREADY failing, so /readyz is"
  note "not_ready TODAY and will STILL be not_ready after a perfect rebuild. The"
  note "container health probe consults /readyz, so \"it came up healthy\" can never be"
  note "the success signal here, and THIS SCRIPT WILL NOT FIX IT. Step 2 checks the"
  note "three things that do discriminate: a direct grep inside the container, the"
  note "sensing-config route answering 401 instead of 404, and expected==current on"
  note "the migration head."

  say "HAZARD -- the migration gap"
  note "live database head      : $(db_head)"
  note "source tree tops out at : $(ls "$REPO/migrations/versions" | grep -E '^[0-9]{4}_' | sort | tail -1 | sed 's/\.py$//')"
  note "readiness asserts       : $TARGET_HEAD"
  note "An image built from this tree expects $TARGET_HEAD and sits not_ready until"
  note "alembic runs, and roll-release.sh does NOT run alembic. Step 1 does, first."

  say "the 24-hour problem -- know this before you start"
  note "device_route_support.SESSION_TTL is 24 HOURS, enforced in SQL. capture_policy"
  note "NEVER calls POST /v1/device-agent/{id}/session/rotate -- it has no rotation"
  note "code at all. So ~24h after step 3 every poll 401s, the gate reads"
  note "kernel_unreachable and the camera stands down. That is correct fail-safe"
  note "behaviour AND a daily outage. It is why step 7 refuses to retire the bridge."

  say "what would be baked into the new image"
  local dirty
  dirty=$( cd "$REPO" && git status --porcelain -- boltrig/ 2>/dev/null )
  if [ -z "$dirty" ]; then
    note "boltrig/ is clean at $( cd "$REPO" && git log --oneline -1 2>/dev/null )"
  else
    printf '%s\n' "$dirty" | sed 's/^/    /'
    note "^ these UNCOMMITTED files would ship in the image. A build ships the WORKING"
    note "  TREE, not a tag. If anything there is not the sensing work, another"
    note "  session's work-in-progress is about to be deployed. Stop and ask them."
  fi

  say "the camera this machine has"
  camera_probe

  say "preflight complete -- nothing was changed"
}

# ============================================================================
# key -- BOLTRIG_DEVICE_LEASE_SIGNING_KEY
#
# Prerequisite of step 3, but it must land BEFORE step 2, because env_file is
# read when the container is CREATED. Adding it now is inert until step 2
# recreates the kernel; adding it after step 2 would need another recreate.
# ============================================================================
step_key() {
  say "key: add BOLTRIG_DEVICE_LEASE_SIGNING_KEY to $REPO/.env"

  [ -f "$REPO/.env" ] || precondition_failed "$REPO/.env does not exist"
  if grep -q '^BOLTRIG_DEVICE_LEASE_SIGNING_KEY=..' "$REPO/.env"; then
    note "already present -- nothing to do."
    return 0
  fi
  note "PRECONDITION ok: the key is absent, which is why enrolment answers 503."

  say "what this would do"
  note "Append ONE line to $REPO/.env holding a fresh 32-byte urlsafe-base64 seed."
  note "It changes NO container. .env is gitignored and excluded by .dockerignore,"
  note "so the seed is never baked into an image."
  note "A copy of the current .env is kept in $STATE_DIR."
  applying || dry_stop

  confirm "add the signing key"
  mkstate
  cp -a "$REPO/.env" "$STATE_DIR/env.bak-$(date +%Y%m%d-%H%M%S)" || die "could not back up .env"
  local seed
  seed=$(python3 -c "import base64,secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b'=').decode())")
  {
    printf '\n# Added by scripts/activate-sensing.sh -- Ed25519 seed for device lease signing.\n'
    printf 'BOLTRIG_DEVICE_LEASE_SIGNING_KEY=%s\n' "$seed"
  } >> "$REPO/.env"

  say "POSTCONDITION"
  grep -q '^BOLTRIG_DEVICE_LEASE_SIGNING_KEY=..' "$REPO/.env" \
    || postcondition_failed "the key is still not in .env"
  note "present in .env."
  note "It is NOT in the running container yet, and will not be until step 2."
  note "Rotating it later invalidates every enrolled device."
}

# ============================================================================
# 1-migrate -- bring the live schema from 0070 to 0073. BEFORE the deploy.
#
# WHY BEFORE. readiness compares heads with STRICT EQUALITY. A new image on an
# old schema sits not_ready with a migration failure stacked on top of the
# model_gateway one, and you cannot tell the two apart. Migrating first means
# step 2 has exactly one new variable.
#
# WHY THIS IS SAFE AGAINST THE OLD CODE STILL RUNNING. All three revisions are
# additive and were read line by line:
#   0071  ALTER TABLE model_endpoints ADD COLUMN IF NOT EXISTS revision
#   0072  DROP + re-ADD device_lease_verb_valid, WIDENED by 'device.file.list'
#         (strictly wider: old code cannot violate a constraint that allows more)
#   0073  ALTER TABLE agent_capabilities ADD COLUMN IF NOT EXISTS model_routes
# and all three have working downgrade()s.
#
# WHY NOT `make migrate`. postgres publishes NO host port and the kernel's rootfs
# is read-only. The only way in is a throwaway container joined to the stack
# network -- the estate's own pattern (scripts/roll-migrate-stack.sh).
#
# WHY NOT roll-migrate-stack.sh ITSELF. It reads the target head from the TARGET
# IMAGE, and the new image does not exist yet at this point in the order. It
# would read the OLD image's 0070 and correctly conclude there is nothing to do.
# So the target head is taken from the source tree's readiness.py instead, and
# alembic is run in a throwaway container off the CURRENTLY RUNNING image -- it
# supplies alembic and psycopg, and /mig supplies the chain. migrations/env.py
# imports only os and alembic.context, so no boltrig model code is involved.
# ============================================================================
step_1_migrate() {
  say "1-migrate: alembic $BASE_HEAD -> $TARGET_HEAD, on the LIVE boltrig database"

  local head src_head
  head=$(db_head)
  [ -n "$head" ] || precondition_failed "could not read alembic_version from $PGCONTAINER"
  src_head=$(grep -m1 -oE '"[0-9]{4}_[a-z_]+"' "$REPO/boltrig/api/readiness.py" | tr -d '"')
  note "PRECONDITION live database head : $head"
  note "PRECONDITION readiness asserts   : $src_head"

  [ "$src_head" = "$TARGET_HEAD" ] || precondition_failed \
    "readiness.py asserts $src_head, but this script was written for $TARGET_HEAD" \
    "The tree moved. Re-read migrations/versions and update TARGET_HEAD before running this."
  if [ "$head" = "$TARGET_HEAD" ]; then
    note "already at $TARGET_HEAD -- nothing to apply."; return 0
  fi
  [ "$head" = "$BASE_HEAD" ] || precondition_failed \
    "the database is at $head, not the expected $BASE_HEAD" \
    "Something else migrated it. Do not run this blind -- find out what, first."

  local i missing=""
  for i in 0071 0072 0073; do
    ls "$REPO/migrations/versions/${i}_"*.py >/dev/null 2>&1 || missing="$missing $i"
  done
  [ -z "$missing" ] || precondition_failed "missing migration files:$missing"
  note "PRECONDITION 0071, 0072 and 0073 are all present in migrations/versions."

  say "what this would do"
  note "Stage the alembic chain inside the VM, then run it in a THROWAWAY container"
  note "joined to $NETWORK. The kernel container is not touched."
  cmd "orb -m $VM bash -lc 'rm -rf /tmp/roll-mig && mkdir -p /tmp/roll-mig && cp $REPO/alembic.ini /tmp/roll-mig/ && cp -r $REPO/migrations /tmp/roll-mig/migrations'"
  cmd "orb -m $VM docker run --rm -i --network $NETWORK -v /tmp/roll-mig:/mig:ro -w /mig -e DATABASE_URL=<from $CONTAINER> $IMAGE sh -lc 'python -m alembic upgrade $TARGET_HEAD'"
  note ""
  note "TAKE A DUMP FIRST if you want one. This script does not, because writing a"
  note "backup nobody verified is worse than saying plainly that there is none:"
  cmd "orb -m $VM docker exec $PGCONTAINER pg_dump -U boltrig -Fc boltrig > ~/boltrig-preflight.dump"
  note ""
  note "BETWEEN THIS STEP AND STEP 2 the running (old) kernel asserts $BASE_HEAD while"
  note "the database is at $TARGET_HEAD, so /readyz gains a migration mismatch. That is"
  note "EXPECTED and transient. The kernel keeps serving; only /readyz changes. Do not"
  note "chase it -- close it by running step 2."
  applying || dry_stop

  confirm "migrate the live database"

  vm "rm -rf /tmp/roll-mig && mkdir -p /tmp/roll-mig && cp $REPO/alembic.ini /tmp/roll-mig/ && cp -r $REPO/migrations /tmp/roll-mig/migrations" \
    || die "could not stage the alembic chain at /tmp/roll-mig -- nothing was migrated"

  # DATABASE_URL is read into a variable and never interpolated into a command
  # line: doing that has silently corrupted this credential before.
  local dburl
  dburl=$(dk exec "$CONTAINER" printenv DATABASE_URL 2>/dev/null | tr -d '\r')
  [ -n "$dburl" ] || die "no DATABASE_URL on $CONTAINER -- nothing was migrated"

  dk run --rm -i --network "$NETWORK" -v /tmp/roll-mig:/mig:ro -w /mig \
     -e DATABASE_URL="$dburl" "$IMAGE" sh -lc "python -m alembic upgrade '$TARGET_HEAD'" \
     2>&1 | tail -8 | sed 's/^/    /'

  say "POSTCONDITION -- the head the database actually reports"
  local now; now=$(db_head)
  note "alembic_version = ${now:-<empty>}"
  [ "$now" = "$TARGET_HEAD" ] || postcondition_failed \
    "the database is at ${now:-<empty>}, not $TARGET_HEAD"
  note "schema is at $TARGET_HEAD, the head the new image will assert."
  mkstate; printf '%s\n' "$head" > "$STATE_DIR/schema-was"
}

# ============================================================================
# 2-deploy -- rebuild the kernel image and recreate the container.
#
# THE ONE STEP THAT INTERRUPTS OTHER SESSIONS. boltrig-kernel-1 goes away and
# comes back.
#
# THE ROLLBACK HINGE. `compose build` retags boltrig/kernel:0.1.0, and the
# running image has NO OTHER TAG -- it becomes dangling, and one prune destroys
# the only thing you could go back to. So the running image is tagged FIRST.
# That retag is the entire rollback.
#
# --no-deps is not optional. Without it compose reconsiders postgres, redis and
# hatchet-lite, and hatchet-lite regenerates its keyset on recreate, which
# invalidates the fleet worker's token.
# ============================================================================
step_2_deploy() {
  say "2-deploy: rebuild $IMAGE and recreate $CONTAINER"

  local head
  head=$(db_head)
  note "PRECONDITION live database head : $head"
  [ "$head" = "$TARGET_HEAD" ] || precondition_failed \
    "the database is at ${head:-<empty>}, but the new image asserts $TARGET_HEAD" \
    "Run 1-migrate first. Deploying now gives you TWO readiness failures and no way" \
    "to tell them apart."

  grep -q '^BOLTRIG_DEVICE_LEASE_SIGNING_KEY=..' "$REPO/.env" 2>/dev/null || precondition_failed \
    "BOLTRIG_DEVICE_LEASE_SIGNING_KEY is not in $REPO/.env" \
    "env_file is read at container-CREATE time, so it must be there BEFORE this" \
    "recreate, or step 3 gets 503 device_leases_unavailable and you need another" \
    "recreate to fix it. Run:  ./scripts/activate-sensing.sh key --apply"
  note "PRECONDITION signing key present in .env (it reaches the process on THIS recreate)."

  local src
  src=$(grep -c sensing "$REPO/boltrig/kernel/camera_agent_routes.py" 2>/dev/null); src=${src:-0}
  [ "$src" -gt 0 ] 2>/dev/null || precondition_failed \
    "the SOURCE camera_agent_routes.py contains no 'sensing'" \
    "There would be nothing to deploy. You are on the wrong tree or the wrong branch."
  note "PRECONDITION source camera_agent_routes.py mentions sensing $src times."

  local dirty
  dirty=$( cd "$REPO" && git status --porcelain -- boltrig/ 2>/dev/null )
  if [ -n "$dirty" ]; then
    say "UNCOMMITTED WORK THAT WOULD BE BAKED IN"
    printf '%s\n' "$dirty" | sed 's/^/    /'
    note "A build ships the WORKING TREE. Read that list before you continue."
  else
    note "PRECONDITION boltrig/ is clean at $( cd "$REPO" && git log --oneline -1 2>/dev/null )"
  fi

  local running
  running=$(dk inspect "$CONTAINER" --format '{{.Image}}' 2>/dev/null)
  [ -n "$running" ] || precondition_failed "cannot inspect $CONTAINER"

  local stamp tag
  stamp=$(date +%Y%m%d-%H%M%S)
  tag="boltrig/kernel:rollback-$stamp"

  say "what this would do"
  note "1. tag the RUNNING image so it survives the build -- this is the rollback:"
  cmd "orb -m $VM docker tag $running $tag"
  note "2. build (the container keeps running on the old image throughout):"
  cmd "orb -m $VM bash -lc 'cd $REPO && docker compose $COMPOSE_FILES build kernel'"
  note "3. check the NEW image really contains the route, BEFORE deploying it"
  note "4. recreate ONLY the kernel:"
  cmd "orb -m $VM bash -lc 'cd $REPO && docker compose $COMPOSE_FILES up -d --no-deps kernel'"
  note ""
  note "Other sessions lose the kernel for about one boot. It is ALREADY unhealthy"
  note "(FailingStreak $(dk inspect "$CONTAINER" --format '{{.State.Health.FailingStreak}}' 2>/dev/null), model_gateway probe_failed) and it will STILL say unhealthy"
  note "afterwards. That is not this deploy failing. See the postconditions below."
  applying || dry_stop

  confirm "rebuild and recreate the kernel"

  mkstate
  dk tag "$running" "$tag" || die "could not tag the running image -- refusing to build over it"
  printf '%s\n' "$tag"     > "$STATE_DIR/rollback-image"
  printf '%s\n' "$running" > "$STATE_DIR/rollback-image-id"
  note "preserved: $tag"

  vm "cd $REPO && docker compose $COMPOSE_FILES build kernel" \
    || die "build failed -- NOTHING was deployed, the old container is still running"

  say "checking the new image BEFORE deploying it"
  # --entrypoint sh overrides kernel-entrypoint.py; verified against this image.
  local baked
  baked=$(dk run --rm --entrypoint sh "$IMAGE" -c \
            'grep -c sensing /app/boltrig/kernel/camera_agent_routes.py' 2>/dev/null | tr -d '\r')
  note "occurrences of 'sensing' in the new image: ${baked:-0}"
  [ "${baked:-0}" -gt 0 ] 2>/dev/null || postcondition_failed \
    "the newly built image STILL has no sensing route -- the build used a stale context"
  local want
  want=$(dk run --rm "$IMAGE" python -c \
    'from boltrig.api.readiness import EXPECTED_ALEMBIC_HEAD as h; print(h)' 2>/dev/null | tr -d '\r')
  note "head the new image asserts: ${want:-<unknown>}"
  [ "$want" = "$TARGET_HEAD" ] || postcondition_failed \
    "the new image asserts ${want:-<unknown>}, but the database was migrated to $TARGET_HEAD"

  say "recreating the container"
  vm "cd $REPO && docker compose $COMPOSE_FILES up -d --no-deps kernel" \
    || postcondition_failed "compose up failed"

  say "waiting for the API to answer (NOT for 'healthy' -- it will not be)"
  local i
  for i in $(seq 1 60); do
    curl -fsS -m 3 "$KERNEL/healthz" >/dev/null 2>&1 && break
    sleep 2
  done
  curl -fsS -m 3 "$KERNEL/healthz" >/dev/null 2>&1 \
    || postcondition_failed "the kernel never answered /healthz"

  say "POSTCONDITION 1 -- a direct grep of the file INSIDE the running container"
  local live; live=$(deployed_sensing_count)
  note "occurrences of 'sensing' in the deployed camera_agent_routes.py: $live"
  [ "$live" -gt 0 ] 2>/dev/null || postcondition_failed \
    "the running container STILL has no sensing route -- it did not take the new image"

  say "POSTCONDITION 2 -- the route's own HTTP status"
  local code
  code=$(http_code "$KERNEL/v1/device-agent/x/sensing-config")
  note "GET /v1/device-agent/x/sensing-config -> $code   (404 = old image; 401 = route live, refusing an unauthenticated caller)"
  [ "$code" = "401" ] || postcondition_failed \
    "sensing-config answered $code, not 401. The deploy did not take."

  say "POSTCONDITION 3 -- the migration heads must AGREE"
  curl -s -m 5 "$KERNEL/readyz" | python3 -c '
import json,sys
d=json.load(sys.stdin); c=d.get("checks",{}); m=c.get("migration",{})
print("    migration     :", m)
print("    model_gateway :", c.get("model_gateway"))
sys.exit(0 if m.get("expected")==m.get("current") else 3)
'
  [ "$?" = "0" ] || postcondition_failed \
    "the migration heads DISAGREE -- step 1 did not do what it said"

  say "deployed"
  note "The container will still report UNHEALTHY. That is model_gateway, it was"
  note "failing long before you started, and this script does not fix it."
}

# ============================================================================
# 3-enrol -- mint a real device credential.
#
# WHY NOT A HAND-WRITTEN FILE. capture_policy._credential() only checks the SHAPE
# ({device_id, token}, both non-empty strings). A hand-written one passes that and
# is then rejected by authenticate_device_session as invalid_device_session --
# WORSE than no file at all, because the host then looks provisioned.
#
# THE REAL ISSUANCE:
#   POST /v1/devices/enrollment/start          human principal, cookie + CSRF
#        {"label": "..."} -> {"authorization_code", ...}   valid 10 minutes
#   POST /v1/device-agent/enrollment/complete  UNAUTHENTICATED; the code IS the auth
#        {"authorization_code", "device_public_key"} -> {"session_token", "device":{"id"}}
#
# AUTH. BOLTRIG_AUTH_MODE=session, so the dev-header resolver is not in play. A
# PAT would satisfy start_enrollment (actor_tier=="human") but NOT step 5, which
# additionally demands is_interactive_credential() -- PATs are deliberately
# excluded there. One session cookie serves both, so this logs in.
#
# device_public_key is length-checked and fingerprinted and NEVER verified --
# nothing in the kernel reads devices.public_key -- so 32 random bytes are honest
# here: this agent signs nothing.
#
# owner_id comes from the ENROLMENT ROW, not the body, so the device's owner is
# whoever logs in below. That must be the same person whose settings step 5
# writes, and it is, by construction: same login.
# ============================================================================
login() {
  mkstate
  COOKIEJAR="$STATE_DIR/cookies"
  : > "$COOKIEJAR"; chmod 600 "$COOKIEJAR"
  local pw
  if [ -n "${BOLTRIG_LOGIN_PASSWORD:-}" ]; then pw="$BOLTRIG_LOGIN_PASSWORD"
  else printf '    password for %s: ' "$EMAIL"; read -rs pw; printf '\n'; fi
  local body
  body=$(curl -s -m 15 -c "$COOKIEJAR" -X POST "$KERNEL/v1/auth/login" \
          -H 'content-type: application/json' \
          --data "$(python3 -c 'import json,sys;print(json.dumps({"email":sys.argv[1],"password":sys.argv[2]}))' "$EMAIL" "$pw")")
  unset pw
  CSRF=$(printf '%s' "$body" | python3 -c '
import json,sys
d=json.load(sys.stdin)
if d.get("status") != "ok":
    sys.exit("login did not return a usable session: " + json.dumps(d))
print(d["csrf_token"])
') || die "login failed -- nothing was changed"
  note "logged in; session cookie (12h) and CSRF token held for this step only"
}

api_post() {
  curl -s -m 20 -b "$COOKIEJAR" -X POST "$KERNEL$1" \
    -H 'content-type: application/json' -H "x-boltrig-csrf: $CSRF" --data "$2"
}
api_put() {
  curl -s -m 20 -b "$COOKIEJAR" -X PUT "$KERNEL$1" \
    -H 'content-type: application/json' -H "x-boltrig-csrf: $CSRF" --data "$2"
}

step_3_enrol() {
  say "3-enrol: mint a device credential and write $CRED"

  local code
  code=$(http_code "$KERNEL/v1/device-agent/x/sensing-config")
  note "PRECONDITION sensing-config route -> $code"
  [ "$code" = "401" ] || precondition_failed \
    "the sensing-config route answers $code, not 401" \
    "The new image is not deployed. Run 2-deploy first -- a credential minted" \
    "against a kernel that cannot serve the config is of no use."

  [ -e "$CRED" ] && precondition_failed \
    "$CRED already exists" \
    "This script will not overwrite a credential. Read it, decide, and move it" \
    "aside yourself. capture_policy is reading that file right now."
  note "PRECONDITION $CRED does not exist."

  say "what this would do"
  note "Create ONE devices row and consume ONE device_enrollments row, then write a"
  note "0600 credential at the path capture_policy already reads."
  cmd "POST $KERNEL/v1/auth/login                       (cookie + CSRF)"
  cmd "POST $KERNEL/v1/devices/enrollment/start         {\"label\": \"$LABEL\"}"
  cmd "POST $KERNEL/v1/device-agent/enrollment/complete {\"authorization_code\", \"device_public_key\"}"
  cmd "write $CRED  {\"device_id\", \"token\"}  mode 0600"
  note ""
  note "KNOW THIS BEFORE YOU START. The device session expires in 24 HOURS and"
  note "NOTHING ROTATES IT -- capture_policy has no rotation code at all. About a day"
  note "from now every poll 401s and the camera stands down. That is why step 7"
  note "refuses to retire the bridge."
  applying || dry_stop

  confirm "enrol this machine as a device"
  login

  local start acode
  start=$(api_post /v1/devices/enrollment/start \
    "$(python3 -c 'import json,sys;print(json.dumps({"label":sys.argv[1]}))' "$LABEL")")
  acode=$(printf '%s' "$start" | python3 -c '
import json,sys
d=json.load(sys.stdin)
if "authorization_code" not in d:
    sys.exit("enrollment/start refused: " + json.dumps(d)
             + "\n(503 device_leases_unavailable means the signing key is still not in"
               " the RUNNING container -- the key step ran but the recreate did not)")
print(d["authorization_code"])
') || die "could not start enrolment -- no device was created"
  note "authorization code minted (valid 10 minutes)"

  local complete
  complete=$(curl -s -m 20 -X POST "$KERNEL/v1/device-agent/enrollment/complete" \
    -H 'content-type: application/json' \
    --data "$(python3 -c '
import base64,json,os,sys
print(json.dumps({"authorization_code": sys.argv[1],
                  "device_public_key": base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode()}))
' "$acode")")

  # The token is written by python straight from the response and never passes
  # through a shell variable: a secret that never reaches the shell cannot reach
  # shell history, a trace, or another process's view of argv.
  mkdir -p "$HOME/.boltrig"; chmod 700 "$HOME/.boltrig"
  printf '%s' "$complete" | python3 -c '
import json, os, sys
cred, state = sys.argv[1], sys.argv[2]
d = json.load(sys.stdin)
if d.get("status") != "ok":
    sys.exit("enrollment/complete refused: " + json.dumps(d))
device = d["device"]["id"]
fd = os.open(cred, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, "w") as fh:
    # expires_at GOES IN THE CREDENTIAL, beside the token it belongs to. The
    # session is 24h and capture_policy._maybe_rotate renews it at the halfway
    # mark, but only if it can see when that is -- and it cannot derive it: the
    # token is base64url JSON carrying {version, kind, tenant_id, subject_id,
    # secret} and no expiry, so this reply is the only time the kernel ever says.
    # It used to be written to $STATE_DIR/session-expires only, which no daemon
    # reads. That was not unsafe -- an absent expiry reads as UNKNOWN and renews
    # at the next poll -- but it spent a rotation to learn what was already in
    # this response, and every rotation is a chance to lose the reply.
    json.dump({"device_id": device, "token": d["session_token"],
               "expires_at": d["session_expires_at"]}, fh)
    fh.write("\n")
open(os.path.join(state, "device-id"), "w").write(device + "\n")
open(os.path.join(state, "session-expires"), "w").write(d["session_expires_at"] + "\n")
' "$CRED" "$STATE_DIR" || die "could not complete enrolment"

  say "POSTCONDITION -- the credential must actually authenticate"
  local device expires perms
  device=$(cat "$STATE_DIR/device-id"); expires=$(cat "$STATE_DIR/session-expires")
  perms=$(stat -f '%Lp' "$CRED" 2>/dev/null)
  note "device_id  $device"
  note "expires    $expires   <-- 24h; capture_policy renews at the 12h mark"
  note "mode       $perms"
  [ "$perms" = "600" ] || postcondition_failed "$CRED is mode $perms, not 600"

  # The shape check is not enough -- a hand-written file passes that. This makes
  # the kernel answer.
  local token
  token=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["token"])' "$CRED")
  local scode
  scode=$(curl -s -o /dev/null -w '%{http_code}' -m 10 \
    -H "authorization: Bearer $token" "$KERNEL/v1/device-agent/$device/sensing-config")
  note "GET /v1/device-agent/$device/sensing-config -> $scode   (200 = the token is real)"
  [ "$scode" = "200" ] || postcondition_failed \
    "the minted credential got $scode, not 200 -- it does not authenticate"
  note "the credential authenticates against the live kernel."
}

# ============================================================================
# 4-bind -- publish the camera binding.
#
# DEVICE-authenticated, not human-authenticated: a binding is a statement about
# hardware, made by the process next to the hardware.
#
# ptz_get_state / ptz_set_state are "unknown" ON PURPOSE. This path never probed
# UVC. "proven" additionally requires the evidence string
# bounded_uvc_set_readback_frame_change_and_exact_restoration, and claiming it
# without the evidence is exactly the unearned assertion the kernel refuses.
# Nothing downstream reads those fields -- sensing_config carries only camera_id
# and descriptor_fingerprint.
# ============================================================================
step_4_bind() {
  say "4-bind: publish the camera binding"

  require_state device-id
  local device; device=$(state device-id)
  [ -f "$CRED" ] || precondition_failed "$CRED is missing -- run 3-enrol first"
  note "PRECONDITION device_id $device with a credential on disk."
  camera_probe

  say "what this would do"
  cmd "POST $KERNEL/v1/device-agent/$device/camera-bindings   (Bearer <device session>)"
  note "body: camera_id=$CAMERA_ID"
  note "      descriptor_fingerprint=$FINGERPRINT"
  note "      connection_state=connected  ptz_get_state=unknown  ptz_set_state=unknown"
  note "      label=\"$CAMERA_NAME\"  product=\"${MODEL_ID:-unknown}\"  transport=avfoundation"
  note ""
  note "This creates ONE camera_bindings row. There is NO delete route for it."
  applying || dry_stop

  confirm "publish this binding"

  local token out
  token=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["token"])' "$CRED")
  out=$(curl -s -m 20 -X POST "$KERNEL/v1/device-agent/$device/camera-bindings" \
    -H "authorization: Bearer $token" -H 'content-type: application/json' \
    --data "$(python3 -c '
import json,sys
cid,fp,label,model = sys.argv[1:5]
print(json.dumps({
  "camera_id": cid,
  "descriptor_fingerprint": fp,
  "connection_state": "connected",
  "ptz_get_state": "unknown",
  "ptz_set_state": "unknown",
  "label": label,
  "product": model,
  "transport": "avfoundation",
  "capabilities": {},
  "evidence": [],
}))
' "$CAMERA_ID" "$FINGERPRINT" "$CAMERA_NAME" "${MODEL_ID:-unknown}")")

  say "POSTCONDITION -- the kernel must echo the binding back"
  printf '%s' "$out" | python3 -c '
import json,sys
want = sys.argv[1]
d = json.load(sys.stdin)
b = d.get("binding")
if not b:
    sys.exit("binding refused: " + json.dumps(d))
if b.get("camera_id") != want:
    sys.exit("kernel stored camera_id %r, not %r" % (b.get("camera_id"), want))
print("    bound:", b["camera_id"], "-", b.get("label"))
' "$CAMERA_ID" || postcondition_failed "the binding was refused or came back wrong"

  mkstate
  printf '%s\n' "$CAMERA_ID"   > "$STATE_DIR/camera-id"
  printf '%s\n' "$FINGERPRINT" > "$STATE_DIR/fingerprint"
}

# ============================================================================
# 5-enable -- write the user_settings sensing row. THE CONSENT DECISION ITSELF.
#
# THE RAW SETTINGS BAG IS REFUSED. PUT /v1/me/settings answers 400 "use the
# sensing endpoints" for every key in sensing_policy.SENSING_KEYS. The validated
# route is PUT /v1/me/sensing/camera.
#
# It requires an INTERACTIVE credential (session/federated/dev-header). A PAT is
# refused 403 even carrying actor_tier="human" -- config/dev_posture
# .INTERACTIVE_CREDENTIAL_KINDS. Hence the login.
#
# It also re-checks the binding against camera_bindings (_known_camera) and
# answers 409 camera_binding_unavailable for a camera nobody published. That is
# why step 4 comes first.
# ============================================================================
step_5_enable() {
  say "5-enable: turn the camera on in the owner's settings"

  local device camera fp
  require_state device-id camera-id fingerprint
  device=$(state device-id); camera=$(state camera-id); fp=$(state fingerprint)
  note "PRECONDITION device_id $device"
  note "PRECONDITION camera_id $camera  (bound in step 4)"

  say "what this would do"
  cmd "PUT $KERNEL/v1/me/sensing/camera   (session cookie + x-boltrig-csrf)"
  note "body: {\"enabled\": true, \"camera_id\": \"$camera\","
  note "       \"device_id\": \"$device\","
  note "       \"descriptor_fingerprint\": \"$fp\","
  note "       \"label\": \"$CAMERA_NAME\"}"
  note ""
  note "This writes sensing.camera.enabled=true and the binding for $EMAIL."
  note "It IS the consent decision. Presence stays off -- PUT /v1/me/sensing/presence"
  note "refuses 409 until a room-calibrated threshold has been published. Separate job."
  applying || dry_stop

  confirm "enable the camera"
  login

  api_put /v1/me/sensing/camera "$(python3 -c '
import json,sys
print(json.dumps({"enabled": True, "camera_id": sys.argv[1], "device_id": sys.argv[2],
                  "descriptor_fingerprint": sys.argv[3], "label": sys.argv[4]}))
' "$camera" "$device" "$fp" "$CAMERA_NAME")" | python3 -c '
import json,sys
d=json.load(sys.stdin)
if d.get("status") != "ok":
    sys.exit("refused: " + json.dumps(d))
print("   ", json.dumps(d, indent=2).replace("\n","\n    "))
' || postcondition_failed "the settings write was refused"

  say "POSTCONDITION -- what the DEVICE now reads back"
  # The settings write returning ok is not enough. The thing that matters is what
  # the device-authenticated sensing-config endpoint says, because that is the
  # only thing capture_policy ever looks at.
  local token
  token=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["token"])' "$CRED")
  curl -s -m 10 -H "authorization: Bearer $token" \
    "$KERNEL/v1/device-agent/$device/sensing-config" | python3 -c '
import json,sys
d=json.load(sys.stdin)
c=d.get("camera",{})
print("    camera:", json.dumps(c))
if c.get("enabled") is not True: sys.exit("camera is not enabled in the device-visible config")
if not c.get("camera_id"):       sys.exit("no camera_id in the device-visible config")
print("    the device sees an enabled, bound camera.")
' || postcondition_failed "the device-visible sensing-config does not show an enabled, bound camera"
}

# ============================================================================
# 6-verify -- READ ONLY, and the only honest proof. Runs regardless of --apply.
#
# It empties BOLTRIG_SENSING_UNMANAGED for ONE short-lived probe process. No
# plist is touched, no daemon is restarted, capture_policy.py is not edited.
# ============================================================================
step_6_verify() {
  say "6-verify: does the gate GRANT on the kernel's own answer?"

  local device token
  require_state device-id
  device=$(state device-id)
  [ -f "$CRED" ] || precondition_failed "$CRED is missing -- run 3-enrol first"
  token=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["token"])' "$CRED")

  say "the exact call capture_policy._fetch() makes"
  curl -s -m 10 -H "authorization: Bearer $token" \
    "$KERNEL/v1/device-agent/$device/sensing-config" | python3 -c '
import json,sys
d=json.load(sys.stdin)
print("   ", json.dumps(d, indent=2).replace("\n","\n    "))
if d.get("v") != 1: sys.exit("wrong schema version")
c=d.get("camera",{})
if c.get("enabled") is not True: sys.exit("camera is not enabled")
if not c.get("camera_id"):       sys.exit("no camera_id -- the binding did not land")
print("\n    config parses, camera enabled, camera bound.")
' || postcondition_failed "sensing-config did not answer usefully"

  say "the gate itself, with the bridge switched off for ONE probe process"
  note "BOLTRIG_SENSING_UNMANAGED is emptied for this python only. No plist is"
  note "edited. No daemon is restarted. camerad is not touched."
  [ -x "$OBS/.venv/bin/python" ] || precondition_failed "no interpreter at $OBS/.venv/bin/python"
  ( cd "$OBS" && BOLTRIG_SENSING_UNMANAGED= "$OBS/.venv/bin/python" -c '
import capture_policy as p
d = p.camera_gate(force=True)
print("    allowed :", bool(d))
print("    reason  :", d.reason)
print("    detail  :", d.detail or "-")
print("    camera  :", (d.config or {}).get("camera"))
raise SystemExit(0 if d else 1)
' ) || postcondition_failed "the gate still REFUSES with the bridge off -- read the reason above"

  say "GRANTED, from the kernel. All four blockers are closed."
  note "The bridge is now provably unnecessary -- but it is still in place, and"
  note "step 7 explains why you should think hard before removing it today."
}

# ============================================================================
# 7-retire -- PRINTS ONLY. Performs nothing, in --apply or out of it.
# ============================================================================
step_7_retire() {
  say "7-retire -- THIS SCRIPT WILL NOT DO THIS FOR YOU"
  cat <<EOF

    Retiring the bridge is two edits, and they are yours to make, attended, one
    at a time.

    (a) THE THREE PLISTS. Remove the BOLTRIG_SENSING_UNMANAGED entry (the <key>
        and its <string>1</string>) from each of:

            ~/Library/LaunchAgents/app.companion.observer.plist
            ~/Library/LaunchAgents/app.pixy.presence.plist
            ~/Library/LaunchAgents/app.pixy.camerad.plist

        Each takes effect only when that job is reloaded:

            launchctl bootout   gui/\$(id -u)/<label>
            launchctl bootstrap gui/\$(id -u) ~/Library/LaunchAgents/<label>.plist

        ORDER MATTERS AND camerad IS LAST. Reloading camerad restarts it, and a
        second camerad contending for the UVC device is recovered only by
        PHYSICALLY UNPLUGGING the Pixy. Do the observer first -- its restart
        costs nothing -- then presence, then camerad on its own, watched.

    (b) THE BRANCH IN capture_policy.py. In
        $OBS/capture_policy.py:

            line 110        UNMANAGED = os.environ.get("BOLTRIG_SENSING_UNMANAGED", "") == "1"
                            (with its comment, lines 105-109)
            lines 332-368   the whole \`if UNMANAGED:\` branch at the top of
                            camera_gate(), ending at
                              return Decision(True, GRANTED,
                                              "unmanaged host: no kernel sensing route", {})

        Delete both. camera_gate() then begins at
            config, reason, detail = sensing_config(force)
        which is the code step 6 just proved GRANTS.

    DO NOT DO EITHER OF THESE YET IF THE 24-HOUR PROBLEM IS STILL OPEN.
    The device session minted in step 3 expires in 24 hours and NOTHING rotates
    it: capture_policy has no call to POST /v1/device-agent/{id}/session/rotate
    anywhere. With the bridge removed, that expiry stands the camera down until
    someone re-enrols by hand -- a daily outage, arriving quietly.

    Either teach the agent to rotate first, or keep the bridge and treat this
    activation as PROVEN BUT NOT ADOPTED. Proven is already worth having: it
    means the comment in capture_policy.py describing four blockers is now
    describing history.

EOF
}

# ============================================================================
# rollbacks
# ============================================================================
rollback_image() {
  say "rollback-image: put the previous kernel image back"
  require_state rollback-image
  local tag; tag=$(state rollback-image)
  note "would retag $tag -> $IMAGE and recreate the container"
  cmd "orb -m $VM docker tag $tag $IMAGE"
  cmd "orb -m $VM bash -lc 'cd $REPO && docker compose $COMPOSE_FILES up -d --no-deps kernel'"
  note ""
  note "NOTE: if 1-migrate ran, the schema is at $TARGET_HEAD and this old image"
  note "asserts $BASE_HEAD. It will SERVE, but /readyz gains a migration failure."
  note "Run rollback-schema too if you want the old readiness back."
  applying || { say "DRY RUN -- nothing was executed"; exit 0; }
  confirm "roll the kernel image back"
  dk tag "$tag" "$IMAGE" || die "retag failed"
  vm "cd $REPO && docker compose $COMPOSE_FILES up -d --no-deps kernel" || die "compose up failed"
  local live; live=$(deployed_sensing_count)
  note "occurrences of 'sensing' in the deployed file: $live   (0 = the old image is back)"
}

rollback_schema() {
  say "rollback-schema: $TARGET_HEAD -> $BASE_HEAD"
  note "0072's downgrade REFUSES while any device.file.list lease exists -- by design."
  cmd "orb -m $VM docker run --rm -i --network $NETWORK -v /tmp/roll-mig:/mig:ro -w /mig -e DATABASE_URL=<from $CONTAINER> $IMAGE sh -lc 'python -m alembic downgrade $BASE_HEAD'"
  applying || { say "DRY RUN -- nothing was executed"; exit 0; }
  confirm "downgrade the live schema"
  vm "rm -rf /tmp/roll-mig && mkdir -p /tmp/roll-mig && cp $REPO/alembic.ini /tmp/roll-mig/ && cp -r $REPO/migrations /tmp/roll-mig/migrations" \
    || die "could not stage the alembic chain"
  local dburl; dburl=$(dk exec "$CONTAINER" printenv DATABASE_URL 2>/dev/null | tr -d '\r')
  [ -n "$dburl" ] || die "no DATABASE_URL on $CONTAINER"
  dk run --rm -i --network "$NETWORK" -v /tmp/roll-mig:/mig:ro -w /mig \
     -e DATABASE_URL="$dburl" "$IMAGE" sh -lc "python -m alembic downgrade '$BASE_HEAD'" \
     2>&1 | tail -8 | sed 's/^/    /'
  note "head now: $(db_head)"
}

rollback_sensing() {
  say "rollback-sensing: camera off, binding cleared, device revoked, credential moved aside"
  note "There is NO delete route for camera_bindings -- that row stays, inert."
  note "Clearing the SETTINGS binding is what actually withdraws consent."
  cmd "PUT    $KERNEL/v1/me/sensing/camera  {\"enabled\": false, \"camera_id\": null}"
  cmd "DELETE $KERNEL/v1/devices/<device_id>"
  cmd "mv $CRED $CRED.revoked-<stamp>"
  note ""
  note "The UNMANAGED bridge is untouched, so the daemons keep working exactly as now."
  applying || { say "DRY RUN -- nothing was executed"; exit 0; }
  confirm "undo the sensing activation"
  login
  api_put /v1/me/sensing/camera '{"enabled": false, "camera_id": null}' | head -c 400; echo
  if [ -f "$STATE_DIR/device-id" ]; then
    local device; device=$(cat "$STATE_DIR/device-id")
    curl -s -m 20 -b "$COOKIEJAR" -X DELETE "$KERNEL/v1/devices/$device" \
      -H "x-boltrig-csrf: $CSRF" | head -c 400; echo
  fi
  [ -f "$CRED" ] && { mv "$CRED" "$CRED.revoked-$(date +%Y%m%d-%H%M%S)"; note "credential moved aside"; }
  note "done."
}

usage() { sed -n '2,60p' "$0"; exit 2; }

# ============================================================================
# argument parsing -- --apply may appear before or after the step name.
# ============================================================================
for arg in "$@"; do
  case "$arg" in
    --apply) APPLY=1 ;;
    --help|-h) usage ;;
    -*) die "unknown option: $arg" ;;
    *) [ -z "$STEP" ] && STEP="$arg" || die "only one step at a time" ;;
  esac
done

[ -n "$STEP" ] || usage

if applying; then
  printf '\n*** --apply: THIS RUN WILL CHANGE THE LIVE SYSTEM ***\n'
else
  printf '\n*** DRY RUN (no --apply): read-only checks run, nothing is changed ***\n'
fi

case "$STEP" in
  0-preflight|preflight) step_0_preflight ;;
  key)                   step_key ;;
  1-migrate)             step_1_migrate ;;
  2-deploy)              step_2_deploy ;;
  3-enrol|3-enroll)      step_3_enrol ;;
  4-bind)                step_4_bind ;;
  5-enable)              step_5_enable ;;
  6-verify)              step_6_verify ;;
  7-retire)              step_7_retire ;;
  rollback-image)        rollback_image ;;
  rollback-schema)       rollback_schema ;;
  rollback-sensing)      rollback_sensing ;;
  *) usage ;;
esac
