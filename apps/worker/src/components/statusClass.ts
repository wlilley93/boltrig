/**
 * Map a row status onto its activity-dot class.
 *
 * Its own module for the same reason as contentText: ParityViews renders the
 * memory surface, so importing the helper back out of ParityViews would make
 * the pair circular.
 */
export function statusClass(status: string) {
  if (["done", "ok", "completed", "active"].includes(status)) return "ok";
  if (["failed", "error", "cancelled"].includes(status)) return "error";
  if (["blocked", "awaiting_human", "paused", "pending_human"].includes(status)) return "paused";
  return status;
}
