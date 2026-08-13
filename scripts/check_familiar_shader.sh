#!/usr/bin/env bash
# Is the vendored Worker familiar.frag the one copied from its source?
#
# apps/worker/src/bundles/familiar/familiar.frag is a COPY. Its source lives in another repo entirely
# (wlilley93/beelink-desktop, familiar/familiar.frag), so no compiler, linter or CI job in this
# repository can tell you when the two have diverged - CI has no checkout of it.
#
# The vitest beside the shader pins the half that IS visible here: that the vendored copy has
# not been edited in place. This answers the other half, on a machine that has both trees.
#
# THE NOT-CHECKED RULE, the same one scripts/check_fleet_drift.py follows: where the upstream
# cannot be found, this says NOT CHECKED and exits non-zero rather than reporting an agreement
# it did not observe. A drift check that goes green when it could not look is worse than no
# check, because it converts "nobody has verified this" into "somebody verified this".

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UPSTREAM_DIR="${FAMILIAR_UPSTREAM_DIR:-$HOME/Projects/beelink-desktop/familiar}"

FILES="familiar.frag"

status=0
for f in $FILES; do
  vendored="$HERE/apps/worker/src/bundles/familiar/$f"
  upstream="$UPSTREAM_DIR/$f"

  if [ ! -f "$vendored" ]; then
    echo "FAIL: no vendored $f at $vendored" >&2
    exit 1
  fi

  vend_sha="$(sha256sum "$vendored" | cut -d' ' -f1)"
  echo "vendored : $vend_sha  $vendored"

  if [ ! -f "$upstream" ]; then
    echo "NOT CHECKED: no upstream $f at $upstream" >&2
    echo "             set FAMILIAR_UPSTREAM_DIR to its directory, or clone wlilley93/beelink-desktop." >&2
    exit 2
  fi

  up_sha="$(sha256sum "$upstream" | cut -d' ' -f1)"
  echo "upstream : $up_sha  $upstream"

  if [ "$vend_sha" != "$up_sha" ]; then
    echo >&2
    echo "DRIFT in $f: the console is rendering a different being from the desktop." >&2
    echo "  The two files differ. Neither is automatically right - check which way the change" >&2
    echo "  went before copying, because a blind re-copy can discard a real upstream fix." >&2
    echo >&2
    diff -u "$upstream" "$vendored" | head -40 >&2 || true
    status=1
  fi
  echo
done

[ "$status" -eq 0 ] || exit 1

frag_sha="$(sha256sum "$HERE/apps/worker/src/bundles/familiar/familiar.frag" | cut -d' ' -f1)"
echo "RESULT: PASS - every vendored file is byte-identical to its upstream."
echo "        Remember the digest in the Worker familiar provenance test"
echo "        must also name this hash: $frag_sha"
