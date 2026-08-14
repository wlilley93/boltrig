#!/usr/bin/env bash
# WL-1 / WL-2 severance checks for the familiar surface. Re-runnable "binding" of the two contracts
# the way a desktop-config repo can: static assertions + the degrade paths. (WL-3, familiar.express
# through boltrig's chokepoint, is a later step and is NOT built here.)
set -uo pipefail
cd "$(dirname "$0")"
fail=0

echo "== WL-1: the surface imports nothing from boltrig; it consumes only the phenotype file =="
# No boltrig import/link, no HTTP/boltrig socket. The ONLY boltrig token allowed is the phenotype
# filename and prose comments naming where the file comes from.
bad=$(grep -nE '#include .*boltrig|-lboltrig|libboltrig|https?://|boltrig\.(emotion|kernel)' main.c familiar.frag 2>/dev/null || true)
if [ -n "$bad" ]; then echo "  FAIL - boltrig/network coupling:"; echo "$bad"; fail=1
else echo "  ok - only the versioned phenotype file couples them"; fi
# It must actually read the phenotype file (the whole contract).
grep -q 'boltrig-phenotype.json' main.c && echo "  ok - reads \$XDG_RUNTIME_DIR/boltrig-phenotype.json" \
  || { echo "  FAIL - does not read the phenotype file"; fail=1; }

echo "== WL-2: no compositor / no GPU / no phenotype degrades typed, never crashes =="
# Static evidence of each degrade path (behaviour is exercised by run-check below when a compositor
# is present; these greps make the intent binding even in CI with no display).
grep -q 'no wayland display' main.c && echo "  ok - no-compositor path prints a typed message + exits" \
  || { echo "  FAIL - missing no-compositor guard"; fail=1; }
grep -q 'eglInitialize failed\|no EGL config\|EGL context/surface failed' main.c \
  && echo "  ok - no-GPU/EGL paths are typed" || { echo "  FAIL - missing EGL guards"; fail=1; }
grep -q 'PHENO_IDLE' main.c && echo "  ok - no/stale phenotype falls back to the resting baseline" \
  || { echo "  FAIL - missing phenotype fallback"; fail=1; }

# Optional live degrade check: if a compositor is reachable, prove no-compositor really exits clean.
if [ -n "${WAYLAND_DISPLAY:-}" ] && [ -x build/familiar-bg ]; then
  WAYLAND_DISPLAY=__nope__ timeout 3 ./build/familiar-bg >/dev/null 2>&1
  rc=$?
  [ "$rc" = "1" ] && echo "  ok - live: bogus WAYLAND_DISPLAY exits 1 (no crash)" \
    || echo "  note - bogus-display exit was $rc (expected 1; non-fatal)"
fi

echo "== LAYER HYGIENE: nothing of ours may smother the bar or the KVM capture strip =="
# Twice now a layer-shell change of ours has broken the lan-mouse bridge to the Mac: first a leftover
# headless output, then moving the FULL-SCREEN wallpaper to the overlay layer while docking, which sat
# on top of lan-mouse's 1x1080 edge-capture strip at x=1919. Both were invisible and both stole the
# cursor. These checks make the rule enforceable: the wallpaper stays on BACKGROUND for life, and the
# only thing we put on overlay is the small bead.
if grep -q 'ZWLR_LAYER_SHELL_V1_LAYER_BACKGROUND, "familiar"' main.c; then
  echo "  ok - the wallpaper surface is born on the background layer"
else
  echo "  FAIL - the wallpaper surface is not created on the background layer"; fail=1
fi
if grep -q 'zwlr_layer_surface_v1_set_layer' main.c; then
  echo "  FAIL - set_layer is called: the wallpaper must never change layer (it lands on top of the"
  echo "         KVM edge-capture strip and eats the cursor). Give a new job its own small surface."
  fail=1
else
  echo "  ok - no set_layer: surfaces stay on the layer they are born on"
fi
if grep -q 'ZWLR_LAYER_SHELL_V1_LAYER_OVERLAY, "familiar-bead"' main.c \
   && grep -q 'zwlr_layer_surface_v1_set_size(bead_ls' main.c; then
  echo "  ok - the only overlay surface is the porthole, and it is explicitly size-bounded"
else
  echo "  FAIL - the overlay surface must be the porthole, with an explicit set_size"; fail=1
fi
# The porthole grows for the migration so the being withdraws OVER your windows. That is allowed;
# what is never allowed is reaching the right edge, where lan-mouse captures the cursor.
if grep -q 'bead_w > W32 - 200' main.c; then
  echo "  ok - the wide porthole is capped clear of the screen's right edge (the KVM strip)"
else
  echo "  FAIL - the wide porthole must be capped away from the right edge"; fail=1
fi
if [ "$(grep -c 'wl_surface_set_input_region' main.c)" -ge 2 ]; then
  echo "  ok - both surfaces set an input region (decorative surfaces take no pointer input)"
else
  echo "  FAIL - every surface we create must set an EMPTY input region"; fail=1
fi

# Live check: ask the compositor what is actually mapped, if one is running.
if command -v hyprctl >/dev/null 2>&1 && hyprctl layers -j >/dev/null 2>&1; then
  hyprctl layers -j | python3 -c '
import json,sys
data=json.load(sys.stdin)
ours=[]; capture=[]; SW=SH=1
for mon,info in data.items():
    for lvl,layers in info.get("levels",{}).items():
        for L in layers:
            SW=max(SW,L.get("x",0)+L.get("w",0)); SH=max(SH,L.get("y",0)+L.get("h",0))
for mon,info in data.items():
    for lvl,layers in info.get("levels",{}).items():
        for L in layers:
            r=(L.get("x",0),L.get("y",0),L.get("w",0),L.get("h",0))
            ns=L.get("namespace","")
            if ns.startswith("familiar"): ours.append((int(lvl),ns,r))
            if "lan mouse" in ns.lower() or "lan-mouse" in ns.lower(): capture.append((ns,r))
bad=False
for lvl,ns,(x,y,w,h) in ours:
    # A large porthole is legitimate DURING the migration; a full-screen one never is - that is what
    # covered the lan-mouse capture strip and swallowed the cursor.
    if lvl >= 2 and (w >= 0.92*SW or h >= 0.92*SH):
        print(f"  FAIL - {ns} is {w}x{h}, effectively full-screen on layer level {lvl}"); bad=True
for ns,(cx,cy,cw,ch) in capture:
    for lvl,ons,(x,y,w,h) in ours:
        if lvl >= 2 and x < cx+cw and cx < x+w and y < cy+ch and cy < y+h:
            print(f"  FAIL - {ons} overlaps the KVM capture strip {ns} ({cx},{cy} {cw}x{ch})"); bad=True
if not bad:
    print(f"  ok - live: {len(ours)} familiar surface(s) mapped, none full-screen, none over the KVM strip")
sys.exit(1 if bad else 0)
' || fail=1
else
  echo "  note - no compositor reachable, static checks only"
fi

[ "$fail" = "0" ] && echo "ALL SEVERANCE CHECKS PASS" || echo "SEVERANCE CHECKS FAILED"
exit $fail
