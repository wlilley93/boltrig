#!/usr/bin/env bash
# Is the vendored familiar.frag the one it was copied from?
#
# ui/src/familiar/familiar.frag is a COPY. Its source lives in another repo entirely
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
VENDORED="$HERE/ui/src/familiar/familiar.frag"
UPSTREAM="${FAMILIAR_UPSTREAM:-$HOME/Projects/beelink-desktop/familiar/familiar.frag}"

if [ ! -f "$VENDORED" ]; then
  echo "FAIL: no vendored shader at $VENDORED" >&2
  exit 1
fi

vend_sha="$(sha256sum "$VENDORED" | cut -d' ' -f1)"
echo "vendored : $vend_sha  $VENDORED"

if [ ! -f "$UPSTREAM" ]; then
  echo "NOT CHECKED: no upstream shader at $UPSTREAM" >&2
  echo "             set FAMILIAR_UPSTREAM to its path, or clone wlilley93/beelink-desktop." >&2
  exit 2
fi

up_sha="$(sha256sum "$UPSTREAM" | cut -d' ' -f1)"
echo "upstream : $up_sha  $UPSTREAM"

if [ "$vend_sha" != "$up_sha" ]; then
  echo >&2
  echo "DRIFT: the console is rendering a different being from the desktop." >&2
  echo "  The two files differ. Neither is automatically right - check which way the change" >&2
  echo "  went before copying, because a blind re-copy can discard a real upstream fix." >&2
  echo >&2
  diff -u "$UPSTREAM" "$VENDORED" | head -40 >&2 || true
  exit 1
fi

echo
echo "RESULT: PASS - the vendored shader is byte-identical to its upstream."
echo "        Remember the digest in ui/tests/__characterization__/familiar/shader-provenance.test.ts"
echo "        must also name this hash: $vend_sha"
