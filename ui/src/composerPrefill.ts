// One-shot composer prefill (chat spec 8c, the receiving half of ByChat / P32).
// A module variable in the identity-store idiom - NOT a hash query param,
// because `?run=` owns the query slot (router.ts). The chat slide consumes the
// phrase into the composer on activation: focused, cursor at end, never
// auto-sent (the user owns the send).

let pending: string | null = null;

export function setComposerPrefill(text: string): void {
  pending = text;
}

// Returns the stored phrase once, then null (one-shot).
export function consumeComposerPrefill(): string | null {
  const text = pending;
  pending = null;
  return text;
}
