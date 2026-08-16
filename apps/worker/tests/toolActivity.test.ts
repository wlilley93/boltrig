import { describe, expect, it } from "vitest";
import {
  WORKER_INTEGRATION_CATALOGUE,
  type ToolEntry,
} from "@wlilley93/boltrig-web-sdk";

import {
  integrationForToolVerb,
  integrationsUsedByConversation,
  integrationsUsedByTools,
} from "../src/components/chat/toolActivity";

function tool(verb: string, key = verb): ToolEntry {
  return { key, verb, status: "ok" };
}

describe("tool integration evidence", () => {
  it("recognises every catalogue id only at tool-verb boundaries", () => {
    for (const entry of WORKER_INTEGRATION_CATALOGUE) {
      expect(integrationForToolVerb(`${entry.id}.read`)?.id).toBe(entry.id);
      expect(integrationForToolVerb(`${entry.id.replaceAll("-", "_")}:write`)?.id)
        .toBe(entry.id);
    }
    expect(integrationForToolVerb("dropbox.read")?.id).toBe("dropbox");
    expect(integrationForToolVerb("letterbox.read")).toBeNull();
    expect(integrationForToolVerb("assistant.said.figma")).not.toBeNull();
  });

  it("dedupes repeated exact receipts in first-observed order", () => {
    const result = integrationsUsedByTools([
      tool("figma.get_design_context", "a"),
      tool("github.issue.read", "b"),
      tool("figma.screenshot", "c"),
      tool("file.read", "d"),
    ]);
    expect(result.map((entry) => entry.id)).toEqual(["figma", "github"]);
  });

  it("keeps earlier persisted integrations in the conversation source list", () => {
    const result = integrationsUsedByConversation([{
      id: "assistant-a",
      role: "assistant",
      content: "Read the design.",
      created_at: "2026-08-11T10:00:00Z",
      events: [
        { type: "tool_call", tool: "figma.read", call_id: "figma-a" },
        { type: "tool_result", verb: "figma.read", call_id: "figma-a", status: "ok" },
      ],
    }, {
      id: "assistant-b",
      role: "assistant",
      content: "Checked the process.",
      created_at: "2026-08-11T10:01:00Z",
      events: [
        { type: "tool_call", tool: "background.process", call_id: "process-a" },
        { type: "tool_result", verb: "background.process", call_id: "process-a", status: "ok" },
      ],
    }], [tool("github.issue.read", "live-github")]);
    expect(result.map((entry) => entry.id)).toEqual(["figma", "github"]);
  });
});
