#!/usr/bin/env bash
# The gate the pre-push hook runs. On Linux it IS `make python-quality`. On macOS
# it runs that same target inside a Linux VM, because on the host it cannot pass.
#
# WHY. Measured 2026-08-06 on the M4, the first machine to hold the pen that is not
# the beelink:
#
#   macOS host   3567 passed, 34 failed
#   Linux VM     3616 passed,  1 failed   (and that one was uncommitted tree state)
#
# Seventeen of those 34 are not portability defects and never will be. They assert
# Linux kernel security controls that macOS does not implement:
#
#   15  /proc/sys/kernel/yama/ptrace_scope   "ptrace is unproved"
#    1  SO_PEERCRED peer identity            "Unix listener is unavailable"
#    1  landlock + seccomp sandbox probe     codex-linux-sandbox-landlock-seccomp
#
# Five more WERE portability defects and were fixed (#239): grep -oP in the ruff pin
# read, a fixture seeding /etc/hostname, mapfile under bash 3.2, and two test stubs
# that stopped injecting failures because a bare `[[ ]]` under `set -e` exits 1 on
# bash 5 and 0 on bash 3.2. What is left is the genuine platform floor.
#
# So the hook on a Mac had become a check that CANNOT PASS, and a hook that cannot
# pass teaches `--no-verify` - which then survives every later day when it would
# have caught something real. The two bad answers were to weaken the suite on the
# host, or to leave the hook failing. This is the third: run it where the
# assertions are true. The VM is already there and already runs the stack.
#
# It is deliberately NOT a second list of gates. It invokes `make python-quality`,
# the same target CI runs, so it cannot drift from CI by someone editing a copy.
set -euo pipefail
cd "$(dirname "$0")/.."

VM="${BOLTRIG_QUALITY_VM:-boltrig-vm}"
VM_PY="${BOLTRIG_QUALITY_VM_PY:-\$HOME/boltrig-venv/bin/python}"

if [ "$(uname -s)" != "Darwin" ]; then
  exec make python-quality
fi

# --- macOS from here ---------------------------------------------------------
if ! command -v orb >/dev/null 2>&1; then
  echo "quality-gate: this is macOS, where 17 of these tests cannot pass on the host." >&2
  echo "  They assert Linux kernel controls (yama ptrace_scope, SO_PEERCRED, landlock)." >&2
  echo "  The gate runs inside an OrbStack Linux machine and \`orb\` is not on PATH." >&2
  echo "  A non-interactive shell does not source ~/.zprofile, which is where OrbStack" >&2
  echo "  puts it - so if this fires from a hook, that is the likely cause." >&2
  exit 1
fi

if ! orb list 2>/dev/null | awk '{print $1}' | grep -qx "$VM"; then
  echo "quality-gate: no OrbStack machine named '$VM'." >&2
  echo "  Set BOLTRIG_QUALITY_VM to the right name, or create it. See" >&2
  echo "  docs/HANDOVER-2026-08-06-beelink-stack-retired.md for what that VM is for." >&2
  exit 1
fi

# The repo path is identical inside the machine: OrbStack mounts /Users through.
# Checked rather than assumed, because a wrong path here would run the gate over
# whatever happened to be at that location and report a pass for the wrong tree.
REPO_IN_VM="$(pwd)"
if ! orb -m "$VM" bash -lc "test -f '$REPO_IN_VM/Makefile'" 2>/dev/null; then
  echo "quality-gate: '$REPO_IN_VM' is not visible inside '$VM'." >&2
  echo "  OrbStack normally mounts /Users at the same path. Without that the gate" >&2
  echo "  would be reading a different tree than the one you are pushing." >&2
  exit 1
fi

# Resolved to an ABSOLUTE path inside the VM before it is handed to make. A literal
# `$HOME` survives this far because the default is written unexpanded (the host's
# $HOME is the wrong one), and passing it through produced a genuinely confusing
# failure: make expands `$H` as an empty variable of its own, so
# `$HOME/boltrig-venv/bin/python` arrived as `OME/boltrig-venv/bin/python` and the
# error blamed a path nobody had typed. Found by running this, not by reading it.
VM_PY="$(orb -m "$VM" bash -lc "eval echo \"$VM_PY\"" 2>/dev/null || true)"
if [ -z "$VM_PY" ]; then
  echo "quality-gate: could not resolve the interpreter path inside '$VM'." >&2
  exit 1
fi

if ! orb -m "$VM" bash -lc "test -x \"$VM_PY\"" 2>/dev/null; then
  echo "quality-gate: no interpreter at $VM_PY inside '$VM'." >&2
  echo "  The host .venv is macOS binaries and cannot be used there. Build one:" >&2
  echo "    orb -m $VM bash -lc '" >&2
  echo "      sudo apt-get install -y make build-essential" >&2
  echo "      curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
  echo "      export PATH=\$HOME/.local/bin:\$PATH" >&2
  echo "      uv venv --python 3.12 \$HOME/boltrig-venv" >&2
  echo "      cd $REPO_IN_VM && uv pip sync --python \$HOME/boltrig-venv/bin/python \\" >&2
  echo "        requirements-dev-lock.txt'" >&2
  echo "  3.12 matters: it is what CI runs at all three job sites." >&2
  exit 1
fi

# `with_test_postgres.sh` needs the docker socket, and a fresh VM user is not in the
# docker group. Named explicitly because the failure is a bare
# "permission denied while trying to connect to the docker API", which reads as a
# broken daemon rather than a missing group.
if ! orb -m "$VM" bash -lc "docker info >/dev/null 2>&1"; then
  echo "quality-gate: docker is not usable by your user inside '$VM'." >&2
  echo "  The test Postgres cannot start, so the Postgres leg would not run at all." >&2
  echo "  Fix:  orb -m $VM bash -lc 'sudo usermod -aG docker \$USER'" >&2
  exit 1
fi

echo "[quality-gate] macOS host: running \`make python-quality\` inside '$VM'."
exec orb -m "$VM" bash -lc \
  "cd '$REPO_IN_VM' && export PATH=\$HOME/.local/bin:\$PATH && make python-quality PY='$VM_PY'"
