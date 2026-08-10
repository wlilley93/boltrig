// Characterizes the chat-first Studio panel (design pivot: the canvas is a
// read-only projection; this docked side panel is the ONLY authoring channel).
// The old behavior - prefill the main chat composer and navigate away - is
// deliberately gone: the conversation lives here, sends go through the same
// governed /v1/chat lane, and approval holds surface inline as review cards.

import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { BoltChatPanel } from "@/panels/workflowCanvas/BoltChatPanel";
import type { useStudioChat } from "@/panels/workflowCanvas/useStudioChat";

type StudioChat = ReturnType<typeof useStudioChat>;

function stubChat(overrides: Partial<StudioChat> = {}): StudioChat {
  return {
    messages: [],
    draft: "",
    setDraft: vi.fn(),
    send: vi.fn(async () => undefined),
    mention: vi.fn(),
    busy: false,
    error: null,
    ...overrides,
  } as StudioChat;
}

afterEach(() => {
  cleanup();
  window.location.hash = "";
});

describe("BoltChatPanel", () => {
  it("sends the draft through the studio chat lane and stays in the studio", () => {
    const chat = stubChat({ draft: "Add an approval before fetch" });
    render(
      <BoltChatPanel
        open
        onToggle={() => undefined}
        workflowId="release"
        steps={[]}
        chat={chat}
      />,
    );

    // Chat-first framing: the panel says the canvas is inspect-only and edits
    // apply only through an approval hold.
    expect(screen.getByText(/nothing applies without your approval/i)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(chat.send).toHaveBeenCalledOnce();
    // No navigation: the conversation lives next to the canvas it changes.
    expect(window.location.hash).not.toContain("/chat");
  });

  it("does not send an empty draft", () => {
    const chat = stubChat({ draft: "   " });
    render(
      <BoltChatPanel open onToggle={() => undefined} workflowId="" steps={[]} chat={chat} />,
    );
    expect(screen.getByRole("button", { name: "Send" }).hasAttribute("disabled")).toBe(true);
  });

  it("renders an approval hold as an inline review card", () => {
    const chat = stubChat({
      messages: [
        {
          role: "assistant",
          text: "Drafted the change; it is holding for your approval.",
          activity: ["→ control.workflow.upsert", "← control.workflow.upsert: pending_human"],
          hitls: [
            {
              requestId: "hitl-1",
              question: "Approve control.workflow.upsert?",
              verb: "control.workflow.upsert",
            },
          ],
        },
      ],
    });
    render(
      <BoltChatPanel open onToggle={() => undefined} workflowId="release" steps={[]} chat={chat} />,
    );
    expect(screen.getByText("Approve control.workflow.upsert?")).toBeTruthy();
    // Inline decision through the one respond path; Detail deep-links to the
    // full Approvals surface.
    expect(screen.getByRole("button", { name: "Approve" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Reject" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Detail" })).toBeTruthy();
    // The governed action trail stays visible - honesty over polish.
    expect(screen.getByText("→ control.workflow.upsert")).toBeTruthy();
  });
});
