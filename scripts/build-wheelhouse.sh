#!/usr/bin/env bash
# (scripts/build-wheelhouse.sh - populate deploy/wheelhouse so the image build never touches the link)
# Populate a wheelhouse ONE REQUIREMENT AT A TIME so a truncated wheel costs one package, not the
# whole download.
#
# WHY CHUNKING IS THE FIX, not more --retries. `pip download --require-hashes` stages EVERY wheel in
# a temp dir, verifies the lot, and only then copies to -d. So a single truncated wheel - which pip
# considers a COMPLETE download, which is why it never retries it - discards ~2GB of good wheels and
# the next attempt starts from nothing. Six builds died that way. Per-requirement, a failure costs
# that one wheel and everything already in /wheelhouse survives.
#
# THE HASH CONTRACT IS UNCHANGED. Each wheel is verified against requirements-lock.txt here, and the
# whole set is verified again inside the image build. --no-deps is correct and not a loosening: the
# lock is fully pinned by uv, so there is nothing for a resolver to decide.
set -u
B=$(cd "$(dirname "$0")/.." && pwd)
WH="$B/deploy/wheelhouse"
SPLIT="${TMPDIR:-/tmp}/boltrig-reqsplit"
BASE=python:3.12.13-slim-bookworm@sha256:8a7e7cc04fd3e2bd787f7f24e22d5d119aa590d429b50c95dfe12b3abe52f48b
mkdir -p "$WH"; rm -rf "$SPLIT"; mkdir -p "$SPLIT"

# Split the lock on requirement boundaries (a `name==ver \` line starts one; --hash/comment lines
# continue it). Comments are dropped so a trailing "# via x" cannot end up in the wrong chunk.
python3 - "$B/requirements-lock.txt" "$SPLIT" <<'PY'
import sys, os, re
src, out = sys.argv[1], sys.argv[2]
cur, n = [], 0
def flush():
    global cur, n
    if cur:
        n += 1
        open(os.path.join(out, f"{n:04d}.txt"), "w").write("".join(cur))
        cur = []
for line in open(src):
    if re.match(r'^[A-Za-z0-9]', line):
        flush()
    if line.lstrip().startswith('#'):
        continue
    cur.append(line)
flush()
print(f"{n} requirements")
PY

fail=0
for pass_no in 1 2 3 4 5; do
  remaining=0
  for f in "$SPLIT"/*.txt; do
    [ -f "$f.done" ] && continue
    name=$(head -1 "$f" | cut -d= -f1)
    if docker run --rm --network=host -v "$WH":/wheelhouse -v "$f":/r.txt:ro "$BASE" \
         pip download --require-hashes --no-deps --retries 5 --timeout 60 \
         -d /wheelhouse -r /r.txt >/dev/null 2>&1; then
      touch "$f.done"
    else
      remaining=$((remaining+1))
      echo "pass $pass_no: $name still failing"
    fi
  done
  echo "=== pass $pass_no done: $remaining outstanding, $(ls "$WH" | wc -l) wheels, $(du -sh "$WH" | cut -f1) ==="
  [ "$remaining" -eq 0 ] && { echo "WHEELHOUSE OK"; exit 0; }
done
echo "WHEELHOUSE INCOMPLETE: $(ls "$SPLIT"/*.txt | wc -l) reqs, $(ls "$SPLIT"/*.done 2>/dev/null | wc -l) done"
exit 1
