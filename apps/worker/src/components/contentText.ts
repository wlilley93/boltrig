/**
 * Render arbitrary stored content as a string for display.
 *
 * Its own module because two components need it and neither should import the
 * other: ParityViews renders MemoryReview, so pulling the helper back out of
 * ParityViews would make the pair circular for the sake of six lines.
 */
export function contentText(content: unknown) {
  if (typeof content === "string") return content;
  try {
    return JSON.stringify(content);
  } catch {
    return String(content);
  }
}
