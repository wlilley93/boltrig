#!/bin/zsh
# boltrig's console (Vite SPA) as a NATIVE dev server on the M4, with hot reload.
#
# Port 8080 is not a preference: the shared cloudflare tunnel's ingress maps
# dev.boltrig.io -> http://localhost:8080 on whichever host runs the connector,
# and the connector runs on this Mac. Vite's own default is 5173.
#
# In production this SPA is served by nginx, which also reverse-proxies /v1,
# /healthz and /readyz to the kernel. In dev, vite.config.ts already does that
# proxying itself against BOLTRIG_KERNEL_URL - so pointing that at the kernel is
# all that replaces nginx here.
#
# The kernel runs in the OrbStack Linux machine `boltrig-vm`, NOT in the Mac's
# Docker engine: its boot-time sandbox proof shells out to bubblewrap, and a
# nested user namespace is refused inside a container on the Mac engine unless
# the container is fully --privileged. In the VM, seccomp:unconfined alone is
# enough, so the rest of the hardening survives. See docker-compose.vm.yml.
#
# node is pinned to 22.23.1 to match ui/Dockerfile's build stage; the PATH node
# on this box is v24.

export PATH="$HOME/opbox-dev/node-v22.23.1-darwin-arm64/bin:$PATH"
cd "$HOME/Projects/boltrig/ui" || exit 1

# Reach the kernel by OrbStack's stable machine domain rather than the VM's
# current IP, which is not guaranteed across VM restarts. KERNEL_PORT=18000 in
# .env because host 8000 on the Mac belongs to me-lora.
# The kernel lives in the boltrig-vm machine. Reaching it by NAME does not work
# from vite, and the reason is specific enough to be worth writing down:
#
# boltrig-vm.orb.local is dual-stack and its AAAA (fd07:...:cafe::3) is NOT
# routable from this host, while its A records are (measured: v4 -> 200,
# v6 -> refused). vite's proxy resolves with lookup-ALL and then races the
# addresses (node:dns onlookupall -> internalConnectMultiple), and that path
# surfaced an AggregateError [EHOSTUNREACH] for every /v1,/healthz,/readyz -
# serving 500 while the vite log looked healthy. Two things did NOT fix it:
# `curl` to the identical URL returns 200 (it falls back between addresses), and
# NODE_OPTIONS=--dns-result-order=ipv4first has no effect on the lookup-all path.
#
# So resolve the A record ONCE here and hand vite a literal. This keeps working
# when OrbStack reassigns the machine's address, which hardcoding the IP would
# not, and it avoids the v6 candidate entirely.
# LOOPBACK, deliberately - do NOT point this at the VM's address directly.
#
# The kernel really lives in the boltrig-vm machine on 192.168.139.x, but macOS 26
# Local Network Privacy blocks a launchd job from reaching a local-network address:
# this script serves /healthz 200 when launched from an interactive shell and
# EHOSTUNREACH when launchd starts it, same interface, same destination, while
# plain curl works throughout. Nothing about the address was ever wrong, so
# neither an IPv4 literal nor --dns-result-order fixes it.
#
# run-kernel-relay.sh (launchd: app.boltrig.kernel-relay) publishes the kernel on
# 127.0.0.1:18000 via an OrbStack container, so OrbStack - which already holds
# local-network permission - makes the hop and vite only ever touches loopback.
# If /healthz starts 500-ing with EHOSTUNREACH, check that relay first.
export BOLTRIG_KERNEL_URL="${BOLTRIG_KERNEL_URL:-http://127.0.0.1:18000}"

# The console pulls @wlilley93/boltrig-web-sdk from GitHub Packages, which needs
# auth even though the package is public.
export NPM_CONFIG_USERCONFIG="$HOME/Projects/boltrig/.secrets/gh_npmrc"

# Vite answers 403 to any Host header it does not recognise, so the tunnel's
# hostname has to be declared or every request through it is refused while the
# vite log still reports a healthy server (see vite.config.ts allowedHosts).
export BOLTRIG_UI_ALLOWED_HOSTS="${BOLTRIG_UI_ALLOWED_HOSTS:-dev.boltrig.io}"

reap_8080() {
  local pids
  pids=$(lsof -nP -tiTCP:8080 -sTCP:LISTEN 2>/dev/null)
  if [ -n "$pids" ]; then
    echo "=== [boltrig-ui] reaping stale listener(s) on 8080: $pids ==="
    kill -9 ${=pids} 2>/dev/null
    sleep 2
  fi
}

trap 'echo "=== [boltrig-ui] shutting down ==="; reap_8080; exit 0' TERM INT

while true; do
  reap_8080
  echo "=== [boltrig-ui] starting vite on 8080 (node $(node --version), kernel ${BOLTRIG_KERNEL_URL}) at $(date) ==="
  # --host 127.0.0.1 is REQUIRED, not cosmetic. Vite's default bind is the
  # "localhost" name, which on this box resolves to ::1 and leaves IPv4
  # 127.0.0.1 refused. cloudflared dials the ingress target over IPv4 (that is
  # how demo.opbox.app reaches its dev server, which binds 0.0.0.0), so an
  # IPv6-only listener here shows up as a 502 on dev.boltrig.io with a vite
  # process that looks perfectly healthy in its own log.
  ./node_modules/.bin/vite --port 8080 --strictPort --host 127.0.0.1
  echo "=== [boltrig-ui] vite exited code=$? at $(date); restarting in 3s ==="
  sleep 3
done
