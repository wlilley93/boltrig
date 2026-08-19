// @vitest-environment happy-dom

import { act, cleanup, createEvent, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useEffect, useState } from "react";

const api = vi.hoisted(() => ({
  approvalPosture: vi.fn(),
  artifacts: vi.fn(),
  chatConfig: vi.fn(),
  chatModelChoices: vi.fn(),
  conversation: vi.fn(),
  conversations: vi.fn(),
  createCall: vi.fn(),
  invokeApprovalState: vi.fn(),
  modelProfiles: vi.fn(),
  putApprovalPosture: vi.fn(),
  respondHitl: vi.fn(),
  runEvents: vi.fn(),
  streamChat: vi.fn(),
}));
const replySpeech = vi.hoisted(() => ({
  prime: vi.fn(),
  readReply: vi.fn().mockResolvedValue(undefined),
  stop: vi.fn(),
}));

vi.mock("../src/client", () => ({ client: api }));
vi.mock("../src/components/chat/useReplySpeech", () => ({
  useLiveReplySpeech: ({ callActive, live }: {
    callActive: boolean;
    live: { cancelled: boolean; ended: boolean; runId?: string; text: string };
  }) => {
    useEffect(() => {
      if (!live.runId || !live.ended || live.cancelled || !live.text.trim()) return;
      void replySpeech.readReply(live.runId, live.text);
    }, [live.cancelled, live.ended, live.runId, live.text]);
    useEffect(() => { if (callActive) replySpeech.stop(); }, [callActive]);
    return replySpeech.prime;
  },
  useReplySpeech: () => ({
    enabled: true,
    loaded: true,
    provider: "pocket-voice",
    ...replySpeech,
  }),
}));
// A stub call control: placement rule 3 is about where the Stage sits for the
// life of a call, not about realtime media, so the stub only raises the
// call-active signal the way the real control does. It keeps the real idle
// markup shape (.voice-idle > .primary-button) because the empty-draft
// primary starts the call through that button.
vi.mock("../src/components/VoiceCall", () => ({
  VoiceCall: ({ onCallActive }: { onCallActive?(active: boolean): void }) => (
    <div className="voice-idle">
      <button
        aria-label="Talk to the chief of staff"
        className="primary-button"
        onClick={() => onCallActive?.(true)}
        type="button"
      >Start test call</button>
    </div>
  ),
}));

import { ChatView } from "../src/components/ChatView";
import { CommandPalette } from "../src/components/CommandPalette";
import {
  CHAT_QUEUE_DRAG_TYPE,
  LONG_TEXT_ATTACHMENT_THRESHOLD,
} from "../src/components/chat/ComposerAttachments";

function attachmentFile(name: string, text: string): File {
  return {
    name,
    size: new TextEncoder().encode(text).byteLength,
    type: "text/plain",
    arrayBuffer: vi.fn().mockResolvedValue(new TextEncoder().encode(text).buffer),
  } as unknown as File;
}

function transfer({
  files = [],
  text = "",
  types = files.length ? ["Files"] : ["text/plain"],
}: {
  files?: File[];
  text?: string;
  types?: string[];
}): DataTransfer {
  return {
    dropEffect: "none",
    files,
    getData: (type: string) => type === "text/plain" ? text : "",
    types,
  } as unknown as DataTransfer;
}

beforeEach(() => {
  document.documentElement.dataset.theme = "dark";
  stubChatViewport(false, false);
  api.artifacts.mockResolvedValue({ artifacts: [], next_cursor: null });
  api.approvalPosture.mockResolvedValue({
    posture: "risk_based",
    source: "safe_default",
    enforcement: {
      applies_to: "delegated_agent_adapter_calls",
      workspace_blocking_verbs_remain: true,
      control_plane_approvals_remain: true,
      direct_human_consequence_gate_remains: true,
      authority_is_never_widened: true,
    },
  });
  api.chatConfig.mockResolvedValue({
    attachments: {
      max_count: 8,
      max_bytes: 262_144,
      max_total_bytes: 1_048_576,
      model_readable_media_types: ["text/*"],
    },
  });
  api.chatModelChoices.mockResolvedValue({
    status: "ok",
    reason: null,
    choices: [],
    default_choice_id: "opaque-default-route",
    default_model_name: "openai/gpt-5.4",
    default_available: true,
  });
  api.invokeApprovalState.mockResolvedValue({ status: "consumed" });
  api.respondHitl.mockResolvedValue({ status: "ok" });
  api.conversations.mockResolvedValue({
    conversations: [{
      id: "conversation-a",
      title: "Renewal outreach",
      status: "active",
      updated_at: "2026-01-01T00:00:00Z",
    }],
  });
  api.modelProfiles.mockResolvedValue({ profiles: [] });
  api.runEvents.mockResolvedValue([]);
  replySpeech.prime.mockReset();
  replySpeech.readReply.mockReset().mockResolvedValue(undefined);
  replySpeech.stop.mockReset();
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.unstubAllGlobals();
  delete document.documentElement.dataset.theme;
  try {
    localStorage.removeItem("boltrig-worker-theme");
    localStorage.removeItem("boltrig-worker-voice-banner-dismissed");
  } catch {
    // Storage is optional in this environment.
  }
});

function renderChat(conversationId: string | null) {
  render(
    <ChatView
      conversationId={conversationId}
      onConversation={vi.fn()}
      onChanged={vi.fn()}
    />,
  );
}

function renderChatWithCommands(conversationId: string | null, onCommandPalette: () => void) {
  render(
    <ChatView
      conversationId={conversationId}
      onCommandPalette={onCommandPalette}
      onConversation={vi.fn()}
      onChanged={vi.fn()}
    />,
  );
}

function stubChatViewport(initialCompact: boolean, initialPhone: boolean) {
  const listeners = new Map<string, Set<(event: MediaQueryListEvent) => void>>();
  const matches = new Map<string, boolean>([
    ["(max-width: 1374px)", initialCompact],
    ["(max-width: 640px)", initialPhone],
  ]);
  const media = new Map<string, MediaQueryList>();
  vi.stubGlobal("matchMedia", vi.fn().mockImplementation((query: string) => {
    if (!media.has(query)) {
      const queryListeners = new Set<(event: MediaQueryListEvent) => void>();
      listeners.set(query, queryListeners);
      media.set(query, {
        get matches() { return matches.get(query) ?? false; },
        media: query,
        onchange: null,
        addEventListener: (_type: string, listener: EventListenerOrEventListenerObject) => queryListeners.add(
          listener as (event: MediaQueryListEvent) => void,
        ),
        removeEventListener: (_type: string, listener: EventListenerOrEventListenerObject) => queryListeners.delete(
          listener as (event: MediaQueryListEvent) => void,
        ),
        addListener: () => undefined,
        removeListener: () => undefined,
        dispatchEvent: vi.fn(),
      });
    }
    return media.get(query)!;
  }));
  return {
    setCompact(next: boolean) {
      matches.set("(max-width: 1374px)", next);
      const event = { matches: next, media: "(max-width: 1374px)" } as MediaQueryListEvent;
      listeners.get(event.media)?.forEach((listener) => listener(event));
    },
  };
}

describe("console chat surface", () => {
  it("greets a fresh chat the way the decided target does, chrome-free", async () => {
    renderChat(null);

    // New tasks open on one question and the real prompt controls, without
    // suggested openers competing with slash and command discovery.
    // It does NOT open on the Stage at hero size: ADR 0025 placement rule 1 is
    // superseded here by the target, and the unbounded square it put in the
    // welcome was what pushed the composer off a short window.
    expect(screen.getByRole("heading", { level: 1, name: "What needs doing?" }))
      .toBeTruthy();
    expect(document.querySelector(".welcome .starters")).toBeNull();
    expect(document.querySelector(".welcome .starter-card")).toBeNull();
    await waitFor(() => {
      expect(document.querySelector(".welcome > .familiar-stage")).toBeNull();
      expect(document.querySelector(".welcome .familiar-stage.hero")).toBeNull();
    });
    // The New state draws no header bar at all (so no familiar or settings
    // control can sit in one). Theme remains available from Settings.
    expect(document.querySelector(".chat-header")).toBeNull();
    expect(screen.queryByRole("button", { name: "Toggle theme" })).toBeNull();

    // At 30px the canonical ladder uses its glossy Stage, not the flat badge.
    // No chief genotype exists in this route's contract, so the renderer must
    // state that absence instead of borrowing a child identity.
    // The NAME is the identity alone: the state moved to a live region beside
    // the body, because an aria-label changing on a role="img" is not announced.
    const voiceFamiliar = screen.getByRole("img", {
      name: "chief of staff Familiar",
    });
    expect(voiceFamiliar.classList.contains("familiar-stage")).toBeTruthy();
    expect(voiceFamiliar.classList.contains("conversation")).toBeTruthy();
    expect(voiceFamiliar.getAttribute("data-genotype-source")).toBe("unbound");
    const voiceIntro = voiceFamiliar.closest(".voice-intro");
    const promptStack = voiceIntro?.closest(".new-chat-prompt-stack");
    expect(voiceIntro).toBeTruthy();
    expect(promptStack).toBeTruthy();
    expect(promptStack?.firstElementChild).toBe(voiceIntro);
    expect(promptStack?.lastElementChild?.classList.contains("composer")).toBe(true);
    const newComposer = promptStack?.lastElementChild;
    expect(newComposer?.firstElementChild?.classList.contains("composer-context")).toBe(true);
    expect(newComposer?.lastElementChild?.classList.contains("composer-frame")).toBe(true);
    expect(screen.getByRole("button", { name: "Start voice chat" })).toBeTruthy();
    expect(screen.getByText("Talk to Familiar")).toBeTruthy();

    // Composer action glyphs share one legible Codex-weight stroke family.
    // Dictation remains explicitly unavailable even though its icon no longer
    // fades into the canvas.
    const addAction = screen.getByRole("button", { name: "Add" });
    const dictateAction = screen.getByRole("button", { name: "Dictation unavailable" });
    expect(addAction.querySelector("svg")?.getAttribute("stroke-width")).toBe("2.2");
    expect(dictateAction.querySelector("svg")?.getAttribute("stroke-width")).toBe("2.2");
    expect(dictateAction.getAttribute("aria-disabled")).toBe("true");
  });

  it("opens existing command and skill discovery from slash without inventing a project picker", () => {
    const onCommandPalette = vi.fn();
    renderChatWithCommands(null, onCommandPalette);

    const composer = screen.getByRole("textbox", { name: "Task instructions" });
    fireEvent.keyDown(composer, { key: "/" });

    expect(onCommandPalette).toHaveBeenCalledOnce();
    expect((composer as HTMLTextAreaElement).value).toBe("");
    expect(screen.queryByText("No project selected")).toBeNull();
    expect(screen.queryByTitle("Project selection is not available in this client"))
      .toBeNull();
  });

  it("lights the composer for external drags and stages a window drop", async () => {
    renderChat(null);
    const textarea = screen.getByRole("textbox", { name: "Task instructions" }) as HTMLTextAreaElement;
    await waitFor(() => expect(textarea.disabled).toBe(false));
    const composer = textarea.closest(".composer")!;
    const dataTransfer = transfer({ files: [attachmentFile("brief.txt", "Attach this brief")] });

    fireEvent.dragEnter(window, { dataTransfer });
    expect(composer.getAttribute("data-drop-active")).toBe("true");
    expect(screen.getByRole("status").textContent).toContain("Drop to attach");
    expect(screen.getByRole("status").textContent).toContain("Files, media, or text");

    fireEvent.drop(window, { dataTransfer });
    expect(composer.getAttribute("data-drop-active")).toBeNull();
    expect(await screen.findByText("brief.txt")).toBeTruthy();

    fireEvent.dragEnter(window, {
      dataTransfer: transfer({ text: "queued-message", types: [CHAT_QUEUE_DRAG_TYPE, "text/plain"] }),
    });
    expect(composer.getAttribute("data-drop-active")).toBeNull();

    const textTransfer = transfer({ text: "A dragged excerpt keeps its surrounding whitespace.\n" });
    fireEvent.dragEnter(window, { dataTransfer: textTransfer });
    expect(composer.getAttribute("data-drop-active")).toBe("true");
    fireEvent.drop(window, { dataTransfer: textTransfer });
    expect(await screen.findByText("dropped-text.txt")).toBeTruthy();

    const oversized = {
      name: "oversized.bin",
      size: 262_145,
      type: "application/octet-stream",
      arrayBuffer: vi.fn(),
    } as unknown as File;
    const oversizedTransfer = transfer({ files: [oversized] });
    fireEvent.dragEnter(window, { dataTransfer: oversizedTransfer });
    fireEvent.drop(window, { dataTransfer: oversizedTransfer });
    expect((await screen.findByRole("alert")).textContent).toBe(
      "oversized.bin is too large. Each file must be 256 KB or smaller.",
    );
    expect(screen.queryByText("oversized.bin")).toBeNull();
  });

  it("stages long pasted text as a readable attachment without replacing the draft", async () => {
    renderChat(null);
    const textarea = screen.getByRole("textbox", { name: "Task instructions" }) as HTMLTextAreaElement;
    await waitFor(() => expect(textarea.disabled).toBe(false));
    fireEvent.change(textarea, { target: { value: "Summarise the attached excerpt" } });
    const longText = `Header\n${"A substantial pasted excerpt. ".repeat(100)}`
      .slice(0, LONG_TEXT_ATTACHMENT_THRESHOLD + 200);
    const longPaste = createEvent.paste(textarea, {
      clipboardData: transfer({ text: longText }),
    });

    fireEvent(textarea, longPaste);
    expect(longPaste.defaultPrevented).toBe(true);
    expect(textarea.value).toBe("Summarise the attached excerpt");
    expect(await screen.findByText("pasted-text.txt")).toBeTruthy();

    const shortPaste = createEvent.paste(textarea, {
      clipboardData: transfer({ text: "short excerpt" }),
    });
    fireEvent(textarea, shortPaste);
    expect(shortPaste.defaultPrevented).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: "Send ↑" }));
    await waitFor(() => expect(api.streamChat).toHaveBeenCalledOnce());
    const request = api.streamChat.mock.calls[0]![0];
    expect(request.attachments).toHaveLength(1);
    expect(request.attachments[0]).toMatchObject({
      name: "pasted-text.txt",
      media_type: "text/plain",
    });
    expect(atob(request.attachments[0].data)).toBe(longText);
  });

  it("restores the empty composer after dismissing slash-opened commands", async () => {
    function Harness() {
      const [commandsOpen, setCommandsOpen] = useState(false);
      return (
        <>
          <ChatView
            conversationId={null}
            onChanged={vi.fn()}
            onCommandPalette={() => setCommandsOpen(true)}
            onConversation={vi.fn()}
          />
          <CommandPalette
            open={commandsOpen}
            onClose={() => setCommandsOpen(false)}
            onNavigate={vi.fn()}
          />
        </>
      );
    }

    render(<Harness />);
    const composer = screen.getByRole("textbox", { name: "Task instructions" });
    composer.focus();
    fireEvent.keyDown(composer, { key: "/" });

    const search = await screen.findByRole("combobox", { name: "Search Worker" });
    expect(document.activeElement).toBe(search);
    fireEvent.keyDown(search, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog", {
      name: "Worker commands",
    })).toBeNull());
    expect(document.activeElement).toBe(composer);
  });

  it("labels exact chat models and sends only the opaque text-model choice", async () => {
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
    });
    api.streamChat.mockResolvedValue(undefined);
    renderChat(null);

    const model = await screen.findByRole("button", { name: "Model" });
    expect(model.textContent).toContain("Automatic · openai/gpt-5.4");
    fireEvent.click(model);
    fireEvent.click(screen.getByRole("menuitem", { name: "Choose model" }));
    fireEvent.click(screen.getByRole("option", {
      name: "anthropic/claude-sonnet-4-5",
    }));
    fireEvent.change(screen.getByRole("textbox", { name: "Task instructions" }), {
      target: { value: "Use the selected model" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send ↑" }));

    await waitFor(() => expect(api.streamChat).toHaveBeenCalledOnce());
    const request = api.streamChat.mock.calls[0]![0];
    expect(request.model_choice_id).toBe("opaque-sonnet-route");
    expect(request).not.toHaveProperty("model_profile_id");
  });

  it("primes audio on submit and reads a newly completed reply once", async () => {
    api.conversation.mockResolvedValue({
      messages: [{ id: "assistant-a", role: "assistant", content: "Finished reply" }],
      active_run_id: null,
    });
    api.streamChat.mockImplementation(async (_request, onEvent) => {
      onEvent({ type: "message_start", run_id: "run-spoken", conversation_id: "conversation-spoken" });
      onEvent({ type: "text_delta", run_id: "run-spoken", delta: "Finished reply" });
      onEvent({ type: "message_end", run_id: "run-spoken" });
      await new Promise((resolve) => window.setTimeout(resolve, 0));
      return undefined;
    });
    renderChat(null);

    await screen.findByRole("button", { name: "Model" });
    fireEvent.change(screen.getByRole("textbox", { name: "Task instructions" }), {
      target: { value: "Say the result" },
    });
    const send = screen.getByRole("button", { name: "Send ↑" }) as HTMLButtonElement;
    await waitFor(() => expect(send.disabled).toBe(false));
    fireEvent.click(send);

    expect(replySpeech.prime).toHaveBeenCalledOnce();
    await waitFor(() => expect(replySpeech.readReply).toHaveBeenCalledWith(
      "run-spoken",
      "Finished reply",
    ));
    expect(replySpeech.readReply).toHaveBeenCalledTimes(1);
  });

  it("fails closed when the selected automatic model is unavailable", async () => {
    api.chatModelChoices.mockResolvedValue({
      choices: [{
        id: "opaque-sonnet-route",
        model_name: "anthropic/claude-sonnet-4-5",
        available: true,
        is_default: false,
        modalities: ["text"],
      }],
      default_choice_id: null,
      default_model_name: "openai/gpt-5.4",
      default_available: false,
      default_unavailable_reason: "model_gateway_unavailable",
      status: "unavailable",
      reason: "model_gateway_unavailable",
    });
    renderChat(null);

    expect((await screen.findByRole("button", { name: "Model" })).textContent)
      .toContain("Automatic · openai/gpt-5.4Unavailable");
    fireEvent.change(screen.getByRole("textbox", { name: "Task instructions" }), {
      target: { value: "Do not submit this to an unavailable route" },
    });
    const send = screen.getByRole("button", { name: "Send ↑" }) as HTMLButtonElement;
    expect(send.disabled).toBe(true);
    expect(send.title).toBe("The model gateway is unavailable.");
    fireEvent.click(send);
    expect(api.streamChat).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Model" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Choose model" }));
    const automaticOption = screen.getAllByRole("option")[0]!;
    expect(within(automaticOption).getByText("Unavailable").title)
      .toBe("The model gateway is unavailable.");
    fireEvent.click(screen.getByRole("option", {
      name: "anthropic/claude-sonnet-4-5",
    }));
    expect(send.disabled).toBe(false);
    fireEvent.click(send);
    await waitFor(() => expect(api.streamChat).toHaveBeenCalledOnce());
    expect(api.streamChat.mock.calls[0]![0].model_choice_id)
      .toBe("opaque-sonnet-route");
  });

  it("keeps voice start in the round composer control", () => {
    renderChat(null);

    expect(screen.queryByText("Try boltrig Voice")).toBeNull();
    expect(screen.getByRole("button", { name: "Start a voice call" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Talk to the chief of staff" }))
      .toBeNull();
    expect(screen.queryAllByRole("button", {
      name: /Start a voice call|Talk to the chief of staff/,
    })).toHaveLength(1);
    const mountedController = document.querySelector<HTMLElement>(
      ".composer-voice-controller",
    );
    expect(mountedController?.hidden).toBe(true);
    expect(mountedController?.querySelector(".voice-idle > button.primary-button"))
      .toBeTruthy();
    expect(screen.queryByText("Call options")).toBeNull();
  });

  it("shows voice and send as distinct controls once the draft has text", () => {
    renderChat(null);

    fireEvent.change(screen.getByRole("textbox", { name: "Task instructions" }), {
      target: { value: "draft text" },
    });

    expect(screen.queryByRole("button", { name: "Start a voice call" })).toBeNull();
    expect(screen.getByRole("button", { name: "Talk to the chief of staff" }))
      .toBeTruthy();
    expect(screen.getByRole("button", { name: "Send ↑" })).toBeTruthy();
  });

  it("turns the empty-draft primary into a voice call, and says so", async () => {
    renderChat(null);

    // Empty draft: the primary is the round voice control, with no explanatory footer.
    expect(screen.queryByText("Nothing typed, so the round button starts a voice call."))
      .toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Start a voice call" }));

    // The click reaches VoiceCall's own start control, so the call machinery
    // (capability fallbacks, media teardown) stays in one place.
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "New chat" })).toBeTruthy();
    });
    expect(document.querySelector(".voice-stage")).toBeNull();

    // A non-empty draft flips the primary back to Send.
    fireEvent.change(screen.getByRole("textbox", { name: "Task instructions" }), {
      target: { value: "draft text" },
    });
    expect(screen.queryByRole("button", { name: "Start a voice call" })).toBeNull();
    expect(screen.getByRole("button", { name: "Send ↑" })).toBeTruthy();
  });

  it("keeps voice reachable from the composer, not the title row", async () => {
    api.conversation.mockResolvedValue({ messages: [], active_run_id: null });
    renderChat("conversation-a");
    // Voice moved out of the header, but it must stay reachable in an ACTIVE
    // conversation too, so it lives with the composer tools rather than in a
    // banner that only the empty state renders.
    await waitFor(() => {
      expect(document.querySelector(".composer-tools")).toBeTruthy();
    });
    expect(document.querySelector(".composer.conversation-context:not(.closed)"))
      .toBeTruthy();
    expect(await screen.findByRole("button", { name: "Approve for me" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Add" }).querySelector("svg"))
      .toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    expect(screen.getByRole("dialog", { name: "Add to task" })).toBeTruthy();
    expect(screen.getByRole("button", { name: /Files/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: /Record a skill/ })).toBeTruthy();
    expect(document.querySelector(".chat-header-actions .voice-call")).toBeNull();
  });

  it("does not attribute a main response to its first child subagent", async () => {
    api.conversation.mockResolvedValue({
      messages: [
        { id: "m1", role: "user", content: "First ask" },
        { id: "m2", role: "assistant", content: "Older answer" },
        { id: "m3", role: "user", content: "Second ask" },
        {
          id: "m4",
          role: "assistant",
          content: "Newest answer",
          events: [{
            type: "subagent",
            child_run_id: "child-lyell",
            task: "Read account health",
            name: "Lyell",
          }],
        },
      ],
      active_run_id: null,
    });
    renderChat("conversation-a");

    const answer = await screen.findByText("Newest answer");
    const article = answer.closest("article.message.assistant");
    expect(article?.querySelector(".message-author")).toBeNull();
    expect(article?.querySelector(".subagent-chip")?.textContent).toContain("Lyell");
    expect(article?.querySelector(".subagent-fanout")).toBeNull();
    expect(article?.querySelectorAll(".transcript-subagent-chip")).toHaveLength(1);
    expect(article?.querySelector(".familiar-stage")).toBeNull();
    expect(document.querySelectorAll("article.message.assistant .message-author").length)
      .toBe(0);
    expect(document.querySelector(".chat-header .familiar-stage")).toBeNull();
  });

  it("does not leave a second character Stage behind the voice modal", async () => {
    api.conversation.mockResolvedValue({
      messages: [
        { id: "m1", role: "user", content: "First ask" },
        { id: "m2", role: "assistant", content: "Newest answer" },
      ],
      active_run_id: null,
    });
    renderChat("conversation-a");
    await screen.findByText("Newest answer");

    fireEvent.click(screen.getByRole("button", { name: "Start a voice call" }));

    // VoiceCall's portal owns the one full-resolution Stage. This mocked
    // controller intentionally supplies no modal, so ChatView must leave no
    // duplicate WebGL Stage running invisibly behind it.
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Renewal outreach" })).toBeTruthy();
    });
    expect(document.querySelector(".voice-stage")).toBeNull();
    expect(document.querySelectorAll(".familiar-stage")).toHaveLength(0);
    const newest = [...document.querySelectorAll("article.message.assistant")]
      .find((article) => article.textContent?.includes("Newest answer"));
    expect(newest?.querySelector(".message-author")).toBeNull();
    expect(newest?.querySelector(".familiar-stage")).toBeNull();
  });

  it("keeps the one task-details trigger mounted on the phone surface", async () => {
    // The trigger sits above the mobile/console swap so a breakpoint flip
    // never detaches it mid-measure; on the phone it must coexist with the
    // MobileChat surface and still control the sheet.
    vi.stubGlobal("matchMedia", vi.fn().mockImplementation((query: string) => ({
      matches: query === "(max-width: 1374px)" || query === "(max-width: 640px)",
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })));
    api.conversation.mockResolvedValue({
      messages: [{
        id: "assistant-a",
        role: "assistant",
        content: "Current answer",
        created_at: "2026-01-01T00:00:00Z",
      }],
      active_run_id: null,
    });
    try {
      renderChat("conversation-a");
      expect(document.querySelector(".mobile-surface")).toBeTruthy();
      const trigger = await screen.findByRole("button", { name: "Task details" });
      expect(trigger.getAttribute("aria-controls")).toBe("worker-task-details");
      fireEvent.click(trigger);
      expect(await screen.findByRole("dialog", { name: "Task details" })).toBeTruthy();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("does not offer an empty task-details sheet on a new phone chat", () => {
    vi.stubGlobal("matchMedia", vi.fn().mockImplementation((query: string) => ({
      matches: query === "(max-width: 1374px)" || query === "(max-width: 640px)",
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })));
    renderChat(null);
    expect(document.querySelector(".mobile-surface")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Task details" })).toBeNull();
    expect(document.getElementById("worker-task-details")).toBeNull();
  });

  it("closes a compact overlay and moves focus to the desktop toggle at the breakpoint", async () => {
    const viewport = stubChatViewport(true, false);
    api.conversation.mockResolvedValue({
      messages: [{
        id: "assistant-a",
        role: "assistant",
        content: "Current answer",
        created_at: "2026-01-01T00:00:00Z",
      }],
      active_run_id: null,
    });
    renderChat("conversation-a");
    await screen.findByText("Current answer");

    fireEvent.click(screen.getByRole("button", { name: "Task details" }));
    expect(await screen.findByRole("complementary", { name: "Task details" })).toBeTruthy();

    act(() => viewport.setCompact(false));

    await waitFor(() => expect(screen.getByRole("complementary", {
      name: "Task details",
    }).classList.contains("task-inspector--rail")).toBe(true));
    const railToggle = screen.getByRole("button", { name: "Hide the task panel" });
    await waitFor(() => expect(document.activeElement).toBe(railToggle));
    expect(screen.queryByRole("button", { name: "Dismiss task details" })).toBeNull();
  });

  it("keeps conversation-title controls out of the phone task-details rail", async () => {
    vi.stubGlobal("matchMedia", vi.fn().mockImplementation((query: string) => ({
      matches: query === "(max-width: 1374px)" || query === "(max-width: 640px)",
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })));
    api.conversation.mockResolvedValue({
      messages: [{
        id: "assistant-a",
        role: "assistant",
        content: "Current answer",
        created_at: "2026-01-01T00:00:00Z",
      }],
      active_run_id: null,
    });
    try {
      renderChat("conversation-a");
      fireEvent.click(await screen.findByRole("button", { name: "Task details" }));
      const rail = await screen.findByRole("dialog", { name: "Task details" });
      expect(within(rail).queryByText("Task actions")).toBeNull();
      expect(within(rail).queryByLabelText("Conversation title")).toBeNull();
      expect(within(rail).queryByRole("button", { name: "Close conversation" })).toBeNull();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("titles the header with the real conversation, not a slogan", async () => {
    api.conversation.mockResolvedValue({ messages: [], active_run_id: null });
    renderChat("conversation-a");

    expect(await screen.findByRole("heading", { level: 1, name: "Renewal outreach" }))
      .toBeTruthy();
    expect(screen.getByRole("region", { name: "Conversation transcript" }).hasAttribute("aria-live"))
      .toBe(false);
  });

  it("summarises tool use naturally and retains the exact expandable detail", async () => {
    api.conversation.mockResolvedValue({
      messages: [{
        id: "assistant-a",
        role: "assistant",
        content: "I found the file.",
        events: [
          { type: "message_start", run_id: "run-a", conversation_id: "conversation-a" },
          { type: "tool_call", call_id: "call-a", tool: "file.read", args_summary: { keys: ["path"] } },
          { type: "tool_result", call_id: "call-a", verb: "file.read", status: "ok" },
          { type: "message_end", run_id: "run-a" },
        ],
      }],
      active_run_id: null,
    });
    renderChat("conversation-a");

    const summaryText = await screen.findByText("Read files");
    const summary = summaryText.closest("summary");
    expect(summary?.getAttribute("aria-label")).toBe("Read files. 1 tool detail");
    expect(summary?.querySelector(".transcript-tool-glyph")?.getAttribute("data-kind"))
      .toBe("read");
    expect(document.querySelector(".work-rule")).toBeNull();
    expect(document.querySelector(".activity-row")).toBeNull();

    fireEvent.click(summary!);
    const detail = document.querySelector(".transcript-tool-detail");
    expect(detail?.querySelector("code")?.textContent).toBe("file.read");
    expect(detail?.querySelector("[data-status]")?.textContent).toBe("Success");
    expect(document.querySelector(".tool-icon-read")).toBeTruthy();
  });

  it("loads redacted run detail only after the user opens a tool receipt", async () => {
    api.runEvents.mockResolvedValue([
      {
        type: "tool_call",
        run_id: "run-a",
        call_id: "call-read",
        tool: "file.read",
        input: { path: "apps/worker/package.json" },
        args_summary: { keys: ["path"], count: 1 },
      },
      {
        type: "tool_result",
        run_id: "run-a",
        call_id: "call-read",
        status: "ok",
        output: { bytes: 640 },
        result_summary: { keys: ["bytes"] },
      },
      {
        type: "tool_call",
        run_id: "run-a",
        call_id: "call-command",
        tool: "exec_command",
        input: { cmd: "pnpm --dir apps/worker typecheck", token: "[redacted]" },
        args_summary: { keys: ["cmd", "token"], count: 2 },
      },
      {
        type: "tool_result",
        run_id: "run-a",
        call_id: "call-command",
        status: "ok",
        output: { output: "Done in 1.2s", exit_code: 0 },
        result_summary: { keys: ["exit_code", "output"] },
      },
    ]);
    api.conversation.mockResolvedValue({
      messages: [{
        id: "assistant-a",
        role: "assistant",
        content: "The checks passed.",
        events: [
          { type: "message_start", run_id: "run-a", conversation_id: "conversation-a" },
          { type: "tool_call", call_id: "call-read", tool: "file.read", args_summary: { keys: ["path"] } },
          { type: "tool_result", call_id: "call-read", status: "ok", result_summary: { keys: ["bytes"] } },
          { type: "tool_call", call_id: "call-command", tool: "exec_command", args_summary: { keys: ["cmd", "token"] } },
          { type: "tool_result", call_id: "call-command", status: "ok", result_summary: { keys: ["exit_code", "output"] } },
          { type: "message_end", run_id: "run-a" },
        ],
      }],
      active_run_id: null,
    });
    renderChat("conversation-a");

    expect(api.runEvents).not.toHaveBeenCalled();
    fireEvent.click((await screen.findByText("Read files, ran commands")).closest("summary")!);
    await waitFor(() => expect(api.runEvents).toHaveBeenCalledWith("run-a", expect.any(AbortSignal)));
    fireEvent.click(await screen.findByRole("button", { name: /Ran commands.*exec_command.*Success/ }));

    expect(await screen.findByText(/\$ pnpm --dir apps\/worker typecheck/)).toBeTruthy();
    expect(screen.getByText(/Done in 1\.2s/)).toBeTruthy();
    expect(screen.getByText("Input fields").parentElement?.textContent).toContain("cmd, token");
    expect(document.body.textContent).not.toContain("[redacted]");
  });

  it("collapses the desktop rail from the header toggle", async () => {
    api.conversation.mockResolvedValue({ messages: [], active_run_id: null });
    renderChat("conversation-a");
    await screen.findByRole("heading", { level: 1, name: "Renewal outreach" });

    fireEvent.click(screen.getByRole("button", { name: "Hide the task panel" }));
    expect(document.querySelector(".chat-layout")?.getAttribute("data-rail-collapsed"))
      .toBe("true");

    fireEvent.click(screen.getByRole("button", { name: "Show the task panel" }));
    expect(document.querySelector(".chat-layout")?.getAttribute("data-rail-collapsed"))
      .toBeNull();
  });

  it("counts subagents conversation-wide, including settled turns", async () => {
    api.conversation.mockResolvedValue({
      messages: [
        { id: "m1", role: "user", content: "Do the renewals" },
        {
          id: "m2", role: "assistant", content: "Done", events: [
            { type: "subagent", child_run_id: "r1", task: "Read health signals" },
            { type: "subagent", child_run_id: "r2", task: "Draft outreach" },
          ],
        },
      ],
      active_run_id: null,
    });
    renderChat("conversation-a");

    expect(await screen.findByText("2 subagents")).toBeTruthy();
  });

  it("reconciles a consumed approval in a settled transcript as read-only", async () => {
    api.conversation.mockResolvedValue({
      messages: [
        { id: "m1", role: "user", content: "Do the renewals" },
        {
          id: "m2", role: "assistant", content: "Stopped for approval", events: [
            {
              type: "hitl",
              hitl_request_id: "h1",
              kind: "approval",
              question: "Raise 3 tickets",
              options: [],
              verb: "ticket.create",
            },
          ],
        },
      ],
      active_run_id: null,
    });
    renderChat("conversation-a");

    expect(await screen.findByText("Raise 3 tickets")).toBeTruthy();
    await waitFor(() => expect(api.invokeApprovalState).toHaveBeenCalledWith("h1"));
    expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
    expect(screen.getByText(/request is consumed and is no longer answerable/)).toBeTruthy();
  });

  it("answers a still-pending approval from its reopened run chat", async () => {
    api.invokeApprovalState.mockResolvedValue({ status: "pending" });
    api.conversation.mockResolvedValue({
      messages: [{
        id: "m2",
        role: "assistant",
        content: "Stopped for approval",
        events: [{
          type: "hitl",
          hitl_request_id: "routine-approval",
          kind: "approval",
          question: "Send the prepared update",
          options: [],
          verb: "channel.send",
        }],
      }],
      active_run_id: null,
    });
    renderChat("conversation-a");

    fireEvent.click(await screen.findByRole("button", { name: "Approve" }));
    await waitFor(() => expect(api.respondHitl).toHaveBeenCalledWith(
      "routine-approval",
      "approve",
    ));
    await waitFor(() => expect(api.conversation.mock.calls.length).toBeGreaterThanOrEqual(2));
    expect(screen.getByText(/decision "approve" was recorded/)).toBeTruthy();
  });

  it("labels an automatic routine chat from server-owned provenance", async () => {
    api.conversation.mockResolvedValue({
      conversation: {
        id: "conversation-a",
        title: "Renamed by the user",
        status: "active",
        origin: "routine",
        source_ref: "morning-priorities",
        source_run_id: "routine-run-1",
        companion_id: "jarvis",
      },
      messages: [],
      active_run_id: null,
    });
    renderChat("conversation-a");

    expect(await screen.findByRole("region", { name: "Automatic routine run" })).toBeTruthy();
    expect(screen.getByText("morning-priorities · Jarvis")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "View in Runs" }));
    expect(window.location.hash).toBe("#/runs");
  });

  it("flips the theme from an active conversation header and persists the choice", async () => {
    api.conversation.mockResolvedValue({ messages: [], active_run_id: null });
    renderChat("conversation-a");

    await screen.findByRole("heading", { level: 1, name: "Renewal outreach" });

    fireEvent.click(screen.getByRole("button", { name: "Toggle theme" }));
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(localStorage.getItem("boltrig-worker-theme")).toBe("light");

    fireEvent.click(screen.getByRole("button", { name: "Toggle theme" }));
    expect(document.documentElement.dataset.theme).toBe("dark");
  });
});
