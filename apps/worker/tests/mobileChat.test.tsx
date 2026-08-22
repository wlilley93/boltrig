// @vitest-environment happy-dom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { NormalizedTurn } from "@wlilley93/boltrig-web-sdk";

import { MobileChat } from "../src/components/MobileChat";

const api = vi.hoisted(() => ({
  invokeApprovalState: vi.fn(),
  respondHitl: vi.fn(),
}));
vi.mock("../src/client", () => ({ client: api }));

beforeEach(() => {
  api.invokeApprovalState.mockReset().mockResolvedValue({ status: "pending" });
  api.respondHitl.mockReset().mockResolvedValue({ status: "answered" });
});

afterEach(() => {
  cleanup();
  delete document.documentElement.dataset.mobileSurface;
});

const EMPTY_TURN: NormalizedTurn = {
  text: "", reasoning: "", tools: [], subagents: [], hitls: [],
  questions: [], displayObjects: [], steps: [], timeline: [], ended: false,
  cancelled: false, degraded: false,
};

function turnWith(patch: Partial<NormalizedTurn>): NormalizedTurn {
  return { ...EMPTY_TURN, ...patch };
}

function mobileChat(props: Partial<Parameters<typeof MobileChat>[0]> = {}) {
  return (
    <MobileChat
      busy={false}
      closed={false}
      composerDisabled={false}
      composerValue=""
      continuity=""
      conversationLoadError=""
      error=""
      loadingConversation={false}
      messages={[]}
      newState={false}
      onBack={vi.fn()}
      onComposerChange={vi.fn()}
      onReconnect={vi.fn()}
      onReorderQueued={vi.fn()}
      onRetryConversation={vi.fn()}
      onSend={vi.fn()}
      onSteerQueued={vi.fn()}
      onStop={vi.fn()}
      queueReordering={false}
      queuedMessages={[]}
      retryFollow={false}
      subtitle=""
      title="Renewal outreach"
      turn={EMPTY_TURN}
      turnIsAnswerable={false}
      turnIsLive={false}
      {...props}
    />
  );
}

function renderMobile(props: Partial<Parameters<typeof MobileChat>[0]> = {}) {
  return render(mobileChat(props));
}

describe("mobile surface", () => {
  it("claims the screen so the shell chrome cannot sit on the back control", () => {
    renderMobile();
    expect(document.documentElement.dataset.mobileSurface).toBe("chat");
    expect(screen.getByRole("button", { name: "Back" })).toBeTruthy();
  });

  it("releases the screen when it unmounts", () => {
    const view = renderMobile();
    expect(document.documentElement.dataset.mobileSurface).toBe("chat");
    view.unmount();
    expect(document.documentElement.dataset.mobileSurface).toBeUndefined();
  });

  it("draws the agent tree and the plan from the live turn", () => {
    renderMobile({
      turn: turnWith({
        subagents: [
          { key: "a", childRunId: "r1", task: "Read health signals", skills: [], name: "Lyell" },
          { key: "b", childRunId: "r2", task: "Draft outreach", skills: [], name: "Hutton" },
        ],
        steps: [
          { stepId: "s1", action: "Read the accounts", status: "ok" },
          { stepId: "s2", action: "Draft the messages", status: "running" },
        ],
      }),
    });

    const agents = screen.getByText("2 subagents").closest("summary");
    expect(agents?.closest("details")?.open).toBe(false);
    fireEvent.click(agents!);
    expect(screen.getByText("Lyell")).toBeTruthy();
    expect(screen.getByText("Hutton")).toBeTruthy();
    expect(screen.getByText("The plan")).toBeTruthy();
    // Progress counts only what finished, so a running step is not claimed done.
    expect(screen.getByText("1 of 2")).toBeTruthy();
  });

  it("surfaces what is waiting on a person", () => {
    renderMobile({
      turn: turnWith({
        hitls: [{
          hitlRequestId: "h1",
          kind: "approval",
          question: "Raise 3 tickets",
          options: [],
        }],
      }),
    });
    expect(screen.getByText("Raise 3 tickets")).toBeTruthy();
    // Without a wired responder the row stays read-only: the surface never
    // draws a button that goes nowhere.
    expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
  });

  it("answers an approval inline when a responder is wired", async () => {
    const onRespondHitl = vi.fn().mockResolvedValue(true);
    renderMobile({
      onRespondHitl,
      turnIsAnswerable: true,
      turnIsLive: true,
      turn: turnWith({
        hitls: [{
          hitlRequestId: "h1",
          kind: "approval",
          question: "Raise 3 tickets",
          options: [],
        }],
      }),
    });

    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    expect(onRespondHitl).toHaveBeenCalledWith("h1", "approve");
    expect(await screen.findByText(/was recorded/)).toBeTruthy();
    // The optimistic settle removes the buttons once the kernel accepted it.
    expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
  });

  it("reverts the optimistic settle when the kernel refuses the decision", async () => {
    const onRespondHitl = vi.fn().mockResolvedValue(false);
    renderMobile({
      onRespondHitl,
      turnIsAnswerable: true,
      turnIsLive: true,
      turn: turnWith({
        hitls: [{
          hitlRequestId: "h1",
          kind: "approval",
          question: "Raise 3 tickets",
          options: [],
        }],
      }),
    });

    fireEvent.click(screen.getByRole("button", { name: "Deny" }));
    expect(await screen.findByText(/was not accepted/)).toBeTruthy();
  });

  it("stops a live run instead of invoking the send callback", () => {
    const onSend = vi.fn();
    const onStop = vi.fn();
    const view = renderMobile({ busy: true, onSend, onStop });
    fireEvent.click(screen.getByRole("button", { name: "Stop" }));
    expect(onStop).toHaveBeenCalledTimes(1);
    expect(onSend).not.toHaveBeenCalled();
    view.unmount();
    renderMobile({ busy: false, composerValue: "Follow up", onSend, onStop });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(onSend).toHaveBeenCalledTimes(1);
    expect(onStop).toHaveBeenCalledTimes(1);
  });

  it("does not offer an empty follow up", () => {
    const onSend = vi.fn();
    renderMobile({ composerValue: "", onSend });
    const send = screen.getByRole("button", { name: "Send" }) as HTMLButtonElement;
    expect(send.disabled).toBe(true);
    fireEvent.click(send);
    expect(onSend).not.toHaveBeenCalled();
  });

  it("renders every unsuperseded durable message followed by live turn text", () => {
    renderMobile({
      messages: [
        { id: "u1", role: "user", content: "First request", created_at: "2026-08-11T10:00:00Z" },
        { id: "a1", role: "assistant", content: "First answer", created_at: "2026-08-11T10:00:01Z" },
        { id: "u2", role: "user", content: "Second request", created_at: "2026-08-11T10:00:02Z" },
        {
          id: "a-old",
          role: "assistant",
          content: "Superseded answer",
          superseded_by: "a2",
          created_at: "2026-08-11T10:00:03Z",
        },
        { id: "a2", role: "assistant", content: "Current answer", created_at: "2026-08-11T10:00:04Z" },
      ],
      turn: turnWith({ runId: "run-2", text: "Live continuation" }),
      turnIsLive: true,
    });

    expect(screen.getByText("First request")).toBeTruthy();
    expect(screen.getByText("First answer")).toBeTruthy();
    expect(screen.getByText("Second request")).toBeTruthy();
    expect(screen.getByText("Current answer")).toBeTruthy();
    expect(screen.getByText("Live continuation")).toBeTruthy();
    expect(screen.queryByText("Superseded answer")).toBeNull();
  });

  it("follows a same-count durable message replacement while the reader is at the bottom", () => {
    const first = [{
      id: "assistant-a",
      role: "assistant" as const,
      content: "First durable answer",
      created_at: "2026-08-11T10:00:00Z",
    }];
    const view = renderMobile({ messages: first });
    const transcript = screen.getByRole("log", { name: "Conversation transcript" });
    let scrollTop = 0;
    Object.defineProperty(transcript, "scrollHeight", { configurable: true, value: 480 });
    Object.defineProperty(transcript, "scrollTop", {
      configurable: true,
      get: () => scrollTop,
      set: (value: number) => { scrollTop = value; },
    });

    view.rerender(mobileChat({
      messages: [{
        id: "assistant-b",
        role: "assistant",
        content: "Replacement durable answer",
        created_at: "2026-08-11T10:01:00Z",
      }],
    }));

    expect(scrollTop).toBe(480);
    expect(screen.getByText("Replacement durable answer")).toBeTruthy();
  });

  it("surfaces retry, reconnect, queued and read-only state without a dead attach control", () => {
    const onRetryConversation = vi.fn();
    const onReconnect = vi.fn();
    const onSteerQueued = vi.fn();
    const queued = {
      id: "queued-1",
      role: "user",
      content: "Queue this next",
      created_at: "2026-08-11T10:00:00Z",
    };
    renderMobile({
      composerDisabled: true,
      conversationLoadError: "summary offline",
      continuity: "Live updates paused.",
      error: "The stream disconnected.",
      onReconnect,
      onRetryConversation,
      onSteerQueued,
      queuedMessages: [queued],
      retryFollow: true,
    });

    const alerts = screen.getAllByRole("alert");
    expect(alerts.some((item) => item.textContent?.includes("summary offline"))).toBe(true);
    expect(alerts.some((item) => item.textContent?.includes("stream disconnected"))).toBe(true);
    expect((screen.getByLabelText("Follow up") as HTMLTextAreaElement).disabled).toBe(true);
    expect(screen.queryByRole("button", { name: "Attach" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Retry conversation" }));
    fireEvent.click(screen.getByRole("button", { name: "Reconnect" }));
    fireEvent.click(screen.getByRole("button", { name: /Steer queued message/ }));
    expect(onRetryConversation).toHaveBeenCalledTimes(1);
    expect(onReconnect).toHaveBeenCalledTimes(1);
    expect(onSteerQueued).toHaveBeenCalledWith(queued);
  });

  it("keeps live and canonically pending durable questions answerable", async () => {
    const question = {
      questionId: "q1",
      prompt: "Which account owner?",
      choices: ["Noether"],
    };
    const live = renderMobile({
      turn: turnWith({ questions: [question] }),
      turnIsAnswerable: true,
      turnIsLive: true,
    });
    expect(screen.getByRole("textbox", { name: "Live question answer" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Noether" })).toBeTruthy();

    live.unmount();
    renderMobile({ turn: turnWith({ ended: true, questions: [question] }) });
    await waitFor(() => expect(api.invokeApprovalState).toHaveBeenCalledWith("q1"));
    expect(screen.getByText("Which account owner?")).toBeTruthy();
    expect(screen.getByRole("textbox", { name: "Live question answer" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Noether" })).toBeTruthy();
  });

  it("answers a canonically pending durable approval from the run chat", async () => {
    const onRespondHitl = vi.fn().mockResolvedValue(true);
    renderMobile({
      onRespondHitl,
      turn: turnWith({
        ended: true,
        hitls: [{
          hitlRequestId: "h-settled",
          kind: "approval",
          question: "Publish the report?",
          options: ["approve", "deny"],
        }],
      }),
      turnIsAnswerable: false,
      turnIsLive: true,
    });

    expect(screen.getByText("Publish the report?")).toBeTruthy();
    await waitFor(() => expect(api.invokeApprovalState).toHaveBeenCalledWith("h-settled"));
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    await waitFor(() => expect(api.respondHitl).toHaveBeenCalledWith("h-settled", "approve"));
    expect(onRespondHitl).not.toHaveBeenCalled();
  });

  it("reconciles decisions from earlier durable turns", async () => {
    renderMobile({
      messages: [{
        id: "assistant-earlier",
        role: "assistant",
        content: "I paused for an owner choice.",
        created_at: "2026-08-11T10:00:00Z",
        events: [{
          type: "question",
          run_id: "run-earlier",
          question_id: "question-earlier",
          prompt: "Who should own the account?",
          choices: ["Noether"],
        }, { type: "message_end", run_id: "run-earlier" }],
      }, {
        id: "assistant-latest",
        role: "assistant",
        content: "Later work completed.",
        created_at: "2026-08-11T10:01:00Z",
        events: [
          { type: "tool_call", call_id: "latest-tool", tool: "file.read" },
          { type: "tool_result", call_id: "latest-tool", verb: "file.read", status: "ok" },
        ],
      }],
      turn: turnWith({ tools: [{ key: "latest-tool", verb: "file.read", status: "ok" }] }),
    });

    await waitFor(() => expect(api.invokeApprovalState).toHaveBeenCalledWith("question-earlier"));
    expect(screen.getByText("Who should own the account?")).toBeTruthy();
    expect(screen.getByRole("textbox", { name: "Live question answer" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Noether" })).toBeTruthy();
  });

  it("exposes disclosure state and preserves exact activity statuses", () => {
    renderMobile({
      turn: turnWith({
        tools: [{ key: "tool-1", verb: "figma.read", status: "degraded" }],
        subagents: [{
          key: "agent-1",
          childRunId: "child-1",
          task: "Inspect the design",
          skills: [],
          name: "Lyell",
          status: "degraded",
        }],
        steps: [{ stepId: "step-1", action: "Compare frames", status: "paused" }],
      }),
    });

    const tools = screen.getByText("Used Figma integration").closest("summary");
    expect(tools).toBeTruthy();
    expect(tools!.closest("details")?.open).toBe(false);
    fireEvent.click(tools!);
    expect(tools!.closest("details")?.open).toBe(true);
    expect(screen.getByText("figma.read")).toBeTruthy();
    expect(screen.getAllByText("Degraded")).toHaveLength(2);
    fireEvent.click(screen.getByText("1 subagent").closest("summary")!);
    expect(screen.getByText("degraded")).toBeTruthy();

    const plan = screen.getByRole("button", { name: /The plan/ });
    expect(plan.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByText("paused")).toBeTruthy();
  });

  it("docks queued work above a multiline composer", () => {
    renderMobile({
      queuedMessages: [{
        id: "queued-1",
        role: "user",
        content: "Inspect the compact layout",
        created_at: "2026-08-11T10:00:00Z",
      }],
    });

    const dock = screen.getByRole("region", { name: "Queued messages" }).parentElement;
    const composer = screen.getByLabelText("Follow up");
    expect(dock?.classList.contains("m-composer-dock")).toBe(true);
    expect(composer.tagName).toBe("TEXTAREA");
    expect(dock?.lastElementChild?.classList.contains("m-composer")).toBe(true);
  });

  it("offers touch-sized earlier and later controls for queued work", () => {
    const onReorderQueued = vi.fn();
    renderMobile({
      onReorderQueued,
      queuedMessages: [
        {
          id: "queued-1",
          role: "user",
          content: "First queued turn",
          created_at: "2026-08-11T10:00:00Z",
        },
        {
          id: "queued-2",
          role: "user",
          content: "Second queued turn",
          created_at: "2026-08-11T10:00:01Z",
        },
      ],
    });

    fireEvent.click(screen.getByRole("button", {
      name: "Move queued message later: First queued turn",
    }));
    expect(onReorderQueued).toHaveBeenCalledWith(
      ["queued-1", "queued-2"],
      ["queued-2", "queued-1"],
    );
  });

  it("announces an existing conversation load without showing the New-chat welcome", () => {
    renderMobile({ composerDisabled: true, loadingConversation: true, newState: false });
    expect(screen.getByRole("status").textContent).toContain("Loading conversation");
    expect(screen.queryByText(/Say what needs doing/)).toBeNull();
    expect((screen.getByLabelText("Follow up") as HTMLTextAreaElement).disabled).toBe(true);
  });
});
