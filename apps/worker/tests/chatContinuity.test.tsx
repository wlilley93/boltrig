// @vitest-environment happy-dom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { BoltrigApiError } from "@wlilley93/boltrig-web-sdk";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  artifacts: vi.fn(),
  cancelRun: vi.fn(),
  chatConfig: vi.fn(),
  conversation: vi.fn(),
  conversations: vi.fn(),
  followConversation: vi.fn(),
  modelProfiles: vi.fn(),
  restoreMyConversation: vi.fn(),
  streamChat: vi.fn(),
}));

vi.mock("../src/client", () => ({ client: api }));

import { ChatView } from "../src/components/ChatView";

beforeEach(() => {
  api.artifacts.mockResolvedValue({ artifacts: [] });
  api.cancelRun.mockResolvedValue({ status: "cancelled" });
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
      title: "Renewals",
      status: "active",
      updated_at: "2026-01-01T00:00:00Z",
    }],
  });
  api.modelProfiles.mockResolvedValue({ profiles: [] });
  api.restoreMyConversation.mockResolvedValue({
    status: "ok",
    id: "conversation-a",
    conversation_status: "active",
  });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("Worker chat continuity", () => {
  it("labels a degraded live response as incomplete", async () => {
    api.conversation.mockResolvedValue({ messages: [], active_run_id: "run-a" });
    api.followConversation.mockImplementation(async (_id, onFrame) => {
      onFrame({
        cursor: 1,
        event: {
          type: "text_delta",
          delta: "degraded (codex: unavailable)",
          degraded: true,
        },
      });
      return await new Promise(() => {});
    });

    render(
      <ChatView
        conversationId="conversation-a"
        onConversation={vi.fn()}
        onChanged={vi.fn()}
      />,
    );

    expect(await screen.findByText(
      "This response used a degraded fallback; treat its result as incomplete.",
    )).toBeTruthy();
    expect(screen.getByText("degraded (codex: unavailable)")).toBeTruthy();
  });

  it("reattaches to the server-selected active run and refreshes the durable transcript", async () => {
    let finish!: (value: { status: "ended"; cursor: number }) => void;
    api.conversation
      .mockResolvedValueOnce({ messages: [], active_run_id: "run-a" })
      .mockResolvedValue({
        messages: [{
          id: "assistant-a",
          role: "assistant",
          content: "Durable answer.",
          created_at: "2026-01-01T00:00:00Z",
        }],
        active_run_id: null,
      });
    api.followConversation.mockImplementation(async (_id, onFrame) => {
      onFrame({
        cursor: 0,
        event: {
          type: "message_start",
          run_id: "run-a",
          conversation_id: "conversation-a",
        },
      });
      onFrame({ cursor: 1, event: { type: "text_delta", delta: "Live answer." } });
      return await new Promise((resolve) => {
        finish = resolve;
      });
    });

    render(
      <ChatView
        conversationId="conversation-a"
        onConversation={vi.fn()}
        onChanged={vi.fn()}
      />,
    );

    expect(await screen.findByText("Live answer.")).toBeTruthy();
    expect(api.followConversation).toHaveBeenCalledWith(
      "conversation-a",
      expect.any(Function),
      expect.objectContaining({ since: 0, signal: expect.any(AbortSignal) }),
    );
    finish({ status: "ended", cursor: 1 });
    expect(await screen.findByText("Durable answer.")).toBeTruthy();
  });

  it("refreshes governed artifacts and surfaces rejected or withheld live activity", async () => {
    api.conversation.mockResolvedValue({ messages: [], active_run_id: "run-a" });
    api.artifacts
      .mockResolvedValueOnce({ artifacts: [], next_cursor: null })
      .mockResolvedValue({
        artifacts: [{
          id: "artifact-a",
          owner_id: "alice",
          conversation_id: "conversation-a",
          run_id: "run-a",
          name: "answer.txt",
          digest: "sha256:answer",
          media_type: "text/plain",
          size: 42,
          revision: 1,
          provenance: { kind: "agent" },
          created_at: "2026-01-01T00:00:00Z",
        }],
        next_cursor: null,
      });
    api.followConversation.mockImplementation(async (_id, onFrame) => {
      onFrame({
        cursor: 0,
        event: {
          type: "message_start",
          run_id: "run-a",
          conversation_id: "conversation-a",
        },
      });
      onFrame({
        cursor: 1,
        event: {
          type: "artifact",
          artifact_id: "artifact-a",
          name: "answer.txt",
          media_type: "text/plain",
          size: 42,
        },
      });
      onFrame({ cursor: 2, event: { type: "artifact_rejected", count: 2 } });
      onFrame({
        cursor: 3,
        event: { type: "event_unavailable", reason: "unsupported_event" },
      });
      return await new Promise(() => undefined);
    });

    render(
      <ChatView
        conversationId="conversation-a"
        onConversation={vi.fn()}
        onChanged={vi.fn()}
      />,
    );

    expect(await screen.findByText("answer.txt")).toBeTruthy();
    expect(screen.getByRole("alert").textContent).toContain(
      "2 generated outputs did not satisfy the artifact safety contract.",
    );
    expect(screen.getByRole("status").textContent).toContain(
      "Some internal runtime activity was withheld",
    );
    await waitFor(() => expect(api.artifacts).toHaveBeenCalledTimes(2));
  });

  it("shows the exact summary boundary used for the next model turn", async () => {
    api.conversation.mockResolvedValue({
      messages: [{
        id: "assistant-a",
        role: "assistant",
        content: "Durable answer.",
        created_at: "2026-01-01T00:00:00Z",
      }],
      active_run_id: null,
      model_context: {
        compacted: true,
        covered_count: 18,
        recent_exact_count: 6,
        up_to_message_id: "message-boundary",
        summary: "Earlier decisions, constraints, and open questions.",
      },
    });

    render(
      <ChatView
        conversationId="conversation-a"
        onConversation={vi.fn()}
        onChanged={vi.fn()}
      />,
    );

    expect(await screen.findByText(
      /Model context uses a summary of 18 earlier messages plus 6 recent messages verbatim/,
    )).toBeTruthy();
    fireEvent.click(screen.getByText(
      /Model context uses a summary of 18 earlier messages plus 6 recent messages verbatim/,
    ));
    expect(screen.getByText("Earlier decisions, constraints, and open questions."))
      .toBeTruthy();
    expect(screen.getByText("Durable answer.")).toBeTruthy();
  });

  it("keeps the composer open for a canonical same-surface steer", async () => {
    let finishFirst!: () => void;
    api.conversation.mockResolvedValue({ messages: [], active_run_id: null });
    api.streamChat
      .mockImplementationOnce(async (_body, onEvent) => {
        onEvent({
          type: "message_start",
          run_id: "run-a",
          conversation_id: "conversation-a",
        });
        await new Promise<void>((resolve) => {
          finishFirst = resolve;
        });
        onEvent({ type: "text_delta", delta: "Done." });
        onEvent({ type: "message_end", run_id: "run-a" });
      })
      .mockResolvedValueOnce({
        status: "queued",
        conversation_id: "conversation-a",
        message_id: "message-b",
        run_id: "run-a",
      });
    const onConversation = vi.fn();
    const view = render(
      <ChatView
        conversationId={null}
        onConversation={onConversation}
        onChanged={vi.fn()}
      />,
    );

    fireEvent.change(screen.getByLabelText("Task instructions"), {
      target: { value: "First task" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send ↑" }));
    await waitFor(() => expect(onConversation).toHaveBeenCalledWith("conversation-a"));
    view.rerender(
      <ChatView
        conversationId="conversation-a"
        onConversation={onConversation}
        onChanged={vi.fn()}
      />,
    );
    expect(await screen.findByRole("button", { name: "Queue next ↑" })).toBeTruthy();

    fireEvent.change(screen.getByLabelText("Task instructions"), {
      target: { value: "Also include the appendix" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Queue next ↑" }));
    await waitFor(() => expect(api.streamChat).toHaveBeenCalledTimes(2));
    expect(api.streamChat.mock.calls[1]?.[0]).toEqual(expect.objectContaining({
      conversation_id: "conversation-a",
      message: "Also include the appendix",
      origin: "worker",
    }));
    expect(await screen.findByText("Instruction queued behind the active turn.")).toBeTruthy();

    finishFirst();
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Send ↑" })).toBeTruthy();
    });
  });

  it("attaches a follow when a send is queued behind a turn with no local stream", async () => {
    api.conversation.mockResolvedValue({ messages: [], active_run_id: null });
    api.streamChat.mockResolvedValueOnce({
      status: "queued",
      conversation_id: "conversation-a",
      message_id: "message-b",
      run_id: "run-remote",
    });
    api.followConversation.mockResolvedValue({ status: "aborted", cursor: 0 });

    render(
      <ChatView
        conversationId="conversation-a"
        onConversation={vi.fn()}
        onChanged={vi.fn()}
      />,
    );
    fireEvent.change(await screen.findByLabelText("Task instructions"), {
      target: { value: "Steer from a streamless client" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send ↑" }));

    await waitFor(() => expect(api.followConversation).toHaveBeenCalledWith(
      "conversation-a",
      expect.any(Function),
      expect.objectContaining({ since: 0 }),
    ));
  });

  it("keeps a stale slower load from clobbering the selected conversation", async () => {
    let resolveB!: (value: unknown) => void;
    api.conversations.mockResolvedValue({
      conversations: [
        { id: "conversation-a", title: "Renewals", status: "active", updated_at: "2026-01-01T00:00:00Z" },
        { id: "conversation-b", title: "Filings", status: "active", updated_at: "2026-01-01T00:00:00Z" },
      ],
    });
    api.conversation.mockImplementation(async (id: string) => {
      if (id === "conversation-b") {
        return new Promise((resolve) => {
          resolveB = resolve;
        });
      }
      return {
        messages: [{
          id: "message-a",
          role: "user",
          content: "Renewals question",
        }],
        active_run_id: null,
      };
    });
    const props = { onConversation: vi.fn(), onChanged: vi.fn() };
    const view = render(<ChatView conversationId="conversation-a" {...props} />);
    expect(await screen.findByText("Renewals question")).toBeTruthy();

    view.rerender(<ChatView conversationId="conversation-b" {...props} />);
    view.rerender(<ChatView conversationId="conversation-a" {...props} />);
    expect(await screen.findByText("Renewals question")).toBeTruthy();

    resolveB({
      messages: [{
        id: "message-b",
        role: "user",
        content: "Filings question",
      }],
      active_run_id: "run-b",
    });
    await waitFor(() => expect(api.conversation).toHaveBeenCalledWith("conversation-b"));
    expect(screen.queryByText("Filings question")).toBeNull();
    expect(screen.getByText("Renewals question")).toBeTruthy();
    // The stale load must not attach a follow for the deselected conversation.
    expect(api.followConversation).not.toHaveBeenCalled();
  });

  it("offers cursor-preserving reconnect when live follow drops", async () => {
    api.conversation
      .mockResolvedValueOnce({ messages: [], active_run_id: "run-a" })
      .mockResolvedValue({ messages: [], active_run_id: null });
    api.followConversation
      .mockRejectedValueOnce(new Error("network down"))
      .mockImplementationOnce(async (_id, onFrame) => {
        onFrame({
          cursor: 4,
          event: {
            type: "message_start",
            run_id: "run-a",
            conversation_id: "conversation-a",
          },
        });
        return { status: "ended", cursor: 4 };
      });

    render(
      <ChatView
        conversationId="conversation-a"
        onConversation={vi.fn()}
        onChanged={vi.fn()}
      />,
    );
    fireEvent.click(await screen.findByRole("button", { name: "Reconnect" }));
    await waitFor(() => expect(api.followConversation).toHaveBeenCalledTimes(2));
    expect(api.followConversation.mock.calls[1]?.[2]).toEqual(expect.objectContaining({
      since: 0,
      signal: expect.any(AbortSignal),
    }));
  });

  it("keeps a closed deep link read-only until explicit restore", async () => {
    api.conversation.mockResolvedValue({ messages: [], active_run_id: null });
    api.conversations
      .mockResolvedValueOnce({
        conversations: [{
          id: "conversation-a",
          title: "Renewals",
          status: "closed",
          updated_at: "2026-01-01T00:00:00Z",
        }],
      })
      .mockResolvedValue({
        conversations: [{
          id: "conversation-a",
          title: "Renewals",
          status: "active",
          updated_at: "2026-01-01T00:00:00Z",
        }],
      });

    render(
      <ChatView
        conversationId="conversation-a"
        onConversation={vi.fn()}
        onChanged={vi.fn()}
      />,
    );

    const composer = screen.getByLabelText("Task instructions") as HTMLTextAreaElement;
    expect(composer.disabled).toBe(true);
    expect(await screen.findByText("Restore this conversation to continue it.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Restore conversation" }));
    await waitFor(() => expect(api.restoreMyConversation).toHaveBeenCalledWith("conversation-a"));
    await waitFor(() => expect(composer.disabled).toBe(false));
  });

  it("preflights exact attachment limits and restores a server-rejected draft", async () => {
    api.chatConfig.mockResolvedValue({
      attachments: {
        max_count: 1,
        max_bytes: 32,
        max_total_bytes: 32,
        model_readable_media_types: ["text/*"],
      },
    });
    api.streamChat.mockRejectedValue(
      new BoltrigApiError(413, { reason: "attachment_rejected" }),
    );
    const view = render(
      <ChatView
        conversationId={null}
        onConversation={vi.fn()}
        onChanged={vi.fn()}
      />,
    );
    await screen.findByText(/Text files are included in the model task/);
    const input = view.container.querySelector<HTMLInputElement>('input[type="file"]');
    expect(input).toBeTruthy();

    const first = new File(["notes"], "notes.txt", { type: "text/plain" });
    Object.defineProperty(input!, "files", { configurable: true, value: [first] });
    fireEvent.change(input!);
    expect(await screen.findByText(/notes.txt · model-readable/)).toBeTruthy();

    const second = new File(["more"], "more.txt", { type: "text/plain" });
    Object.defineProperty(input!, "files", { configurable: true, value: [second] });
    fireEvent.change(input!);
    expect(await screen.findByText("Attach at most 1 files to one turn.")).toBeTruthy();

    fireEvent.change(screen.getByLabelText("Task instructions"), {
      target: { value: "Use the attached notes" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send ↑" }));

    await screen.findByText(/server rejected the attachment limits/i);
    expect((screen.getByLabelText("Task instructions") as HTMLTextAreaElement).value)
      .toBe("Use the attached notes");
    expect(screen.getByText(/notes.txt · model-readable/)).toBeTruthy();
  });
});
