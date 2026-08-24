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
