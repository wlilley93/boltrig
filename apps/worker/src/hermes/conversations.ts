import { cellJson, cellPost, cellFetch } from "./http";
import type { 
  ConversationsResponse, 
  ConversationResponse 
} from "@wlilley93/boltrig-web-sdk";

export async function conversations(): Promise<ConversationsResponse> {
  // Hermes uses /api/sessions for this.
  const sessions = await cellJson<any[]>(`/api/sessions`);
  
  return {
    // Map Hermes sessions to v1 conversations.
    // This is a simplified mapping; the real one might need more fields.
    conversations: sessions.map(s => ({
       id: s.id,
       title: s.title || "Untitled Conversation",
       updated_at: s.updated_at,
       status: s.status || "active",
     }))
  };
}

/** The page the SIDEBAR asks for, which is not the list `conversations()`
 *  returns.
 *
 *  THIS IS WHY THE CONVERSATION LIST WAS EMPTY. `useConversationDirectory`
 *  calls `conversationsPage(25, 0)` and nothing else; `conversations()` is used
 *  by ChatView and the archived-settings section. Implementing only the latter
 *  left the sidebar calling a method the adapter did not have, so its promise
 *  rejected, the directory sat at `unavailable`, and not one `.session-row` was
 *  ever rendered - with no error on screen, because the catch sets a status the
 *  empty state renders quietly.
 *
 *  PAGINATED HERE RATHER THAN AT THE CELL. Hermes serves the whole session list
 *  in one response and takes no limit or offset, so slicing client-side is the
 *  honest translation: the caller gets the contract it expects, and
 *  `next_offset` is null at the end rather than an offset that would fetch the
 *  same list again. */
export async function conversationsPage(
  limit: number,
  offset: number,
): Promise<ConversationsResponse & { next_offset: number | null }> {
  const all = (await conversations()).conversations;
  const page = all.slice(offset, offset + limit);
  const next = offset + page.length;
  return { conversations: page, next_offset: next < all.length ? next : null };
}

export async function conversation(id: string): Promise<ConversationResponse> {
  const session = await cellJson<any>(`/api/sessions/${encodeURIComponent(id)}`);
  
  return {
    ...session,
    title: session.title,
    updated_at: session.updated_at,
  } as any;
}

export async function deleteConversation(id: string): Promise<{ status: string; reason?: string }> {
  try {
    await cellFetch(`/api/sessions/${encodeURIComponent(id)}`, { method: "DELETE" });
    return { status: "ok" };
  } catch (e: any) {
    return { status: "error", reason: e.message };
  }
}

export async function renameConversation(id: string, title: string): Promise<{ status: string; reason?: string }> {
  try {
    await cellFetch(`/api/sessions/${encodeURIComponent(id)}`, { 
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    });
    return { status: "ok" };
  } catch (e: any) {
    return { status: "error", reason: e.message };
  }
}

// I'll fix http.ts to allow method overrides.
