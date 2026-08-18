#!/usr/bin/env bash
# Is the Boltrig mark's core still the colour it was copied from?
#
# BrandMark.tsx's CORE is Opbox blue, taken from that product's logo asset so the two
# marks read as one house. Its source lives in another repo entirely (the Opbox frontend,
# public/opbox-mark.svg), so no compiler, linter or CI job in this repository can tell you
# when the two have diverged - CI has no checkout of it. If Opbox rebrands, Boltrig follows
# it nowhere and the first person to notice is looking at two screenshots side by side.
#
# The vitest beside the mark pins the half that IS visible here: that BrandMark.tsx and
# public/favicon.svg carry the SAME core, which matters because the desktop icons are
# rasterised from the favicon. This answers the other half, on a machine that has both trees.
# It deliberately does NOT re-assert the in-repo pairing - a second, weaker copy of a check
# that already exists is how two gates come to disagree about one artefact.
#
# THE NOT-CHECKED RULE, the same one scripts/check_familiar_shader.sh follows: where the
# upstream cannot be found, this says NOT CHECKED and exits non-zero rather than reporting
# an agreement it did not observe. A drift check that goes green when it could not look is
# worse than no check, because it converts "nobody has verified this" into "somebody did".
#
# WIRED TO NOTHING, ON PURPOSE. There is no make target and no hook, for the same reason its
# sibling has none: it cannot pass in an environment that has only this repo, so wiring it
# into a gate would make that gate fail for everyone who is not on the machine holding both
# trees. Run it by hand when the mark changes on either side.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Defaults to the checkout that is on `main`. There are nine trees on this box carrying an
# opbox-mark.svg - build dirs, demo dirs, scan copies - and picking whichever one is nearest
# is how a check comes to compare against a branch nobody ships. Override deliberately.
UPSTREAM_DIR="${OPBOX_UPSTREAM_DIR:-$HOME/Projects/opbox-build-main}"

VENDORED="$HERE/apps/worker/src/components/BrandMark.tsx"
UPSTREAM_MARK="$UPSTREAM_DIR/public/opbox-mark.svg"
UPSTREAM_CSS="$UPSTREAM_DIR/app/globals.css"

if [ ! -f "$VENDORED" ]; then
  echo "FAIL: no BrandMark at $VENDORED" >&2
  exit 1
fi

# `const CORE = "#RRGGBB"` is the single declaration of the colour in this repo. If that
# constant is ever renamed or inlined, this must fail loudly rather than quietly find nothing.
ours="$(sed -n 's/.*const CORE = "\(#[0-9A-Fa-f]\{6\}\)".*/\1/p' "$VENDORED" | head -1)"
if [ -z "$ours" ]; then
  echo "FAIL: no 'const CORE = \"#RRGGBB\"' in $VENDORED" >&2
  echo "      the colour moved or was inlined; this check can no longer find it." >&2
  exit 1
fi
echo "boltrig  : $ours  $VENDORED"

if [ ! -f "$UPSTREAM_MARK" ]; then
  echo "NOT CHECKED: no opbox-mark.svg at $UPSTREAM_MARK" >&2
  echo "             set OPBOX_UPSTREAM_DIR to an Opbox frontend checkout." >&2
  exit 2
fi

# The core is the ONE circle in that file; the rect and the text carry the card and the
# letters. Matching on <circle> rather than on "the last fill" survives a reordered file.
# `|| true` is load-bearing under `set -euo pipefail`: grep exits 1 when it matches
# nothing, and head can SIGPIPE it, either of which would kill the script HERE - one line
# above the branch that exists to report exactly this. The negative control caught it
# reporting a bare exit 1 instead of NOT CHECKED, which is the failure this rule forbids.
theirs="$(grep -o '<circle[^>]*fill="#[0-9A-Fa-f]\{6\}"' "$UPSTREAM_MARK" \
          | sed -n 's/.*fill="\(#[0-9A-Fa-f]\{6\}\)".*/\1/p' | head -1 || true)"
if [ -z "$theirs" ]; then
  echo "NOT CHECKED: no <circle ... fill=\"#RRGGBB\"> in $UPSTREAM_MARK" >&2
  echo "             the upstream mark changed shape; compare it by eye before trusting this." >&2
  exit 2
fi
echo "opbox    : $theirs  $UPSTREAM_MARK"

# Reported, NEVER asserted. Opbox's in-app dot renders var(--accent), and its default theme
# value is five units of green from the logo asset - the two have disagreed since before
# Boltrig copied either. Failing on that difference would have made this check red on the day
# it was written, which is a check that cannot pass rather than a check that found something.
# Note the themes redefine --accent, so only the first (default) value is meaningful here.
if [ -f "$UPSTREAM_CSS" ]; then
  accent="$(grep -o -- '--accent: *#[0-9A-Fa-f]\{6\}' "$UPSTREAM_CSS" \
            | sed -n 's/.*\(#[0-9A-Fa-f]\{6\}\)/\1/p' | head -1 || true)"
  [ -n "$accent" ] && echo "note     : opbox --accent (default theme) is $accent, a known second value; not asserted"
fi

# Case-insensitive: this repo writes #0066FF and Opbox writes #0066ff. They are one colour,
# and a comparison that called them different would be reporting its own formatting.
if [ "$(printf '%s' "$ours" | tr 'a-f' 'A-F')" != "$(printf '%s' "$theirs" | tr 'a-f' 'A-F')" ]; then
  echo >&2
  echo "DRIFT: the Boltrig mark's core is no longer the Opbox blue it was copied from." >&2
  echo "  boltrig $ours   opbox $theirs" >&2
  echo "  Neither is automatically right - check which way the change went before copying," >&2
  echo "  because a blind re-copy can discard a deliberate Boltrig decision. If Boltrig is" >&2
  echo "  meant to diverge, delete this check rather than leaving it red." >&2
  exit 1
fi

echo
echo "RESULT: PASS - the Boltrig core is the Opbox logo's blue."
echo "        The in-repo half (BrandMark.tsx vs public/favicon.svg, which the desktop"
echo "        icons are rasterised from) is pinned by apps/worker/tests/brandWordmark.test.tsx."
