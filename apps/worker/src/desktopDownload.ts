const HTTPS = "https:";

/**
 * Return the reviewed desktop distribution page baked into the hosted Worker.
 *
 * An absent or unsafe value is intentionally represented as unavailable. The
 * browser must never invent a release URL, downgrade to HTTP, or embed
 * credentials in a download link.
 */
export function configuredDesktopDownloadUrl(): string | null {
  const raw = (import.meta.env.VITE_DESKTOP_DOWNLOAD_URL ?? "").trim();
  if (!raw) return null;
  try {
    const parsed = new URL(raw);
    if (parsed.protocol !== HTTPS || parsed.username || parsed.password) return null;
    return parsed.href;
  } catch {
    return null;
  }
}
