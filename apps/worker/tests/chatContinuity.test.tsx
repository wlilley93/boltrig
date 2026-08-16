// @vitest-environment happy-dom

import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { BoltrigApiError, type ChatEvent } from "@wlilley93/boltrig-web-sdk";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  chatModelChoices: vi.fn(),
  artifacts: vi.fn(),
  cancelRun: vi.fn(),
  chatConfig: vi.fn(),
  conversation: vi.fn(),
  conversations: vi.fn(),
  followConversation: vi.fn(),
  invokeApprovalState: vi.fn(),
  modelProfiles: vi.fn(),
  reorderConversationQueue: vi.fn(),
  respondHitl: vi.fn(),
  restoreMyConversation: vi.fn(),
  streamChat: vi.fn(),
}));

vi.mock("../src/client", () => ({ client: api }));

import { ChatView } from "../src/components/ChatView";

beforeEach(() => {
  api.chatModelChoices.mockResolvedValue({
    status: "ok",
    reason: null,
    choices: [],
    default_choice_id: "opaque-default-route",
    default_model_name: "openai/gpt-5.4",
    default_available: true,
  });
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
  api.invokeApprovalState.mockResolvedValue({ status: "pending" });
  api.respondHitl.mockResolvedValue({ status: "answered" });
  api.reorderConversationQueue.mockImplementation(async (_id, body) => ({
    status: "ok",
    message_ids: body.message_ids,
  }));
  api.restoreMyConversation.mockResolvedValue({
    status: "ok",
    id: "conversation-a",
    conversation_status: "active",
  });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.unstubAllGlobals();
});

describe("Worker chat continuity", () => {
  it("clears conversation-owned UI before a direct conversation switch settles", async () => {
    api.chatModelChoices.mockResolvedValue({
      status: "ok",
      reason: null,
      choices: [{
        id: "opaque-sonnet-route",
        model_name: "anthropic/claude-sonnet-4-5",
        available: true,
        is_default: false,
        modalities: ["text"],
      }],
      default_choice_id: "opaque-default-route",
      default_model_name: "openai/gpt-5.4",
      default_available: true,
    });
    api.chatConfig.mockResolvedValue({
      attachments: {
        max_count: 1,
        max_bytes: 262_144,
        max_total_bytes: 1_048_576,
        model_readable_media_types: ["text/*"],
      },
    });
    let resolveBeta!: (value: {
      messages: Array<{
        id: string;
        role: "assistant";
        content: string;
        created_at: string;
      }>;
      active_run_id: null;
    }) => void;
    const betaThread = new Promise<Parameters<typeof resolveBeta>[0]>((resolve) => {
      resolveBeta = resolve;
    });
    api.conversation.mockImplementation((id: string) => (
      id === "conversation-b"
        ? betaThread
        : Promise.resolve({
          messages: [{
            id: "assistant-a",
            role: "assistant",
            content: "Alpha answer",
            attachments: [{
              name: "alpha-source.txt",
              media_type: "text/plain",
              size: 5,
              data: btoa("alpha"),
            }],
            created_at: "2026-01-01T00:00:00Z",
          }],
          active_run_id: null,
        })
    ));
    api.artifacts.mockImplementation(({ conversationId }: { conversationId: string }) => (
      Promise.resolve(conversationId === "conversation-a" ? {
        artifacts: [{
          id: "artifact-a",
          name: "alpha-output.md",
          media_type: "text/markdown",
          revision: 1,
          size: 12,
        }],
        next_cursor: null,
      } : { artifacts: [], next_cursor: null })
    ));
    api.conversations.mockResolvedValue({
      conversations: [
        {
          id: "conversation-a",
          title: "Alpha task",
          status: "active",
          updated_at: "2026-01-01T00:00:00Z",
        },
        {
          id: "conversation-b",
          title: "Beta task",
          status: "active",
          updated_at: "2026-01-02T00:00:00Z",
        },
      ],
    });

    const view = render(
      <ChatView
        conversationId="conversation-a"
        onConversation={vi.fn()}
        onChanged={vi.fn()}
      />,
    );
    expect(await screen.findByText("Alpha answer")).toBeTruthy();
    expect(await screen.findByText("alpha-output.md")).toBeTruthy();
    expect(screen.getByText("alpha-source.txt")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Model" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Choose model" }));
    fireEvent.click(screen.getByRole("option", {
      name: "anthropic/claude-sonnet-4-5",
    }));
    expect(screen.getByRole("button", { name: "Model" }).textContent)
      .toContain("anthropic/claude-sonnet-4-5");

    fireEvent.change(screen.getByLabelText("Task instructions"), {
      target: { value: "Alpha draft" },
    });
    const fileInput = view.container.querySelector<HTMLInputElement>('input[type="file"]');
    const staged = new File(["staged"], "staged.txt", { type: "text/plain" });
    Object.defineProperty(fileInput!, "files", { configurable: true, value: [staged] });
    fireEvent.change(fileInput!);
    expect(await screen.findByText("staged.txt")).toBeTruthy();
    expect(screen.getByText("model-readable")).toBeTruthy();
    const rejected = new File(["second"], "second.txt", { type: "text/plain" });
    Object.defineProperty(fileInput!, "files", { configurable: true, value: [rejected] });
    fireEvent.change(fileInput!);
    expect(await screen.findByText("Attach at most 1 files to one turn.")).toBeTruthy();

    view.rerender(
      <ChatView
        conversationId="conversation-b"
        onConversation={vi.fn()}
        onChanged={vi.fn()}
      />,
    );

    expect(screen.getByRole("heading", { name: "Loading conversation…" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Model" }).textContent)
      .toContain("Automatic · openai/gpt-5.4");
    expect(screen.queryByRole("heading", { name: "What needs doing?" })).toBeNull();
    expect(screen.queryByText("Alpha answer")).toBeNull();
    expect(screen.queryByText("alpha-output.md")).toBeNull();
    expect(screen.queryByText("alpha-source.txt")).toBeNull();
    expect(screen.queryByText("staged.txt")).toBeNull();
    expect(screen.queryByText("Attach at most 1 files to one turn.")).toBeNull();
    expect((screen.getByLabelText("Task instructions") as HTMLTextAreaElement).value).toBe("");
    expect(document.querySelector(".right-rail")).toBeNull();

    resolveBeta({
      messages: [{
        id: "assistant-b",
        role: "assistant",
        content: "Beta answer",
        created_at: "2026-01-02T00:00:00Z",
      }],
      active_run_id: null,
    });
    expect(await screen.findByText("Beta answer")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Beta task" })).toBeTruthy();
    expect((screen.getByLabelText("Task instructions") as HTMLTextAreaElement).disabled)
      .toBe(false);
  });

  it("surfaces a retryable summary failure without showing New-chat content", async () => {
    api.conversation.mockResolvedValue({
      messages: [{
        id: "assistant-a",
        role: "assistant",
        content: "Recovered conversation",
        created_at: "2026-01-01T00:00:00Z",
      }],
      active_run_id: null,
    });
    api.conversations
      .mockRejectedValueOnce(new Error("summary offline"))
      .mockResolvedValueOnce({
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

    expect(await screen.findByText(/Could not load this conversation\. summary offline/))
      .toBeTruthy();
    expect(screen.getByRole("heading", { name: "Conversation unavailable" })).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "What needs doing?" })).toBeNull();
    expect(screen.queryByText("Recovered conversation")).toBeNull();
    const composer = screen.getByLabelText("Task instructions") as HTMLTextAreaElement;
    expect(composer.disabled).toBe(true);
    expect(composer.placeholder).toBe("Conversation unavailable — retry above");

    fireEvent.click(screen.getByRole("button", { name: "Retry conversation" }));
    expect(await screen.findByText("Recovered conversation")).toBeTruthy();
    await waitFor(() => expect(composer.disabled).toBe(false));
    expect(api.conversations).toHaveBeenCalledTimes(2);
  });

  it("clears the mobile follow-up draft when the conversation changes", async () => {
    stubPhoneViewport();
    api.conversation.mockImplementation((id: string) => Promise.resolve({
      messages: [{
        id: `assistant-${id}`,
        role: "assistant",
        content: id === "conversation-a" ? "Alpha mobile" : "Beta mobile",
        created_at: "2026-01-01T00:00:00Z",
      }],
      active_run_id: null,
    }));
    api.conversations.mockResolvedValue({
      conversations: [
        {
          id: "conversation-a",
          title: "Alpha task",
          status: "active",
          updated_at: "2026-01-01T00:00:00Z",
        },
        {
          id: "conversation-b",
          title: "Beta task",
          status: "active",
          updated_at: "2026-01-02T00:00:00Z",
        },
      ],
    });
    const view = render(
      <ChatView
        conversationId="conversation-a"
        onConversation={vi.fn()}
        onChanged={vi.fn()}
      />,
    );
    expect(await screen.findByText("Alpha mobile")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Follow up"), {
      target: { value: "Do not carry this" },
    });

    view.rerender(
      <ChatView
        conversationId="conversation-b"
        onConversation={vi.fn()}
        onChanged={vi.fn()}
      />,
    );
    expect((screen.getByLabelText("Follow up") as HTMLTextAreaElement).value).toBe("");
    expect(await screen.findByText("Beta mobile")).toBeTruthy();
  });

  it("preserves one draft and recaptures dialog focus across the phone breakpoint", async () => {
    const viewport = stubMutablePhoneViewport(false);
    api.conversation.mockResolvedValue({
      messages: [{
        id: "assistant-a",
        role: "assistant",
        content: "Breakpoint-safe conversation",
        created_at: "2026-01-01T00:00:00Z",
      }],
      active_run_id: null,
    });
    render(
      <ChatView
        conversationId="conversation-a"
        onConversation={vi.fn()}
        onChanged={vi.fn()}
      />,
    );
    expect(await screen.findByText("Breakpoint-safe conversation")).toBeTruthy();

    fireEvent.change(screen.getByLabelText("Task instructions"), {
      target: { value: "Keep this draft" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Task details" }));
    expect(screen.getByRole("complementary", { name: "Task details" })).toBeTruthy();
    expect(screen.queryByRole("dialog")).toBeNull();

    act(() => viewport.setPhone(true));
    const phoneDraft = await screen.findByLabelText("Follow up") as HTMLTextAreaElement;
    expect(phoneDraft.value).toBe("Keep this draft");
    await waitFor(() => {
      expect(document.activeElement).toBe(screen.getByRole("button", { name: "Close task details" }));
    });
    fireEvent.click(screen.getByRole("button", { name: "Close task details" }));
    fireEvent.change(phoneDraft, { target: { value: "Edited on phone" } });

    act(() => viewport.setPhone(false));
    expect((await screen.findByLabelText("Task instructions") as HTMLTextAreaElement).value)
      .toBe("Edited on phone");
  });

  it("resets phone-local disclosures when the selected conversation changes", async () => {
    stubPhoneViewport();
    api.conversations.mockResolvedValue({
      conversations: [
        { id: "conversation-a", title: "Alpha", status: "active", updated_at: "2026-01-01T00:00:00Z" },
        { id: "conversation-b", title: "Beta", status: "active", updated_at: "2026-01-02T00:00:00Z" },
      ],
    });
    api.conversation.mockImplementation(async (id: string) => ({
      messages: [{
        id: `assistant-${id}`,
        role: "assistant",
        content: id === "conversation-a" ? "Alpha result" : "Beta result",
        created_at: "2026-01-01T00:00:00Z",
        events: [
          { type: "tool_call", call_id: `call-${id}`, tool: "file.read" },
          { type: "tool_result", call_id: `call-${id}`, verb: "file.read", status: "ok" },
        ],
      }],
      active_run_id: null,
    }));
    const props = { onConversation: vi.fn(), onChanged: vi.fn() };
    const view = render(<ChatView conversationId="conversation-a" {...props} />);
    expect(await screen.findByText("Alpha result")).toBeTruthy();
    const alphaTools = screen.getByText("Read files").closest("summary");
    fireEvent.click(alphaTools!);
    expect(alphaTools!.closest("details")?.open).toBe(true);

    view.rerender(<ChatView conversationId="conversation-b" {...props} />);
    expect(await screen.findByText("Beta result")).toBeTruthy();
    expect(screen.getByText("Read files").closest("details")?.open).toBe(false);
  });

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

  it("keeps ended live text until durable reload and does not duplicate queued receipts on phone", async () => {
    stubPhoneViewport();
    api.conversation.mockResolvedValue({
      messages: [
        {
          id: "user-a",
          role: "user",
          content: "Initial request",
          run_id: "run-old",
          created_at: "2026-01-01T00:00:00Z",
        },
        {
          id: "assistant-a",
          role: "assistant",
          content: "Earlier answer",
          run_id: "run-old",
          created_at: "2026-01-01T00:00:01Z",
        },
        {
          id: "queued-a",
          role: "user",
          content: "Queued mobile steer",
          created_at: "2026-01-01T00:00:02Z",
        },
      ],
      active_run_id: "run-a",
    });
    api.followConversation.mockImplementation(async (_id, onFrame) => {
      onFrame({
        cursor: 1,
        event: {
          type: "message_start",
          run_id: "run-a",
          conversation_id: "conversation-a",
        },
      });
      onFrame({ cursor: 2, event: { type: "text_delta", delta: "Settled live answer." } });
      onFrame({
        cursor: 3,
        event: {
          type: "question",
          run_id: "run-a",
          question_id: "question-a",
          prompt: "Choose an owner",
          choices: ["Noether"],
        },
      });
      onFrame({ cursor: 4, event: { type: "message_end", run_id: "run-a" } });
      return await new Promise(() => undefined);
    });

    render(
      <ChatView
        conversationId="conversation-a"
        onConversation={vi.fn()}
        onChanged={vi.fn()}
      />,
    );

    expect(await screen.findByText("Settled live answer.")).toBeTruthy();
    expect(screen.getAllByText("Queued mobile steer")).toHaveLength(1);
    expect(screen.getByRole("region", { name: "Queued messages" })).toBeTruthy();
    expect(await screen.findByText("Choose an owner")).toBeTruthy();
    expect(screen.getByRole("textbox", { name: "Live question answer" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Noether" })).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Stop" }));
    await waitFor(() => expect(api.cancelRun).toHaveBeenCalledWith("run-a"));
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

  it("follows live transcript updates only while the reader stays near the bottom", async () => {
    let pushFrame!: (frame: {
      cursor: number;
      event: ChatEvent;
    }) => void;
    api.conversation.mockResolvedValue({
      messages: [{
        id: "assistant-a",
        role: "assistant",
        content: "Durable opening",
        created_at: "2026-01-01T00:00:00Z",
      }],
      active_run_id: "run-a",
    });
    api.followConversation.mockImplementation(async (_id, onFrame) => {
      pushFrame = onFrame;
      onFrame({
        cursor: 1,
        event: {
          type: "message_start",
          run_id: "run-a",
          conversation_id: "conversation-a",
        },
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
    expect(await screen.findByText("Durable opening")).toBeTruthy();
    await waitFor(() => expect(pushFrame).toBeTypeOf("function"));
    const transcript = screen.getByRole("region", { name: "Conversation transcript" });
    let scrollTop = 0;
    Object.defineProperty(transcript, "clientHeight", { configurable: true, value: 100 });
    Object.defineProperty(transcript, "scrollHeight", { configurable: true, value: 500 });
    Object.defineProperty(transcript, "scrollTop", {
      configurable: true,
      get: () => scrollTop,
      set: (value: number) => { scrollTop = value; },
    });

    fireEvent.scroll(transcript);
    act(() => pushFrame({
      cursor: 2,
      event: { type: "text_delta", delta: "First live update" },
    }));
    expect(scrollTop).toBe(0);
    expect(transcript.hasAttribute("aria-live")).toBe(false);
    expect(document.querySelector(".chat-live-announcement")?.textContent)
      .toBe("Response in progress.");

    scrollTop = 360;
    fireEvent.scroll(transcript);
    act(() => pushFrame({
      cursor: 3,
      event: { type: "text_delta", delta: " then another" },
    }));
    expect(scrollTop).toBe(500);
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
    expect(screen.getByText(/Some internal runtime activity was withheld/).textContent)
      .toContain("Some internal runtime activity was withheld");
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
    api.chatModelChoices.mockResolvedValue({
      status: "ok",
      reason: null,
      choices: [{
        id: "opaque-sonnet-route",
        model_name: "anthropic/claude-sonnet-4-5",
        available: true,
        is_default: false,
        modalities: ["text"],
      }],
      default_choice_id: "opaque-default-route",
      default_model_name: "openai/gpt-5.4",
      default_available: true,
    });
    api.conversation.mockResolvedValue({ messages: [], active_run_id: null });
    api.streamChat
      .mockImplementationOnce(async (_body, onEvent) => {
        onEvent({
          type: "message_start",
          run_id: "run-a",
          conversation_id: "conversation-a",
        });
        onEvent({
          type: "workflow_step",
          step_id: "audit",
          action: "Audit the task",
          status: "ok",
        });
        onEvent({
          type: "workflow_step",
          step_id: "draft",
          action: "Draft the appendix",
          status: "running",
        });
        onEvent({
          type: "workflow_step",
          step_id: "verify",
          action: "Verify the result",
          status: "paused",
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

    fireEvent.click(await screen.findByRole("button", { name: "Model" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Choose model" }));
    fireEvent.click(screen.getByRole("option", {
      name: "anthropic/claude-sonnet-4-5",
    }));

    fireEvent.change(screen.getByLabelText("Task instructions"), {
      target: { value: "First task" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send ↑" }));
    expect(api.streamChat.mock.calls[0]?.[0]).toEqual(expect.objectContaining({
      model_choice_id: "opaque-sonnet-route",
    }));
    await waitFor(() => expect(onConversation).toHaveBeenCalledWith("conversation-a"));
    view.rerender(
      <ChatView
        conversationId="conversation-a"
        onConversation={onConversation}
        onChanged={vi.fn()}
      />,
    );
    expect(screen.getByRole("button", { name: "Model" }).textContent)
      .toContain("anthropic/claude-sonnet-4-5");
    expect(await screen.findByRole("button", { name: "Queue next ↑" })).toBeTruthy();
    expect(screen.getByText("Step 2 / 3")).toBeTruthy();

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
    expect(api.streamChat.mock.calls[1]?.[0]).not.toHaveProperty("model_choice_id");
    const steer = await screen.findByRole("button", {
      name: "Steer queued message: Also include the appendix",
    });
    expect(steer).toBeTruthy();
    fireEvent.click(steer);
    expect((screen.getByLabelText("Task instructions") as HTMLTextAreaElement).value)
      .toBe("Also include the appendix");

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

  it("persists a queued-turn reorder and paints the accepted execution order", async () => {
    api.conversation.mockResolvedValue({
      messages: [
        {
          id: "direct",
          role: "user",
          content: "Initial turn",
          run_id: "run-a",
          created_at: "2026-01-01T00:00:00Z",
        },
        {
          id: "answer",
          role: "assistant",
          content: "Working",
          run_id: "run-a",
          created_at: "2026-01-01T00:00:01Z",
        },
        {
          id: "queued-first",
          role: "user",
          content: "First queued turn",
          created_at: "2026-01-01T00:00:02Z",
        },
        {
          id: "queued-second",
          role: "user",
          content: "Second queued turn",
          created_at: "2026-01-01T00:00:03Z",
        },
      ],
      active_run_id: null,
      queued_message_ids: ["queued-first", "queued-second"],
    });

    render(
      <ChatView
        conversationId="conversation-a"
        onConversation={vi.fn()}
        onChanged={vi.fn()}
      />,
    );
    const handle = await screen.findByRole("button", {
      name: "Reorder queued message: First queued turn",
    });
    fireEvent.keyDown(handle, { key: "ArrowDown" });

    await waitFor(() => expect(api.reorderConversationQueue).toHaveBeenCalledWith(
      "conversation-a",
      {
        expected_message_ids: ["queued-first", "queued-second"],
        message_ids: ["queued-second", "queued-first"],
      },
    ));
    await waitFor(() => {
      const ids = [...document.querySelectorAll(".queued-message")]
        .map((row) => row.getAttribute("data-message-id"));
      expect(ids).toEqual(["queued-second", "queued-first"]);
    });
    expect(screen.getByText("Queue order updated.")).toBeTruthy();
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

  it("keeps conversation B live when an aborted conversation A send settles late", async () => {
    let settleConversationAStream!: () => void;
    api.conversations.mockResolvedValue({
      conversations: [
        { id: "conversation-a", title: "Renewals", status: "active", updated_at: "2026-01-01T00:00:00Z" },
        { id: "conversation-b", title: "Filings", status: "active", updated_at: "2026-01-02T00:00:00Z" },
      ],
    });
    api.conversation.mockImplementation(async (id: string) => ({
      messages: [],
      active_run_id: id === "conversation-b" ? "run-b" : null,
    }));
    // Deliberately model the SDK's abort contract: once an SSE has emitted a
    // frame, abort resolves streamChat with `undefined`. Conversation A settles
    // only after B's follow is visibly live, exercising the post-await owner
    // checks rather than merely the synchronous route reset.
    api.streamChat.mockImplementationOnce(async (_body, onEvent) => {
      onEvent({
        type: "message_start",
        run_id: "run-a",
        conversation_id: "conversation-a",
      });
      await new Promise<void>((resolve) => {
        settleConversationAStream = resolve;
      });
    });
    api.followConversation.mockImplementation(async (
      id: string,
      onFrame: (frame: { cursor: number; event: ChatEvent }) => void,
      options: { signal?: AbortSignal },
    ) => {
      expect(id).toBe("conversation-b");
      onFrame({
        cursor: 1,
        event: {
          type: "message_start",
          run_id: "run-b",
          conversation_id: "conversation-b",
        },
      });
      onFrame({
        cursor: 2,
        event: { type: "text_delta", delta: "B is still working" },
      });
      return await new Promise<{ status: "aborted"; cursor: number }>((resolve) => {
        options.signal?.addEventListener("abort", () => {
          resolve({ status: "aborted", cursor: 2 });
        }, { once: true });
      });
    });

    const props = {
      onConversation: vi.fn(),
      onChanged: vi.fn(),
      onWorkingChange: vi.fn(),
    };
    const view = render(<ChatView conversationId="conversation-a" {...props} />);
    fireEvent.change(await screen.findByLabelText("Task instructions"), {
      target: { value: "Start A" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send ↑" }));
    expect(await screen.findByText("Working…")).toBeTruthy();

    view.rerender(<ChatView conversationId="conversation-b" {...props} />);
    expect(await screen.findByText("B is still working")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Queue next ↑" })).toBeTruthy();

    await act(async () => {
      settleConversationAStream();
      await new Promise((resolve) => window.setTimeout(resolve, 0));
    });

    expect(screen.getByText("B is still working")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "■ Stop" }));
    await waitFor(() => expect(api.cancelRun).toHaveBeenCalledWith("run-b"));
    expect(api.cancelRun).not.toHaveBeenCalledWith("run-a");
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

  it("keeps a closed deep link read-only without rail mutation controls", async () => {
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
    expect(screen.queryByRole("button", { name: "Restore conversation" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Create output" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Create a file or site" })).toBeNull();
    expect(screen.getByText("No outputs")).toBeTruthy();
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
    expect(screen.queryByText(/Text files are included in the model task/)).toBeNull();
    const input = view.container.querySelector<HTMLInputElement>('input[type="file"]');
    expect(input).toBeTruthy();

    const first = new File(["notes"], "notes.txt", { type: "text/plain" });
    Object.defineProperty(input!, "files", { configurable: true, value: [first] });
    fireEvent.change(input!);
    expect(await screen.findByText("notes.txt")).toBeTruthy();

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
    expect(screen.getByText("notes.txt")).toBeTruthy();
  });

  it("restores a phone draft when the server rejects the turn", async () => {
    stubPhoneViewport();
    api.streamChat.mockRejectedValue(
      new BoltrigApiError(413, { reason: "turn_rejected" }),
    );
    render(
      <ChatView
        conversationId={null}
        onConversation={vi.fn()}
        onChanged={vi.fn()}
      />,
    );
    await waitFor(() => expect(api.chatModelChoices).toHaveBeenCalledOnce());

    const input = screen.getByLabelText("Follow up") as HTMLTextAreaElement;
    fireEvent.change(input, { target: { value: "Keep this phone draft" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    expect(await screen.findByText(/server rejected the attachment limits/i)).toBeTruthy();
    expect(input.value).toBe("Keep this phone draft");
  });
});

function stubPhoneViewport() {
  vi.stubGlobal("matchMedia", vi.fn().mockImplementation((query: string) => ({
    matches: query === "(max-width: 1374px)" || query === "(max-width: 640px)",
    media: query,
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })));
}

function stubMutablePhoneViewport(initialPhone: boolean) {
  const phoneListeners = new Set<(event: MediaQueryListEvent) => void>();
  const phoneMedia = {
    matches: initialPhone,
    media: "(max-width: 640px)",
    onchange: null,
    addEventListener: (_type: string, listener: (event: MediaQueryListEvent) => void) => {
      phoneListeners.add(listener);
    },
    removeEventListener: (_type: string, listener: (event: MediaQueryListEvent) => void) => {
      phoneListeners.delete(listener);
    },
    dispatchEvent: vi.fn(),
  };
  const compactMedia = {
    matches: true,
    media: "(max-width: 1374px)",
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  };
  vi.stubGlobal("matchMedia", vi.fn().mockImplementation((query: string) => (
    query === "(max-width: 640px)" ? phoneMedia : compactMedia
  )));
  return {
    setPhone(matches: boolean) {
      phoneMedia.matches = matches;
      for (const listener of phoneListeners) {
        listener({ matches, media: phoneMedia.media } as MediaQueryListEvent);
      }
    },
  };
}
