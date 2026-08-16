import { describe, expect, it } from "vitest";
import type { ChatMessage } from "@wlilley93/boltrig-web-sdk";

import {
  durableTurnFromMessages,
  queuedMessagesFrom,
  uniqueConversationSources,
} from "./useChatProjection";

function message(overrides: Partial<ChatMessage> & Pick<ChatMessage, "id" | "role">): ChatMessage {
  return {
    content: "",
    created_at: "2026-08-12T12:00:00Z",
    ...overrides,
  };
}

describe("chat presentation projection", () => {
  it("carries the latest durable run boundary into the task rail", () => {
    const turn = durableTurnFromMessages([
      message({ id: "assistant-1", role: "assistant", run_id: "run-old" }),
      message({ id: "user-2", role: "user" }),
      message({ id: "assistant-2", role: "assistant", run_id: "run-latest" }),
    ]);

    expect(turn.runId).toBe("run-latest");
    expect(turn.ended).toBe(true);
  });

  it("deduplicates optimistic queued steers without reviving consumed messages", () => {
    const queued = queuedMessagesFrom([
      message({ id: "user-1", role: "user" }),
      message({ id: "assistant-1", role: "assistant" }),
      message({ id: "queued-1", role: "user", content: "server copy" }),
      message({ id: "consumed", role: "user" }),
    ], [
      message({ id: "queued-1", role: "user", content: "optimistic copy" }),
      message({ id: "queued-2", role: "user" }),
    ], ["consumed"]);

    expect(queued.map((item) => item.id)).toEqual(["queued-1", "queued-2"]);
    expect(queued[0]?.content).toBe("optimistic copy");
  });

  it("deduplicates identical source payloads but preserves same-name revisions", () => {
    const sources = uniqueConversationSources([
      message({
        id: "user-1",
        role: "user",
        attachments: [{ name: "brief.txt", media_type: "text/plain", data: "YQ==" }],
      }),
    ], [
      message({
        id: "queued-1",
        role: "user",
        attachments: [
          { name: "brief.txt", media_type: "text/plain", data: "YQ==" },
          { name: "brief.txt", media_type: "text/plain", data: "Yg==" },
        ],
      }),
    ]);

    expect(sources.map((source) => source.data)).toEqual(["YQ==", "Yg=="]);
  });
});
