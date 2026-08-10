#!/usr/bin/env bash
# familiar-drawer: app launcher summoned from the clockbar or SUPER+Space.
# Wraps nwg-drawer so both the waybar module and the keybind share the same
# layout, theme and behaviour. Each invocation toggles the drawer.
set -uo pipefail

exec nwg-drawer -ovl -k -c 6 -is 48 "$@"
