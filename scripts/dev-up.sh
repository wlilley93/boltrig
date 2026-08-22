#!/usr/bin/env bash
# Bring the local Boltrig dev stack up and expose it on the tailnet.
#
# Assumes .env (dev auth, model key) and manifest.yaml (tenant=default, the GLM
# coding endpoint + glm-5.2) already exist on this box - both are gitignored
# runtime artifacts. Re-run any time to relaunch.
#
#   scripts/dev-up.sh           # build (if needed) + up + serve
#   tailscale serve --https=10000 off   # to take the tailnet origin down
#   docker compose down                 # to stop the stack
set -euo pipefail
cd "$(dirname "$0")/.."

COMPOSE=(docker compose --profile gateway -f docker-compose.yml -f deploy/compose.dev.yml)

echo "== bringing up the core stack (kernel/fleet/worker/bifrost/caddy + pg/redis) =="
"${COMPOSE[@]}" up -d --build kernel fleet-worker ui bifrost caddy

echo "== waiting for the kernel to be healthy =="
for i in $(seq 1 30); do
  if curl -fsS -m3 http://127.0.0.1:8000/healthz >/dev/null 2>&1; then echo "kernel healthy"; break; fi
  sleep 2
done

echo "== exposing one tailnet origin on :10000 (UI + kernel) =="
tailscale serve --https=10000 off >/dev/null 2>&1 || true
tailscale serve --bg --https=10000 --set-path=/v1 http://127.0.0.1:8000/v1 >/dev/null
tailscale serve --bg --https=10000 --set-path=/healthz http://127.0.0.1:8000/healthz >/dev/null
tailscale serve --bg --https=10000 --set-path=/ http://127.0.0.1:8080 >/dev/null

URL="https://$(tailscale status --json 2>/dev/null | grep -oE '"DNSName": "[^"]+' | head -1 | cut -d'"' -f4 | sed 's/\.$//'):10000"
echo
echo "Boltrig is up:  ${URL}"
echo "(tailnet-only; tenant 'default'; live agent chat on the GLM coding endpoint via Bifrost when configured)"
