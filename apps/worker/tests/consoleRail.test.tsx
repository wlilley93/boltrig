// @vitest-environment happy-dom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  chatModelChoices: vi.fn(),
  artifacts: vi.fn(),
  chatConfig: vi.fn(),
  conversation: vi.fn(),
  conversations: vi.fn(),
  followConversation: vi.fn(),
  modelProfiles: vi.fn(),
  streamChat: vi.fn(),
}));

vi.mock("../src/client", () => ({ client: api }));
vi.mock("../src/components/VoiceCall", () => ({
  VoiceCall: () => null,
}));
vi.mock("../src/components/chat/RunSectionView", () => ({
  RunSectionView: ({ runId }: { runId: string }) => (
    <section aria-label="Run section" data-run-id={runId} />
  ),
}));

import { ChatView } from "../src/components/ChatView";

beforeEach(() => {
  vi.stubGlobal("matchMedia", vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })));
  api.chatModelChoices.mockResolvedValue({
    status: "ok",
    reason: null,
    choices: [],
    default_choice_id: "opaque-default-route",
    default_model_name: "openai/gpt-5.4",
    default_available: true,
  });
  document.documentElement.dataset.theme = "dark";
  api.artifacts.mockResolvedValue({ artifacts: [], next_cursor: null });
  api.chatConfig.mockResolvedValue({
    attachments: {
      max_count: 8,
      max_bytes: 262_144,
      max_total_bytes: 1_048_576,
      model_readable_media_types: ["text/*"],
    },
  });
  api.conversations.mockResolvedValue({
    conversations: [{
      id: "conversation-a",
      title: "Renewal outreach",
      status: "active",
      updated_at: "2026-01-01T00:00:00Z",
    }],
  });
  api.conversation.mockResolvedValue({ messages: [], active_run_id: null });
  api.modelProfiles.mockResolvedValue({ profiles: [] });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.unstubAllGlobals();
  delete document.documentElement.dataset.theme;
});

describe("console rail", () => {
  it("draws one floating glass surface without legacy rail copy or title editing", async () => {
    render(
      <ChatView conversationId="conversation-a" onConversation={vi.fn()} onChanged={vi.fn()} />,
    );

    await waitFor(() => {
      expect(document.querySelectorAll(".right-rail .chat-rail-glass").length).toBe(1);
    });

    const rail = document.querySelector(".right-rail") as HTMLElement;
    const groups = document.querySelectorAll(".right-rail .rail-group");
    expect(groups.length).toBe(1);
    for (const group of groups) {
      expect(group.parentElement?.classList.contains("chat-rail-glass")).toBe(true);
    }
    expect(rail.querySelector('[aria-label="Outputs"]')).toBeTruthy();
    expect(rail.textContent).not.toContain("This run");
    expect(rail.textContent).not.toContain("Governed by Boltrig");
    expect(rail.textContent).not.toContain("Conversation settings");
    expect(rail.querySelector('[aria-label="Conversation title"]')).toBeNull();
    expect(rail.querySelector('[aria-label="Conversation"]')).toBeNull();
    expect(rail.textContent).not.toContain("Close conversation");
    // Contracts with no entries do not gain screenshot-shaped placeholders.
    expect(rail.querySelector('[aria-label="Background processes"]')).toBeNull();
    expect(rail.querySelector('[aria-label="Computer Use"]')).toBeNull();
  });

  it("shows only contract-backed output, subagent, process, computer and source rows", async () => {
    api.artifacts.mockResolvedValue({
      artifacts: [{
        id: "artifact-a",
        name: "renewal-report.md",
        media_type: "text/markdown",
        revision: 2,
        size: 512,
      }],
      next_cursor: null,
    });
    api.conversation.mockResolvedValue({
      messages: [{
        id: "message-a",
        role: "user",
        content: "Use the playbook.",
        attachments: [{
          name: "renewal-playbook.txt",
          media_type: "text/plain",
          size: 8,
          data: btoa("playbook"),
        }],
      }],
      active_run_id: "run-a",
    });
    api.followConversation.mockImplementation(async (_id, onFrame) => {
      onFrame({
        cursor: 0,
        event: { type: "message_start", run_id: "run-a", conversation_id: "conversation-a" },
      });
      onFrame({
        cursor: 1,
        event: { type: "subagent", child_run_id: "child-a", task: "Check renewals", name: "Lyell" },
      });
      onFrame({
        cursor: 2,
        event: { type: "tool_call", call_id: "background-a", tool: "background.process" },
      });
      onFrame({
        cursor: 3,
        event: { type: "tool_call", call_id: "computer-a", tool: "computer.use" },
      });
      onFrame({
        cursor: 4,
        event: { type: "tool_call", call_id: "ordinary-a", tool: "crm.account.read" },
      });
      onFrame({
        cursor: 5,
        event: { type: "tool_call", call_id: "figma-a", tool: "figma.get_design_context" },
      });
      onFrame({
        cursor: 6,
        event: {
          type: "tool_result",
          call_id: "background-a",
          verb: "background.process",
          status: "pending_human",
        },
      });
      onFrame({
        cursor: 7,
        event: { type: "tool_call", call_id: "background-failed", tool: "background.retry" },
      });
      onFrame({
        cursor: 8,
        event: {
          type: "tool_result",
          call_id: "background-failed",
          verb: "background.retry",
          status: "grant_missing",
        },
      });
      return await new Promise(() => {});
    });

    render(
      <ChatView conversationId="conversation-a" onConversation={vi.fn()} onChanged={vi.fn()} />,
    );

    const rail = await waitFor(() => {
      const current = document.querySelector(".right-rail") as HTMLElement | null;
      expect(current?.querySelector('[aria-label="Background processes"]')).toBeTruthy();
      expect(current?.querySelector('[aria-label="Computer Use"]')).toBeTruthy();
      return current!;
    });
    expect(rail.querySelector('[aria-label="Outputs"]')?.textContent)
      .toContain("renewal-report.md");
    const subagentGroup = rail.querySelector('[aria-label="Subagents"]');
    expect(subagentGroup?.querySelector(".rail-agent-stack")?.getAttribute("aria-label"))
      .toContain("Lyell");
    expect(subagentGroup?.textContent).toContain("1 working");
    expect(rail.querySelector('[aria-label="Background processes"]')?.textContent)
      .toContain("Background process");
    expect(rail.querySelector('[aria-label="Background processes"]')?.textContent)
      .toContain("waiting for approval");
    expect(rail.querySelector('[aria-label="Background processes"] [data-kind="background"]'))
      .toBeTruthy();
    expect(rail.querySelector('[aria-label="Background processes"] [data-tone="amber"]'))
      .toBeTruthy();
    expect(rail.querySelector('[aria-label="Background processes"] [data-tone="red"]'))
      .toBeTruthy();
    expect(rail.querySelector('[aria-label="Background processes"]')?.textContent)
      .toContain("did not complete");
    expect(rail.querySelector('[aria-label="Background processes"]')?.textContent)
      .not.toContain("grant_missing");
    expect(rail.querySelector('[aria-label="Computer Use"]')?.textContent)
      .toContain("Computer use");
    expect(rail.querySelector('[aria-label="Computer Use"] [data-kind="computer"]'))
      .toBeTruthy();
    expect(rail.querySelector('[aria-label="Sources"]')?.textContent)
      .toContain("renewal-playbook.txt");
    expect(rail.querySelector('[aria-label="Sources"]')?.textContent).toContain("Figma");
    expect(rail.querySelector('[data-integration="figma"]')).toBeTruthy();
    expect(rail.querySelector('[aria-label="Sources"]')?.textContent).toContain("View all");
    expect(rail.querySelector('[aria-label="Manage sources"]')).toBeTruthy();
    // The section action owns the single plus; its empty row never repeats it.
    expect(rail.querySelector('[aria-label="Outputs"] .rail-output-mark')).toBeNull();
    // Ordinary tools have a real Work disclosure in the transcript; the rail
    // does not reclassify them as a background process or computer session.
    expect(rail.textContent).not.toContain("crm.account.read");
    expect(rail.textContent).not.toContain("£");
  });

  it("condenses durable subagents into one Familiar stack and truthful summary", async () => {
    api.conversation.mockResolvedValue({
      messages: [{
        id: "assistant-design",
        role: "assistant",
        content: "Design checked.",
        run_id: "run-design",
        events: [
          { type: "tool_call", call_id: "figma-design", tool: "figma.get_design_context" },
          { type: "tool_result", call_id: "figma-design", verb: "figma.get_design_context", status: "ok" },
        ],
      }, {
        id: "assistant-a",
        role: "assistant",
        content: "Renewals checked.",
        run_id: "run-settled",
        events: [
          { type: "subagent", child_run_id: "child-a", task: "Check renewals", name: "Lyell" },
          { type: "subagent", child_run_id: "child-b", task: "Check pipeline", name: "Hutton" },
          { type: "subagent", child_run_id: "child-c", task: "Check usage", name: "Noether" },
          { type: "subagent_end", child_run_id: "child-a", status: "ok" },
          { type: "subagent_end", child_run_id: "child-b", status: "ok" },
          { type: "subagent_end", child_run_id: "child-c", status: "ok" },
        ],
      }],
      active_run_id: null,
    });

    render(
      <ChatView conversationId="conversation-a" onConversation={vi.fn()} onChanged={vi.fn()} />,
    );

    const subagents = await waitFor(() => {
      const current = document.querySelector(
        '.right-rail [aria-label="Subagents"]',
      ) as HTMLElement | null;
      expect(current?.textContent).toContain("3 done");
      return current!;
    });
    expect(subagents.querySelectorAll(".rail-row")).toHaveLength(1);
    expect(subagents.querySelectorAll(".rail-agent-stack .familiar-orb")).toHaveLength(3);
    expect(subagents.querySelector(".rail-agent-stack")?.getAttribute("aria-label"))
      .toBe("Lyell, Hutton, Noether");
    // The durable run id makes the aggregate a real route to the run drawing.
    const runLink = subagents.querySelector("button.rail-row");
    expect(runLink).toBeTruthy();
    fireEvent.click(runLink!);
    expect(screen.getByRole("region", { name: "Run section" }).getAttribute("data-run-id"))
      .toBe("run-settled");
    // Sources are conversation-wide even though the rail's current run rows
    // come from the latest assistant turn.
    expect(document.querySelector('[aria-label="Sources"] [data-integration="figma"]'))
      .toBeTruthy();
  });

  it("keeps real source management reachable for an attachment-only conversation", async () => {
    api.conversation.mockResolvedValue({
      messages: [{
        id: "attachment-only",
        role: "user",
        content: "Use this.",
        attachments: [{
          name: "brief.txt",
          media_type: "text/plain",
          size: 42,
          data: btoa("brief"),
        }],
      }],
      active_run_id: null,
    });

    render(
      <ChatView conversationId="conversation-a" onConversation={vi.fn()} onChanged={vi.fn()} />,
    );

    const sourceGroup = await waitFor(() => {
      const group = document.querySelector<HTMLElement>('[aria-label="Sources"]');
      expect(group?.textContent).toContain("brief.txt");
      return group!;
    });
    expect(sourceGroup.querySelector('[aria-label="Manage sources"]')).toBeTruthy();
    expect(sourceGroup.textContent).toContain("View all");
  });

  it("keeps same-name attachment revisions when their payloads differ", async () => {
    api.conversation.mockResolvedValue({
      messages: [{
        id: "revision-one",
        role: "user",
        content: "Use the first revision.",
        attachments: [{
          name: "brief.txt",
          media_type: "text/plain",
          size: 5,
          data: btoa("first"),
        }],
      }, {
        id: "revision-two",
        role: "user",
        content: "Use the corrected revision.",
        attachments: [{
          name: "brief.txt",
          media_type: "text/plain",
          size: 5,
          data: btoa("later"),
        }],
      }],
      active_run_id: null,
    });

    render(
      <ChatView conversationId="conversation-a" onConversation={vi.fn()} onChanged={vi.fn()} />,
    );

    const sourceGroup = await waitFor(() => {
      const group = document.querySelector<HTMLElement>('[aria-label="Sources"]');
      expect(group).toBeTruthy();
      return group!;
    });
    const revisions = [...sourceGroup.querySelectorAll(".rail-label")]
      .filter((label) => label.textContent === "brief.txt");
    expect(revisions).toHaveLength(2);
  });

  it("excludes superseded replies from transcript, counts, rail and sources", async () => {
    api.conversation.mockResolvedValue({
      messages: [{
        id: "assistant-old",
        role: "assistant",
        content: "Obsolete answer",
        superseded_by: "assistant-current",
        events: [
          { type: "message_start", run_id: "run-old", conversation_id: "conversation-a" },
          { type: "subagent", child_run_id: "ghost-run", task: "Old work", name: "Ghost" },
          { type: "tool_call", call_id: "figma-old", tool: "figma.read" },
          { type: "tool_result", call_id: "figma-old", verb: "figma.read", status: "ok" },
          { type: "message_end", run_id: "run-old" },
        ],
      }, {
        id: "assistant-current",
        role: "assistant",
        content: "Current answer",
        events: [],
      }],
      active_run_id: null,
    });

    render(
      <ChatView conversationId="conversation-a" onConversation={vi.fn()} onChanged={vi.fn()} />,
    );

    await waitFor(() => expect(document.body.textContent).toContain("Current answer"));
    expect(document.body.textContent).not.toContain("Obsolete answer");
    expect(document.body.textContent).not.toContain("Ghost");
    expect(document.querySelector(".chat-header-sub")).toBeNull();
    expect(document.querySelector('.right-rail [aria-label="Sources"]')).toBeNull();
    expect(document.querySelector('[data-integration="figma"]')).toBeNull();
  });
});
