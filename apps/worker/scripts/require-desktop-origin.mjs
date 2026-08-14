const viteOrigin = process.env.VITE_API_BASE ?? "";
const nativeOrigin = process.env.BOLTRIG_DESKTOP_API_ORIGIN ?? "";

function canonicalOrigin(value, name) {
  let parsed;
  try {
    parsed = new URL(value);
  } catch {
    throw new Error(`${name} must be an absolute API origin`);
  }
  const loopback = parsed.hostname === "localhost"
    || parsed.hostname === "127.0.0.1"
    || parsed.hostname === "[::1]";
  if (parsed.protocol !== "https:" && !(parsed.protocol === "http:" && loopback)) {
    throw new Error(`${name} must use HTTPS (or HTTP on loopback)`);
  }
  if (
    parsed.username
    || parsed.password
    || parsed.search
    || parsed.hash
    || (parsed.pathname !== "/" && parsed.pathname !== "")
  ) {
    throw new Error(`${name} must contain only an origin`);
  }
  return parsed.origin;
}

try {
  if (!viteOrigin || !nativeOrigin) {
    throw new Error(
      "desktop builds require both VITE_API_BASE and BOLTRIG_DESKTOP_API_ORIGIN",
    );
  }
  const viteCanonical = canonicalOrigin(viteOrigin, "VITE_API_BASE");
  const nativeCanonical = canonicalOrigin(
    nativeOrigin,
    "BOLTRIG_DESKTOP_API_ORIGIN",
  );
  if (viteOrigin !== viteCanonical || nativeOrigin !== nativeCanonical) {
    throw new Error("desktop API origins must be canonical (no trailing slash)");
  }
  if (viteCanonical !== nativeCanonical) {
    throw new Error("desktop frontend and native API origins must match exactly");
  }
} catch (error) {
  console.error(error instanceof Error ? error.message : String(error));
  process.exit(1);
}
