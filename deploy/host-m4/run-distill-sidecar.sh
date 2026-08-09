#!/bin/sh
# The boltrig distill trainer/scorer sidecar (decision 0023), native for Metal.
# Loopback bind; the boltrig-vm kernel reaches it via host.orb.internal:8930.
#
# NATIVE on purpose: mlx needs Metal, and Metal does not exist inside the
# OrbStack Linux machine that runs the rest of boltrig (the whisper precedent).
#
# This file is the VERSIONED source of truth. It is run by launchd as
# app.boltrig.distill - see app.boltrig.distill.plist.example and the README
# beside it.
#
# The two paths are overridable so this is not M4-only by construction; the
# defaults are what this box uses.
BOLTRIG_REPO="${BOLTRIG_REPO:-$HOME/Projects/boltrig}"
BOLTRIG_MLX_VENV="${BOLTRIG_MLX_VENV:-$HOME/opbox-dev/mlx-venv}"

export BOLTRIG_DISTILL_MLX_PYTHON="${BOLTRIG_DISTILL_MLX_PYTHON:-$BOLTRIG_MLX_VENV/bin/python}"
exec "$BOLTRIG_MLX_VENV/bin/python" \
  "$BOLTRIG_REPO/services/distill_sidecar/app.py"
