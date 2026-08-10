// The Workflow Studio's chat lane (chat-first authoring, design pivot: the
// canvas is a read-only projection; this side panel is the ONLY authoring
// channel). It speaks the same governed lane as the main console chat -
// POST /v1/chat via streamChat - so a studio turn is an ordinary chat turn:
// the agent it convenes loads whatever skills the tenant grants (the
// authoring/control-plane skill is what makes workflow edits possible), every
// amendment goes through control.workflow.upsert, and every hold surfaces on
// this stream as a `hitl` event. Nothing here mutates a workflow directly.
//
// One conversation per workflow id, kept for the browser session so an
// iterate-approve-iterate loop stays one thread. The FIRST turn of a
// conversation is grounded with the workflow id + current steps; later turns
// rely on conversation memory (re-sending the steps every turn would bloat the
// context and drown the user's actual request).

import { useCallback, useRef, useState } from "react";
import { streamChat } from "@/api/sse";
import type { ChatEvent } from "@/api/types";
import type { WorkflowStep } from "./types";

export interface StudioHitl {
  requestId: string;
  question: string;
  verb?: string;
}

export interface StudioChatMessage {
  role: "user" | "assistant";
  text: string;
  // Compact activity lines (tool calls, workflow steps) - honesty without
  // re-implementing the full chat transcript renderer.
  activity: string[];
  hitls: StudioHitl[];
  pending?: boolean;
}

function conversationKey(workflowId: string): string {
  return `wf-studio-chat:${workflowId || "untitled"}`;
}

function grounding(workflowId: string, steps: WorkflowStep[]): string {
  return [
    `You are helping me author the workflow "${workflowId || "untitled"}" from the Studio side panel.`,
    "I describe changes in words; you propose and apply them through the governed",
    "control.workflow.upsert verb (expect a human approval hold and report it honestly).",
    "Current steps:",
    JSON.stringify(steps, null, 2),
  ].join("\n");
}

export function useStudioChat(workflowId: string, steps: WorkflowStep[]) {
  const [messages, setMessages] = useState<StudioChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  // Steps snapshot ride along on the first turn only; keep the latest without
  // re-rendering the hook's consumers on every canvas change.
  const stepsRef = useRef(steps);
  stepsRef.current = steps;

  const mention = useCallback((stepId: string) => {
    setDraft((d) => (d ? `${d.trimEnd()} @${stepId} ` : `@${stepId} `));
  }, []);

  const send = useCallback(async () => {
    const text = draft.trim();
    if (!text || busy) return;
    setDraft("");
    setError(null);
    setBusy(true);
    setMessages((m) => [
      ...m,
      { role: "user", text, activity: [], hitls: [] },
      { role: "assistant", text: "", activity: [], hitls: [], pending: true },
    ]);

    const key = conversationKey(workflowId);
    const priorConversation = sessionStorage.getItem(key);
    const message = priorConversation
      ? text
      : `${grounding(workflowId, stepsRef.current)}\n\nRequest: ${text}`;

    const patchTail = (fn: (msg: StudioChatMessage) => StudioChatMessage) =>
      setMessages((m) =>
        m.length ? [...m.slice(0, -1), fn(m[m.length - 1])] : m,
      );

    const onEvent = (ev: ChatEvent) => {
      if (ev.type === "message_start") {
        sessionStorage.setItem(key, ev.conversation_id);
        return;
      }
      if (ev.type === "text_delta") {
        patchTail((msg) => ({ ...msg, text: msg.text + ev.delta }));
        return;
      }
      if (ev.type === "tool_call") {
        const verb = ev.verb ?? ev.tool ?? "tool";
        patchTail((msg) => ({ ...msg, activity: [...msg.activity, `→ ${verb}`] }));
        return;
      }
      if (ev.type === "tool_result") {
        const verb = ev.verb ?? "tool";
        patchTail((msg) => ({
          ...msg,
          activity: [...msg.activity, `← ${verb}: ${ev.status}`],
        }));
        return;
      }
      if (ev.type === "workflow_step") {
        // `reason` (skip cause / retry tick / absorbed-failure strategy) is in
        // the SDK source (sdks/web/src/types.ts) but not yet in the published
        // package this app installs; read it structurally until the next SDK
        // publish picks it up.
        const reason = (ev as { reason?: string }).reason;
        const cause = reason ? ` (${reason})` : "";
        patchTail((msg) => ({
          ...msg,
          activity: [...msg.activity, `step ${ev.step_id}: ${ev.status}${cause}`],
        }));
        return;
      }
      if (ev.type === "hitl") {
        patchTail((msg) => ({
          ...msg,
          hitls: [
            ...msg.hitls,
            {
              requestId: ev.hitl_request_id,
              question: ev.question ?? `Approve ${ev.verb ?? "this action"}?`,
              verb: ev.verb,
            },
          ],
        }));
        return;
      }
      if (ev.type === "message_end" || ev.type === "cancelled") {
        patchTail((msg) => ({ ...msg, pending: false }));
      }
    };

    const ctrl = new AbortController();
    abortRef.current = ctrl;
    try {
      const queued = await streamChat(
        {
          conversation_id: priorConversation ?? undefined,
          message,
          origin: "studio",
        },
        onEvent,
        ctrl.signal,
      );
      if (queued) {
        patchTail((msg) => ({
          ...msg,
          pending: false,
          text: msg.text || "Queued behind an in-flight turn; it will land in this thread.",
        }));
      }
    } catch (err) {
      const reason = err instanceof Error ? err.message : "chat failed";
      setError(reason);
      patchTail((msg) => ({ ...msg, pending: false }));
    } finally {
      patchTail((msg) => ({ ...msg, pending: false }));
      setBusy(false);
      abortRef.current = null;
    }
  }, [draft, busy, workflowId]);

  return { messages, draft, setDraft, send, mention, busy, error };
}
