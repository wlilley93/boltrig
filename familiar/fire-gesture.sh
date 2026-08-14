#!/usr/bin/env bash
# fire-gesture - fire a voluntary gesture at the desktop familiar (WL-3).
#
# It does NOT write the express channel directly. It goes through boltrig's governed familiar.express
# verb - the one dispatch chokepoint: schema-validated, grant-checked, audited, exactly as an agent
# would. That is the whole point of WL-3: there is no side door from you (or an agent) to the surface.
# The dispatched handler is the only writer of $XDG_RUNTIME_DIR/boltrig-express.json, which the running
# familiar reads and renders as a short decaying gesture over its current mood.
#
# Usage: fire-gesture <gesture> [intensity 0..1] [ttl_s]
#   gestures: look pulse flinch celebrate greet nod recoil preen
#   e.g.      fire-gesture celebrate         fire-gesture pulse 1.0 4
#
# It runs the dispatch inside the kernel container (override with FAMILIAR_KERNEL_CONTAINER), so the
# express file lands in the shared handoff dir the familiar's symlink points at.
set -uo pipefail

GESTURES="look pulse flinch celebrate greet nod recoil preen"
CONTAINER="${FAMILIAR_KERNEL_CONTAINER:-boltrig-kernel-1}"

g="${1:-}"; intensity="${2:-0.9}"; ttl="${3:-3}"
if [ -z "$g" ] || ! grep -qw -- "$g" <<<"$GESTURES"; then
  echo "usage: fire-gesture <gesture> [intensity 0..1] [ttl_s]" >&2
  echo "gestures: $GESTURES" >&2
  exit 2
fi
case "$intensity" in ""|*[!0-9.]*) echo "intensity must be a number 0..1" >&2; exit 2;; esac
case "$ttl"       in ""|*[!0-9.]*) echo "ttl_s must be a number" >&2; exit 2;; esac

if ! docker inspect "$CONTAINER" >/dev/null 2>&1; then
  echo "kernel container '$CONTAINER' not found - is boltrig up? (override with FAMILIAR_KERNEL_CONTAINER)" >&2
  exit 1
fi

docker exec -e FG_G="$g" -e FG_I="$intensity" -e FG_T="$ttl" -e FG_ACTOR="${USER:-operator}" \
  "$CONTAINER" python -c '
import asyncio, os
async def main():
    from boltrig.store import InMemoryStore
    from boltrig.kernel import Kernel
    from boltrig.models import GrantSet, InvocationContext, TenantPermissions
    from boltrig.adapters.builtin.familiar import build
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions("default", GrantSet.of(["familiar.*"])))
    kernel = Kernel(store, blocking_verbs=set())
    await kernel.register_adapter("default", build())
    ctx = InvocationContext(tenant_id="default", grants=GrantSet.of(["familiar.express"]),
                            actor=os.environ["FG_ACTOR"], actor_tier="ephemeral", run_id="fire-gesture")
    out = await kernel.invoke("familiar", "familiar.express",
        {"gesture": os.environ["FG_G"], "intensity": float(os.environ["FG_I"]),
         "ttl_s": float(os.environ["FG_T"])}, ctx)
    rows = await kernel.store.audit_query("default")
    print("fired %s (intensity %s, ttl %ss) -> delivered=%s, dispatch %s + audited"
          % (out["gesture"], os.environ["FG_I"], os.environ["FG_T"], out["delivered"], rows[-1].status))
asyncio.run(main())
' || { echo "dispatch failed (is BOLTRIG_EMOTION=1 and familiar.express registered?)" >&2; exit 1; }

if pgrep -x familiar-bg >/dev/null 2>&1; then
  echo "-> if your beelink display is live, the familiar is ${g}-ing now; if the monitor is off/KVM'd away it renders when the display returns." >&2
else
  echo "-> note: familiar-bg is not running (start it: systemctl --user start familiar.service)." >&2
fi
