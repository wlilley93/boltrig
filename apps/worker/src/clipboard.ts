/**
 * Copies a one-time value without retaining it or including it in errors.
 *
 * Callers own the visible success/failure message so the clipboard result is
 * explicit without moving the secret into another state or logging surface.
 */
export async function copySensitiveText(value: string): Promise<boolean> {
  if (!value) return false;
  try {
    const clipboard = navigator.clipboard;
    if (!clipboard || typeof clipboard.writeText !== "function") return false;
    await clipboard.writeText(value);
    return true;
  } catch {
    return false;
  }
}
