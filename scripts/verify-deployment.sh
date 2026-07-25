#!/usr/bin/env bash
# Assert a boltrig stack is actually SERVING, not merely running.
#
# Written after a client tenant sat at readyz 503 for about forty minutes while
# `docker ps` said "healthy" the entire time. The container healthcheck is
# /healthz, which answers as soon as the process is up; it knows nothing about
# the schema. The stack had been rolled to an image whose EXPECTED_ALEMBIC_HEAD
# was one revision ahead of its database, so every request that touched the
# changed table would have failed - and nothing in the ordinary operational view
# said so.
#
# The rule this encodes: a roll is not finished when the container is up. It is
# finished when readyz says ready AND the running image demonstrably contains the
# change you rolled it for. Tags lie; imports do not.
#
# Usage:
#   verify-deployment.sh <container> [<symbol> ...]
#
#   <container>  the kernel container, e.g. cv-boltrig-kernel-1
#   <symbol>     optional "module:attribute" pairs asserted to exist INSIDE the
#                running container, e.g. boltrig.kernel.run_access:foreign_run_asserted
#
# Env:
#   REMOTE   ssh host to run against (default: local docker)
#
# Exit 0 only if every check passes.

set -uo pipefail

CONTAINER="${1:-}"
if [ -z "$CONTAINER" ]; then
    echo "usage: $(basename "$0") <kernel-container> [module:attr ...]" >&2
    exit 2
fi
shift || true
SYMBOLS=("$@")

REMOTE="${REMOTE:-}"
run() {
    if [ -n "$REMOTE" ]; then ssh -o ConnectTimeout=10 "$REMOTE" "$@"; else bash -c "$@"; fi
}

fail=0
say() { printf '  %-8s %s\n' "$1" "$2"; }

echo "verifying ${CONTAINER}${REMOTE:+ on $REMOTE}"

# 1. The container exists and is up. Necessary, nowhere near sufficient.
status="$(run "docker inspect -f '{{.State.Status}}' $CONTAINER 2>/dev/null" || true)"
if [ "$status" != "running" ]; then
    say "FAIL" "container is '${status:-absent}', not running"
    exit 1
fi
say "ok" "container running"

# 2. readyz, which is the check that actually knows about the schema. This is the
#    one the healthcheck does not do and the one the outage turned on.
ready="$(run "docker exec $CONTAINER python -c '
import json, urllib.request, urllib.error
try:
    r = urllib.request.urlopen(\"http://127.0.0.1:8000/readyz\", timeout=10)
    print(\"READY\", json.loads(r.read()).get(\"status\"))
except urllib.error.HTTPError as e:
    body = json.loads(e.read())
    bad = [k for k, v in (body.get(\"checks\") or {}).items()
           if isinstance(v, dict) and v.get(\"status\") not in (\"ok\", \"disabled\")]
    print(\"NOTREADY\", e.code, \",\".join(bad) or \"?\")
except Exception as e:
    print(\"UNREACHABLE\", type(e).__name__)
' 2>/dev/null" || true)"
case "$ready" in
    READY*) say "ok" "readyz ready" ;;
    *)      say "FAIL" "readyz: ${ready:-no answer}"; fail=1 ;;
esac

# 3. The image really contains what you rolled it for. A digest pin proves the
#    bytes are the ones you pushed; it proves nothing about whether the change
#    you meant is in them, which is the mistake worth designing against.
for pair in "${SYMBOLS[@]:-}"; do
    [ -z "$pair" ] && continue
    mod="${pair%%:*}"; attr="${pair##*:}"
    got="$(run "docker exec $CONTAINER python -c '
import importlib, sys
try:
    m = importlib.import_module(\"$mod\")
except Exception as e:
    print(\"IMPORTFAIL\", type(e).__name__); sys.exit()
print(\"PRESENT\" if hasattr(m, \"$attr\") else \"ABSENT\")
' 2>/dev/null" || true)"
    case "$got" in
        PRESENT) say "ok" "$mod.$attr present" ;;
        *)       say "FAIL" "$mod.$attr ${got:-unknown}"; fail=1 ;;
    esac
done

if [ "$fail" -ne 0 ]; then
    echo "VERIFY FAILED: ${CONTAINER} is running but not serving what you think"
    exit 1
fi
echo "VERIFY OK: ${CONTAINER}"
