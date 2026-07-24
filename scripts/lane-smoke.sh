#!/usr/bin/env bash
# lane-smoke.sh - one-shot kernel-tools lane diagnostic for the local dev box.
#
# Mints a short-lived PAT (via the box-level mint-token CLI), fires one chat turn
# that must drive a governed tool call, then gathers every signal that tells you
# WHERE the lane stands: the chat verdict (real answer vs degraded), the bifrost
# model-call status (200 vs 499/error), and the codex cell's content-free stderr
# markers surfaced on teardown. The PAT is revoked at the end.
#
# It changes NOTHING in the running system beyond the one test turn; safe to run
# repeatedly. Requires: the boltrig compose stack up on this box, and psql access
# via `docker compose exec postgres`.
#
# Usage:
#   scripts/lane-smoke.sh                       # default opbox.matter.list prompt
#   scripts/lane-smoke.sh "Use opbox.party.list and count the parties."
set -euo pipefail

OWNER_EMAIL="${LANE_SMOKE_EMAIL:-will.lilley93@gmail.com}"
KERNEL_URL="${LANE_SMOKE_KERNEL_URL:-http://127.0.0.1:8000}"
BIFROST_URL="${LANE_SMOKE_BIFROST_URL:-http://127.0.0.1:8081}"
MESSAGE="${1:-Use the opbox.matter.list tool to list matters and tell me the count.}"
COMPOSE="docker compose"

say() { printf '\n=== %s ===\n' "$1"; }

say "1/5 mint a short-lived PAT for ${OWNER_EMAIL}"
PAT="$($COMPOSE exec -T kernel python -m boltrig.api.cli mint-token \
  --email "$OWNER_EMAIL" --name "lane-smoke" --ttl-days 1 2>/dev/null | tail -1)"
if [[ "$PAT" != boltrig_pat_* ]]; then
  echo "FAILED to mint a PAT (got: ${PAT:0:24}...). Is the owner seeded?" >&2
  exit 1
fi
echo "minted ${PAT:0:18}..."

# Always revoke the PAT, even on error/interrupt.
cleanup() {
  $COMPOSE exec -T postgres psql -U boltrig -d boltrig -tAc \
    "update personal_access_tokens set revoked=true where name='lane-smoke' and revoked=false;" \
    >/dev/null 2>&1 || true
}
trap cleanup EXIT

say "2/5 fire the chat turn (SSE, 100s cap)"
SSE="$(curl -sS -N -m 100 "$KERNEL_URL/v1/chat" \
  -H "Authorization: Bearer $PAT" -H "Content-Type: application/json" \
  -d "$(printf '{"message":%s}' "$(printf '%s' "$MESSAGE" | python3 -c 'import json,sys;print(json.dumps(sys.stdin.read()))')")" \
  2>&1 || true)"
VERDICT="$(printf '%s' "$SSE" | grep -oE '"delta": "[^"]*"' | tail -1)"
echo "final delta: ${VERDICT:-<none>}"
if printf '%s' "$SSE" | grep -q '"degraded": true'; then
  echo "RESULT: DEGRADED"
else
  echo "RESULT: not flagged degraded (inspect the delta above for the real answer)"
fi

say "3/5 bifrost model-call status (most recent)"
curl -sS -m 8 "$BIFROST_URL/api/logs?limit=3" 2>/dev/null | python3 -c '
import sys, json
try: d=json.load(sys.stdin)
except Exception: print("  (bifrost logs unavailable)"); sys.exit()
items=d.get("logs") or d.get("data") or d.get("items") or (d if isinstance(d,list) else [])
for it in items[:3]:
    if not isinstance(it,dict): continue
    ed=it.get("error_details") or {}
    err=(ed.get("error") or {}) if isinstance(ed,dict) else {}
    print(f"  status={it.get(\"status\")} model={it.get(\"model\")} latency={it.get(\"latency\")}ms "
          f"err={err.get(\"type\")}:{err.get(\"message\")}" if err else
          f"  status={it.get(\"status\")} model={it.get(\"model\")} latency={it.get(\"latency\")}ms")
'

say "4/5 codex cell teardown markers (content-free, from the fleet-worker log)"
$COMPOSE logs --since 3m fleet-worker 2>&1 | grep -F "codex cell teardown" | tail -5 || true
if ! $COMPOSE logs --since 3m fleet-worker 2>&1 | grep -qF "codex cell teardown"; then
  echo "  (no teardown markers logged - either no degrade, or codex emitted no allowlisted token"
  echo "   at its current RUST_LOG level)"
fi

say "5/5 PAT revoked on exit"
echo "done."
