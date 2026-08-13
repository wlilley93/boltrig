#!/usr/bin/env bash
# Boltrig GENESIS - the one canonical, one-shot founder ceremony: turn a fresh
# `git clone` into a fully usable box in ONE run. Everything that used to be
# hand-done after a deploy (fill secrets, bring the stack up, boot Hatchet, seed
# the founding superadmin, verify a real login) happens here.
#
#   cp .env.example .env         # genesis fills the blank internal secrets for you
#   bash genesis.sh dev          # dev (own Caddy on :8080, loopback) | base | secure
#
# Env-first, then prompt (interactive on a fresh box, non-interactive in CI when
# the vars are set): ORG_NAME, WS_NAME, SUPERADMIN_EMAIL, SUPERADMIN_PASSWORD.
#
# Idempotent + resume-safe: gen_secret fills blanks only; the hatchet db + token
# mint are re-runnable; `boltrig initiate` is one-shot fail-closed (refuses twice);
# a mid-run crash is resumed by re-running (persisted secrets are read back).
set -euo pipefail
cd "$(dirname "$0")"

# ---------------------------------------------------------------- config / inputs
ENVF="${BOLTRIG_ENV_FILE:-.env}"
TARGET="${1:-${BOLTRIG_COMPOSE_TARGET:-dev}}"
case "$TARGET" in
  dev)    COMPOSE_FILES=(-f docker-compose.yml -f deploy/compose.dev.yml) ;;
  secure) COMPOSE_FILES=(-f docker-compose.yml -f deploy/compose.secure.yml) ;;
  base)   COMPOSE_FILES=(-f docker-compose.yml) ;;
  *) echo "unknown target '$TARGET' (dev|secure|base)" >&2; exit 2 ;;
esac
COMPOSE_PROFILES=(--profile gateway)
# The hatchet-lite built-in default tenant id (stable across fresh boots).
HATCHET_TENANT="${HATCHET_TENANT_ID:-707d0855-80ab-4e1f-a156-f1c4546cbf52}"

compose() { docker compose "${COMPOSE_FILES[@]}" "${COMPOSE_PROFILES[@]}" --env-file "$ENVF" "$@"; }

prompt_default() {  # prompt_default VAR "label" "default"  (env wins; then prompt; then default)
  local var="$1" label="$2" def="$3" cur="${!1:-}"
  if [ -n "$cur" ]; then printf '%s' "$cur"; return; fi
  if [ -t 0 ]; then read -r -p "$label [$def]: " v; printf '%s' "${v:-$def}"; else printf '%s' "$def"; fi
}
set_env() {  # upsert KEY=VALUE into $ENVF
  local k="$1" v="$2"
  if grep -qE "^${k}=" "$ENVF" 2>/dev/null; then
    # in-place replace (portable: rewrite the line)
    python3 - "$ENVF" "$k" "$v" <<'PY'
import sys
p,k,v=sys.argv[1:4]
lines=open(p).read().splitlines()
out=[(f"{k}={v}" if l.split("=",1)[0]==k else l) for l in lines]
open(p,"w").write("\n".join(out)+"\n")
PY
  else
    printf '%s=%s\n' "$k" "$v" >> "$ENVF"
  fi
}
secret_of() { grep -E "^$1=" "$ENVF" 2>/dev/null | head -1 | cut -d= -f2- || true; }
ensure_csv_env() {  # ensure_csv_env KEY item [item...]
  local k="$1" cur item
  shift
  cur="$(secret_of "$k")"
  for item in "$@"; do
    if [ -z "$cur" ]; then
      cur="$item"
    elif ! printf ',%s,' "$cur" | grep -q ",${item},"; then
      cur="${cur},${item}"
    fi
  done
  set_env "$k" "$cur"
}
gen_secret() {  # fill a blank/absent secret only (idempotent)
  local k="$1"
  [ -n "$(secret_of "$k")" ] && return 0
  set_env "$k" "$(head -c 32 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 48)"
  echo "  generated $k"
}
gen_ed25519_seed() {  # one unpadded base64url-encoded 32-byte seed
  local k="$1"
  [ -n "$(secret_of "$k")" ] && return 0
  set_env "$k" "$(head -c 32 /dev/urandom | base64 | tr '+/' '-_' | tr -d '=\\n')"
  echo "  generated $k"
}
wait_healthy() {  # wait_healthy SERVICE SECONDS
  local svc="$1" max="${2:-90}" i=0
  until [ "$(compose ps --format '{{.Health}}' "$svc" 2>/dev/null)" = "healthy" ]; do
    i=$((i+1)); [ "$i" -ge "$max" ] && { echo "  $svc did not become healthy in ${max}s" >&2; return 1; }
    sleep 1
  done
}

ORG_NAME="$(prompt_default ORG_NAME 'First organisation name' 'Your organisation')"
WS_NAME="$(prompt_default WS_NAME 'First workspace name' "$ORG_NAME")"
# A public checkout must never guess an owner identity or password. Interactive
# genesis prompts for them; non-interactive runs must provide both explicitly.
SUPERADMIN_EMAIL="$(prompt_default SUPERADMIN_EMAIL 'Superadmin email' '')"
SUPERADMIN_PASSWORD="$(prompt_default SUPERADMIN_PASSWORD 'Superadmin password' '')"
[ -n "$SUPERADMIN_EMAIL" ] || { echo "SUPERADMIN_EMAIL is required; no personal default is bundled" >&2; exit 2; }
[ -n "$SUPERADMIN_PASSWORD" ] || { echo "SUPERADMIN_PASSWORD is required; no default password is bundled" >&2; exit 2; }

echo "== BOLTRIG GENESIS  target=$TARGET  org='$ORG_NAME'  ws='$WS_NAME'  super=$SUPERADMIN_EMAIL =="

# ---------------------------------------------------------------- Phase 0: secrets + config
echo "==> Phase 0: .env + blank internal secrets + config"
[ -f "$ENVF" ] || cp .env.example "$ENVF"
[ -f manifest.yaml ] || cp manifest.example.yaml manifest.yaml
gen_secret POSTGRES_PASSWORD
gen_secret BOLTRIG_AUDIT_HMAC_KEY
gen_ed25519_seed BOLTRIG_DEVICE_LEASE_SIGNING_KEY
# Keep DATABASE_URL's credential segment consistent with the POSTGRES_* vars
# (M9/SEC-69: they MUST match) and default the db/user to 'boltrig'.
PGUSER="$(secret_of POSTGRES_USER)"; PGUSER="${PGUSER:-boltrig}"; set_env POSTGRES_USER "$PGUSER"
PGDB="$(secret_of POSTGRES_DB)"; PGDB="${PGDB:-boltrig}"; set_env POSTGRES_DB "$PGDB"
PGPW="$(secret_of POSTGRES_PASSWORD)"
set_env DATABASE_URL "postgresql+asyncpg://${PGUSER}:${PGPW}@postgres:5432/${PGDB}"
# First-party invite-only login is the gate (VJS-COUNTY 7); dev-auth off.
set_env BOLTRIG_AUTH_MODE session
set_env BOLTRIG_DEV_AUTH 0
set_env HATCHET_CLIENT_TLS_STRATEGY none
# Bifrost is the standard-data model gateway in the genesis stack. It is
# profile-gated in raw compose, but genesis starts the gateway profile and wires
# Pi to the internal /v1 route Bifrost exposes.
[ -n "$(secret_of BIFROST_PORT)" ] || set_env BIFROST_PORT 8081
[ -n "$(secret_of BOLTRIG_MODEL_GATEWAY_URL)" ] || set_env BOLTRIG_MODEL_GATEWAY_URL http://bifrost:8080/v1
[ -n "$(secret_of BOLTRIG_MODEL_GATEWAY_TTL)" ] || set_env BOLTRIG_MODEL_GATEWAY_TTL 900
ensure_csv_env NO_PROXY bifrost local-model

# ---------------------------------------------------------------- Phase 1: datastores + Hatchet db
echo "==> Phase 1: datastores up + Hatchet database"
compose up -d postgres redis
wait_healthy postgres 90
# Hatchet-lite needs its OWN 'hatchet' db owned by the boltrig role, or the engine
# never boots (the standing gotcha). Create it idempotently, out-of-band.
if ! compose exec -T postgres psql -U "$PGUSER" -d postgres -tAc \
      "SELECT 1 FROM pg_database WHERE datname='hatchet'" | grep -q 1; then
  compose exec -T postgres createdb -U "$PGUSER" hatchet && echo "  created hatchet db"
fi

# ---------------------------------------------------------------- Phase 2: build + bring the stack up
echo "==> Phase 2: build + bring the full stack up"
# A fresh volume loads boltrig/store/schema.sql on first boot (all tables), so no
# migration is needed on a clean box; an UPGRADE of an existing box runs
# `make migrate` (alembic) separately.
compose up -d --build
wait_healthy kernel 120

# ---------------------------------------------------------------- Phase 3: Hatchet client token
echo "==> Phase 3: mint + wire the Hatchet client token"
if [ -z "$(secret_of HATCHET_CLIENT_TOKEN)" ]; then
  TOKEN="$(compose exec -T hatchet-engine /hatchet-admin token create \
             --config /config --tenant-id "$HATCHET_TENANT" 2>/dev/null | tr -d '\r' | tail -1)"
  if [ -n "${TOKEN:-}" ]; then
    set_env HATCHET_CLIENT_TOKEN "$TOKEN"
    compose up -d fleet-worker   # restart the worker with the token so it selects the durable executor
    echo "  hatchet token minted + fleet-worker restarted"
  else
    echo "  WARNING: could not mint a hatchet token; the fleet falls back to the local executor (P9)"
  fi
fi

# ---------------------------------------------------------------- Phase 4: found the superadmin
echo "==> Phase 4: found the superadmin (VJS-COUNTY 7 invite-only seed)"
# Idempotent: `boltrig initiate` refuses to run twice (one owner per tenant).
if compose exec -T kernel boltrig initiate \
      --email "$SUPERADMIN_EMAIL" --password "$SUPERADMIN_PASSWORD" \
      --org-name "$ORG_NAME" --workspace-name "$WS_NAME" 2>&1 | tee /dev/stderr | grep -qiE 'seated|already'; then
  echo "  superadmin seated: $SUPERADMIN_EMAIL  (org '$ORG_NAME' / workspace '$WS_NAME')"
fi
# `boltrig initiate` now also seeds the default org (renamed to '$ORG_NAME'), the
# default workspace '$WS_NAME', and the OWNER's org + workspace memberships
# (VJS-COUNTY 8, D7). Idempotent: a re-run refuses once an owner exists.

# ---------------------------------------------------------------- Phase 5: verify
echo "==> Phase 5: verify (kernel health + a real login round-trip)"
BASE="http://localhost:${WORKER_PORT:-8082}"
HZ="$(curl -s -o /dev/null -w '%{http_code}' "$BASE/healthz" || true)"
echo "  GET /healthz -> $HZ"
LOGIN="$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE/v1/auth/login" \
          -H 'content-type: application/json' \
          -d "{\"email\":\"$SUPERADMIN_EMAIL\",\"password\":\"$SUPERADMIN_PASSWORD\"}" || true)"
echo "  POST /v1/auth/login -> $LOGIN  (200 = the custom login works)"

echo
if [ "$HZ" = "200" ] && [ "$LOGIN" = "200" ]; then
  echo "== GENESIS COMPLETE =="
  echo "   console:  $BASE    login: $SUPERADMIN_EMAIL"
  echo "   change the seed password before exposing this box to the internet."
else
  echo "== GENESIS finished with warnings (health=$HZ login=$LOGIN) - check 'compose logs' =="
fi
