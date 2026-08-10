#!/usr/bin/env bash
# Swap the familiar's realm (the background room) LIVE: rewrite FAMILIAR_REALM in the INSTALLED
# shader and SIGUSR1 the running service, which recompiles and keeps the old program if the new
# one fails - a typo or a bad number cannot black the screen.
#
# Realms (see familiar.frag, the #if FAMILIAR_REALM branches in main()):
#   1  transit chamber (default): warp-tunnel spokes + ribs around a distant black hole
#   2  the cylinder: a vast greebled cylinder wall falling off to black, mood-coloured sparks
#   3  emberfield: near-featureless dark, parallax drifting embers and occasional flares
#   4  the abyss: a flooded vertical column, god-ray shafts from below, bioluminescent motes
#
# NOTE: this edits the LIVE shader (~/.config/familiar/familiar.frag). `make install` reseeds
# that file from the repo and puts the repo's default realm back; run use-realm again after an
# install, or change the #define in the repo to make a realm permanent.
set -euo pipefail

n="${1:?usage: use-realm N  (1=chamber, 2=cylinder, 3=emberfield, 4=abyss)}"
shader="$HOME/.config/familiar/familiar.frag"

grep -Eq "^#(if|elif) FAMILIAR_REALM == $n$" "$shader" || {
  echo "use-realm: no realm $n in $shader (install a shader that has it first)" >&2; exit 1; }
sed -i "s/^#define FAMILIAR_REALM .*/#define FAMILIAR_REALM $n/" "$shader"
systemctl --user kill -s USR1 familiar.service
echo "realm $n requested - the service reloads the shader in place (old program kept on compile failure)"
