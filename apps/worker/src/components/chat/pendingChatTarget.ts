const PENDING_AGENT_KEY = "boltrig.pending-chat-agent.v1";
export const PENDING_CHAT_AGENT_EVENT = "boltrig:pending-chat-agent";
const SAFE_AGENT = /^[a-z0-9][a-z0-9_-]{0,62}$/;

/** Carry a deliberate agent-pile `+` selection across the route transition. */
export function setPendingChatAgent(address: string): void {
  if (!SAFE_AGENT.test(address)) return;
  try {
    sessionStorage.setItem(PENDING_AGENT_KEY, address);
    window.dispatchEvent(new CustomEvent(PENDING_CHAT_AGENT_EVENT, { detail: address }));
  } catch {
    // The composer remains usable with the tenant-authored intake default.
  }
}

export function consumePendingChatAgent(): string {
  try {
    const address = sessionStorage.getItem(PENDING_AGENT_KEY) ?? "";
    sessionStorage.removeItem(PENDING_AGENT_KEY);
    return SAFE_AGENT.test(address) ? address : "";
  } catch {
    return "";
  }
}
