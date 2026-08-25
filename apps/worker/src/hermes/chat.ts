import { BoltrigApiError } from "@wlilley93/boltrig-web-sdk";
import type {
  ChatEvent,
  ChatFollowFrame,
  ChatFollowResult,
  ChatRequest,
  HITLListResponse,
} from "@wlilley93/boltrig-web-sdk";
import {
  CursorClock,
  frameFromRunEvent,
  frameFromSessionEvent,
  toChatEvents,
  translateRunStream,
} from "@wlilley93/boltrig-web-sdk/hermes/shim";

import { cellFetch, cellPost, jsonBody } from "./http";
import { pumpSse } from "./sse";

export async function streamChat(
  body: ChatRequest,
  onEvent: (event: ChatEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  // THE SDK'S SIGNATURE, not a convenient one. 518 call sites pass a
  // ChatRequest; taking (sessionId, content) instead breaks every one of them
  // and puts the adapter's convenience ahead of the contract it is adapting.
  const sessionId = body.conversation_id ?? await createSession();
  const response = await cellFetch(
    `/api/sessions/${encodeURIComponent(sessionId)}/chat/stream`,
    { ...jsonBody({ content: body.message }), signal },
  );
  if (!response.body) throw new BoltrigApiError(502, null, "the cell sent no stream");

  await pumpSse<Record<string, unknown>>(response.body, (frame) => {
    const hermesFrame = frameFromSessionEvent(frame.name, frame.data);
    const runId = hermesFrame.payload?.run_id;

    // The run id arrives only on the stream - no session response carries it,
    // and there is no run index - so it is captured here or it is lost, and
    // with it cancel, approvals and reattach after a reload.
    if (typeof runId === "string" && runId) rememberRun(sessionId, runId);
    if (TERMINAL.has(hermesFrame.name)) forgetRun(sessionId);

    for (const event of toChatEvents(hermesFrame, sessionId)) onEvent(event);
  }, signal);
}

/** Hermes needs a session before it will take a turn. */
async function createSession(): Promise<string> {
  const created = await cellPost<{ session?: { id?: string }; id?: string }>(
    "/api/sessions", {},
  );
  const id = created.session?.id ?? created.id;
  if (!id) throw new BoltrigApiError(502, created, "the cell created no session");
  return id;
}

const TERMINAL = new Set(["run.completed", "run.cancelled", "run.failed", "error", "done"]);

const runKey = (conversationId: string) => `boltrig_run_${conversationId}`;

function rememberRun(conversationId: string, runId: string): void {
  try {
    sessionStorage.setItem(runKey(conversationId), runId);
  } catch {
    // A browser with storage disabled loses reattach, not the turn.
  }
}

/** The run this conversation last started, if the browser still remembers.
 *
 *  This is the ONLY way back to an in-flight run after a reload: no session
 *  response carries a run id and there is no run index, so a lost id means the
 *  turn can only be read as history. */
function recallRun(conversationId: string): string | null {
  try {
    return sessionStorage.getItem(runKey(conversationId));
  } catch {
    return null;
  }
}

function forgetRun(conversationId: string): void {
  try {
    sessionStorage.removeItem(runKey(conversationId));
  } catch {
    // As above.
  }
}

export async function followConversation(
  id: string,
  onFrame: (frame: ChatFollowFrame) => void,
  options: { since?: number; signal?: AbortSignal } = {},
): Promise<ChatFollowResult> {
  const { since = 0, signal } = options;
  const runId = recallRun(id);

  if (!runId) {
    return { status: "idle", cursor: since };
  }

  try {
    const response = await cellFetch(
      `/v1/runs/${encodeURIComponent(runId)}/events`,
      { signal }
    );

    if (!response.body) throw new BoltrigApiError(502, null, "the cell sent no stream");

    const clock = new CursorClock();
    let lastCursor = since;

    await pumpSse<Record<string, unknown>>(response.body, (frame) => {
      const hermesFrame = frameFromRunEvent(frame.data);
      if (TERMINAL.has(hermesFrame.name)) forgetRun(id);
      // One clock across the whole stream: the cursor is (run ordinal, count),
      // and a clock per frame would restart the count and regress it.
      for (const translated of translateRunStream([hermesFrame], id, clock)) {
        onFrame(translated as ChatFollowFrame);
        lastCursor = translated.cursor;
      }
    }, signal);

    return { status: "ended", cursor: lastCursor };
  } catch (e: any) {
    if (e.name === "AbortError") {
      return { status: "aborted", cursor: since };
    }
    if (e.status === 404) {
      sessionStorage.removeItem(`boltrig_run_${id}`);
      return { status: "idle", cursor: since };
    }
    throw e;
  }
}

export async function cancelRun(runId: string): Promise<void> {
  await cellPost(`/v1/runs/${encodeURIComponent(runId)}/stop`, {});
  // The remembered run id is left alone on purpose. Finding which conversation
  // owns this run would cost a lookup, and the next reattach resolves it for
  // free: a stopped run's event stream 404s, which followConversation already
  // reads as idle and clears.
}

export async function respondHitl(runId: string, decision: string, note?: string): Promise<{ status: string; reason?: string }> {
  await cellPost(`/v1/runs/${encodeURIComponent(runId)}/approval`, {
    choice: decision,
    all: false,
    note,
  });
  return { status: "ok" };
}

/** Pending approvals, of which Hermes keeps no index.
 *
 *  An approval arrives as an `approval.request` frame on a run's event stream
 *  and is answered at `POST /v1/runs/{run_id}/approval`; there is no "list what
 *  is waiting" route. An empty list is the truthful answer, and it is better
 *  than hiding the method: the approval UI stays mounted and renders the cards
 *  the stream delivers, which is where they actually come from.
 */
export async function hitl(): Promise<HITLListResponse> {
  return { requests: [] };
}
