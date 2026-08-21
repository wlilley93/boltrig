// The Boltrig API origin this bundle was built for.
//
// The web image leaves VITE_API_BASE empty so every call stays same-origin
// behind nginx, which also proxies /v1 and the /voice gateway. The desktop
// shell has no such origin: it serves this bundle from tauri://localhost, where
// no kernel and no voice gateway are reachable, so the desktop paths resolve
// against this value instead of the document origin. A desktop device session
// is already bound to exactly this origin when the authenticated desktop is
// connected.
//
// SUBPATH MOUNT (GOAL-console-mounts-with-its-stack M2): when the console is
// served under a host path (`<tenant-host>/boltrig/` behind a stripping
// proxy), the mount is DERIVED from the document, never declared. The app is
// a hash router, so a DIRECTORY pathname ("/", "/boltrig/") is the mount
// prefix, and prefixing the empty same-origin base with it routes every /v1
// call back through the same mount.
//
// Only a directory path (or its /index.html) is a mount. Any other document
// path means ROOT: the first derivation prefixed everything, and the visual
// harness - served at /tests/visual/parity.html with root-relative /v1
// fixtures - missed every fixture (the M3 "breaks the standalone" trap,
// caught by the capture run 2026-08-21). A mount deep-link without the
// trailing slash is the stripping proxy's job to normalise.
export function mountPrefix(): string {
  if (typeof window === "undefined") return "";
  try {
    const path = window.location.pathname;
    if (path.endsWith("/")) return path.replace(/\/$/, "");
    if (path.endsWith("/index.html")) return path.slice(0, -"/index.html".length);
    return "";
  } catch {
    return "";
  }
}

export function configuredApiOrigin(): string {
  const built = (import.meta.env.VITE_API_BASE ?? "").replace(/\/$/, "");
  if (built) return built;
  return mountPrefix();
}
