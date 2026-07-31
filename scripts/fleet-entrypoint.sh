#!/bin/sh
set -eu

root="${BOLTRIG_BROWSER_CLI_HOME:-/var/lib/boltrig/browser-cli}"
export HOME="$root/home"
export XDG_CONFIG_HOME="$root/config"
export XDG_DATA_HOME="$root/data"
export XDG_STATE_HOME="$root/state"
export XDG_CACHE_HOME="$root/cache"
profile="$HOME/.config/chromium"
mkdir -p "$profile" "$XDG_CONFIG_HOME" "$XDG_DATA_HOME" "$XDG_STATE_HOME" "$XDG_CACHE_HOME"
# A container recreate stops the old chromium first, so any Singleton* files
# left behind are stale by construction - an unclean stop (SIGKILL, overlap)
# would otherwise crash-loop every subsequent boot on the profile lock.
rm -f "$profile"/SingletonLock "$profile"/SingletonSocket "$profile"/SingletonCookie

# Chromium runs --no-sandbox for the whole life of this worker, so it starts ONLY
# for a tenant whose manifest actually declares browser automation. Until
# 2026-07-31 it started unconditionally, so a tenant with zero browser
# invocations still ran a permanent unsandboxed browser carrying the image's
# standing HIGH advisories.
#
# The module's exit code IS the answer, and that module is the single definition
# all three consumers share (boltrig/fleet/browser_runtime.py): the gate in
# /readyz reads the same predicate, so skipping the launch here can never leave
# the deployment demanding a tool it no longer runs.
if python -m boltrig.fleet.browser_runtime; then
  ready=0
  attempt=0

  chromium \
    --headless=new \
    --no-sandbox \
    --disable-dev-shm-usage \
    --disable-background-networking \
    --disable-component-update \
    --disable-default-apps \
    --disable-sync \
    --no-first-run \
    --no-default-browser-check \
    --remote-debugging-address=127.0.0.1 \
    --remote-debugging-port=9222 \
    --user-data-dir="$profile" \
    about:blank > /tmp/boltrig-chromium.log 2>&1 &

  while [ "$attempt" -lt 100 ]; do
    if python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9222/json/version', timeout=0.2).close()" 2>/dev/null; then
      ready=1
      break
    fi
    attempt=$((attempt + 1))
    sleep 0.1
  done

  if [ "$ready" -ne 1 ]; then
    echo "fleet-entrypoint: Chromium did not expose its local CDP endpoint" >&2
    sed -n '1,80p' /tmp/boltrig-chromium.log >&2
    exit 1
  fi

  # Start and verify the local Browser Harness daemon before reporting the
  # worker ready. It connects only to the loopback CDP endpoint above.
  printf '%s\n' 'print(page_info())' | browser-use > /tmp/boltrig-browser-prime.log
else
  echo "fleet-entrypoint: browser automation not declared; Chromium not started" >&2
fi

exec "$@"
