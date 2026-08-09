#!/bin/zsh
# Local speech-to-text for boltrig, as a NATIVE macOS process.
#
# It is not in the container stack on purpose: whisper.cpp is fast here because
# of Metal, and Metal is not available inside the OrbStack Linux VM that runs
# the rest of boltrig. Measured on this M4 Pro with ggml-small.en, 2026-08-05:
# ~0.13s per short utterance, repeatably.
#
# The kernel (in the VM) reaches this at http://host.orb.internal:8910. That
# hostname is the ONLY route that works - the VM's default gateway, the docker
# bridge gateway and the VM's own address were all refused. See
# boltrig/adapters/builtin/local_whisper.py.
#
# --host 0.0.0.0 is required for the VM to reach it at all; on a shared network
# that also exposes it to the LAN, which is acceptable here because the box is
# a personal dev machine and the endpoint holds no secrets. Narrow it if that
# ever stops being true.
#
# This file is the VERSIONED source of truth. It is run by launchd as
# app.boltrig.whisper - see app.boltrig.whisper.plist.example and the README
# beside it.

MODEL="${BOLTRIG_WHISPER_MODEL:-$HOME/opbox-dev/whisper-models/ggml-small.en.bin}"
WHISPER_SERVER="${BOLTRIG_WHISPER_SERVER:-/opt/homebrew/bin/whisper-server}"
PORT="${BOLTRIG_WHISPER_PORT:-8910}"

[ -r "$MODEL" ] || { echo "missing model $MODEL"; exit 1; }

while true; do
  echo "=== [whisper] starting on ${PORT} with $(basename "$MODEL") at $(date) ==="
  "$WHISPER_SERVER" \
    -m "$MODEL" \
    --host 0.0.0.0 \
    --port "$PORT" \
    -nt
  echo "=== [whisper] exited code=$? at $(date); restarting in 3s ==="
  sleep 3
done
