// The Boltrig API origin this bundle was built for.
//
// The web image leaves VITE_API_BASE empty so every call stays same-origin
// behind nginx, which also proxies /v1 and the /voice gateway. The desktop
// shell has no such origin: it serves this bundle from tauri://localhost, where
// no kernel and no voice gateway are reachable, so the desktop paths resolve
// against this value instead of the document origin. A desktop device session
// is already bound to exactly this origin at enrollment.
export function configuredApiOrigin(): string {
  return (import.meta.env.VITE_API_BASE ?? "").replace(/\/$/, "");
}
