import { BoltrigClient } from "@wlilley93/boltrig-web-sdk";

import { configuredApiOrigin } from "./apiOrigin";

// Empty on the web image, where nginx serves the SPA and proxies /v1 on the
// same origin. On the desktop shell an empty origin would point every call at
// the tauri://localhost webview, which AuthGate refuses to open on.
export const client = new BoltrigClient({
  baseUrl: configuredApiOrigin(),
});
