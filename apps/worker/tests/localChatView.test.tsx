// @vitest-environment happy-dom

import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  approvalPosture: vi.fn(),
}));
const local = vi.hoisted(() => ({
  localAgentRoots: vi.fn(),
  localAgentStatus: vi.fn(),
  localAgentPosture: vi.fn(),
  putLocalAgentPosture: vi.fn(),
  runLocalAgentTurn: vi.fn(),
  saveLocalConversation: vi.fn(),
  stopLocalAgentTurn: vi.fn(),
}));

vi.mock("../src/client", () => ({ client: api }));
vi.mock("../src/localAgentClient", async (importOriginal) => ({
  ...await importOriginal<typeof import("../src/localAgentClient")>(),
  ...local,
}));

import { LocalChatView } from "../src/components/LocalChatView";

beforeEach(() => {
  api.approvalPosture.mockResolvedValue({ posture: "risk_based" });
  local.localAgentStatus.mockResolvedValue({
    runtime: "local",
    state: "ready",
    source: "development",
    version: "0.145.0",
    active: false,
    reason: null,
  });
  local.localAgentRoots.mockResolvedValue([{ root_id: "root-1" }]);
  local.localAgentPosture.mockResolvedValue({ posture: "risk_based" });
  local.putLocalAgentPosture.mockImplementation(async (posture) => ({ posture }));
  local.saveLocalConversation.mockImplementation(() => undefined);
  local.stopLocalAgentTurn.mockResolvedValue(undefined);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  localStorage.clear();
});

describe("desktop local chat", () => {
  it("points an unbound desktop to the shipped Advanced settings section", async () => {
    local.localAgentRoots.mockResolvedValue([]);
    render(<LocalChatView
      conversationId={null}
      onChanged={vi.fn()}
      onConversation={vi.fn()}
    />);

    const input = await screen.findByLabelText("Task instructions");
    await waitFor(() => expect(input.getAttribute("placeholder"))
      .toBe("Bind a local workspace in Settings → Advanced"));
    expect(screen.getByText(
      "Bind a read/write workspace with local commands enabled in Settings → Advanced.",
    )).toBeTruthy();
  });

  it("states a known missing local runtime instead of appearing to load forever", async () => {
    local.localAgentStatus.mockResolvedValue({
      runtime: "local",
      state: "unavailable",
      source: null,
      version: null,
      active: false,
      reason: "local_agent_binary_not_bundled",
    });
    render(<LocalChatView
      conversationId={null}
      onChanged={vi.fn()}
      onConversation={vi.fn()}
    />);

    const input = await screen.findByLabelText("Task instructions");
    await waitFor(() => expect(input.getAttribute("placeholder"))
      .toBe("Local Codex is not included in this development build"));
    expect((input as HTMLTextAreaElement).disabled).toBe(true);
    expect(screen.queryByPlaceholderText("Loading conversation state…")).toBeNull();
  });

  it("adopts a new local route only after its entire first answer settles", async () => {
    let finish!: () => void;
    local.runLocalAgentTurn.mockImplementation(async (_input, onEvent) => {
      onEvent({
        type: "message_start",
        thread_id: "thread-1",
        turn_id: "turn-1",
        model: "gpt-5.6-sol",
      });
      await new Promise<void>((resolve) => { finish = resolve; });
      onEvent({ type: "text_delta", delta: "Local answer" });
      onEvent({
        type: "message_end",
        thread_id: "thread-1",
        turn_id: "turn-1",
        status: "completed",
      });
      return {
        thread_id: "thread-1",
        turn_id: "turn-1",
        status: "completed",
        model: "gpt-5.6-sol",
      };
    });
    const onConversation = vi.fn();
    const onWorkingChange = vi.fn();
    render(<LocalChatView
      conversationId={null}
      onChanged={vi.fn()}
      onConversation={onConversation}
      onWorkingChange={onWorkingChange}
    />);

    const input = await screen.findByLabelText("Task instructions");
    await waitFor(() => expect((input as HTMLTextAreaElement).disabled).toBe(false));
    fireEvent.change(input, { target: { value: "Inspect locally" } });
    fireEvent.keyDown(input, { key: "Enter", code: "Enter", keyCode: 13 });

    await waitFor(() => expect(local.runLocalAgentTurn).toHaveBeenCalledOnce());
    await waitFor(() => expect(local.saveLocalConversation).toHaveBeenCalled());
    expect(onWorkingChange).toHaveBeenCalledWith("local:thread-1", true);
    expect(onConversation).not.toHaveBeenCalled();

    await act(async () => finish());
    await waitFor(() => expect(onConversation).toHaveBeenCalledWith("local:thread-1"));
    expect(onWorkingChange).toHaveBeenLastCalledWith("local:thread-1", false);
    expect(await screen.findByText("Local answer")).toBeTruthy();
    expect(local.runLocalAgentTurn.mock.calls[0]?.[0]).toEqual({
      rootId: "root-1",
      threadId: undefined,
      message: "Inspect locally",
    });
    expect(screen.getByText("Local workspace")).toBeTruthy();
    expect(screen.getByText("Cloud plugins are not connected")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Plugins" })).toBeNull();
  });

  it("interrupts the native child before adopting another local task", async () => {
    localStorage.setItem("boltrig.local-conversations.v1", JSON.stringify([{
      id: "local:thread-b",
      thread_id: "thread-b",
      root_id: "root-1",
      title: "Thread B",
      status: "active",
      model: "gpt-5.6-sol",
      messages: [],
      created_at: "2026-08-13T10:00:00.000Z",
      updated_at: "2026-08-13T10:00:00.000Z",
    }]));
    let rejectRun!: (reason: Error) => void;
    local.runLocalAgentTurn.mockImplementation((_input, onEvent) => {
      onEvent({
        type: "message_start",
        thread_id: "thread-a",
        turn_id: "turn-a",
        model: "gpt-5.6-sol",
      });
      return new Promise((_resolve, reject) => { rejectRun = reject; });
    });
    local.stopLocalAgentTurn.mockImplementation(async () => {
      rejectRun(new Error("local_agent_cancelled"));
    });
    const view = render(<LocalChatView
      conversationId={null}
      onChanged={vi.fn()}
      onConversation={vi.fn()}
    />);

    const input = await screen.findByLabelText("Task instructions");
    await waitFor(() => expect((input as HTMLTextAreaElement).disabled).toBe(false));
    fireEvent.change(input, { target: { value: "Long local task" } });
    fireEvent.keyDown(input, { key: "Enter", code: "Enter", keyCode: 13 });
    await waitFor(() => expect(local.runLocalAgentTurn).toHaveBeenCalledOnce());

    view.rerender(<LocalChatView
      conversationId="local:thread-b"
      onChanged={vi.fn()}
      onConversation={vi.fn()}
    />);

    await waitFor(() => expect(local.stopLocalAgentTurn).toHaveBeenCalledOnce());
    expect(await screen.findByRole("heading", { name: "Thread B" })).toBeTruthy();
    expect(screen.queryByText("Local task stopped.")).toBeNull();
  });
});
