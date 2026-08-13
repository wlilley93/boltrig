// @vitest-environment happy-dom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const state = vi.hoisted(() => ({
  artifacts: vi.fn(),
  chatConfig: vi.fn(),
  chatModelChoices: vi.fn(),
  conversation: vi.fn(),
  conversations: vi.fn(),
  knowledgeAssets: vi.fn(),
  knowledgeProviders: vi.fn(),
  modelProfiles: vi.fn(),
  voiceStart: vi.fn(),
}));

vi.mock("../src/client", () => ({
  client: {
    artifacts: state.artifacts,
    chatConfig: state.chatConfig,
    chatModelChoices: state.chatModelChoices,
    conversation: state.conversation,
    conversations: state.conversations,
    createCall: vi.fn(),
    knowledgeAssets: state.knowledgeAssets,
    knowledgeProviders: state.knowledgeProviders,
    modelProfiles: state.modelProfiles,
  },
}));

vi.mock("../src/components/VoiceCall", () => ({
  VoiceCall: ({ onCallActive }: { onCallActive?(active: boolean): void }) => (
    <div className="voice-idle voice-idle-embedded">
      <button
        aria-label="Talk to the chief of staff"
        className="primary-button"
        onClick={() => {
          state.voiceStart();
          onCallActive?.(true);
        }}
        type="button"
      >
        Start voice
      </button>
    </div>
  ),
}));

vi.mock("../src/components/build/ActionsTable", () => ({
  ActionsTable: () => <div>Actions inventory</div>,
}));
vi.mock("../src/components/build/SkillsTable", () => ({
  SkillsTable: () => <div>Skills inventory</div>,
}));
vi.mock("../src/components/build/CapabilityRunner", () => ({
  CapabilityRunner: () => <div>Capability runner</div>,
}));
vi.mock("../src/components/build/RegistryBuild", () => ({
  RegistryBuild: () => <div>Registry authoring</div>,
}));
vi.mock("../src/components/build/AdaptersBuild", () => ({
  AdaptersBuild: () => <div>Adapter authoring</div>,
}));
vi.mock("../src/components/build/ModelEndpointsBuild", () => ({
  ModelEndpointsBuild: () => <div>Model authoring</div>,
}));
vi.mock("../src/components/build/SpawnRulesBuild", () => ({
  SpawnRulesBuild: () => <div>Routing authoring</div>,
}));
vi.mock("../src/components/build/SkillsBuild", () => ({
  SkillsBuild: () => <div>Skill authoring</div>,
}));
vi.mock("../src/components/build/RecentlyChanged", () => ({
  RecentlyChanged: () => <div>Recently changed</div>,
}));

import { BuildView } from "../src/components/BuildView";
import { ChatView } from "../src/components/ChatView";
import { KnowledgeView } from "../src/components/knowledge/KnowledgeView";

beforeEach(() => {
  window.history.replaceState(null, "", "#/chat");
  state.artifacts.mockResolvedValue({ artifacts: [], next_cursor: null });
  state.chatConfig.mockResolvedValue({
    attachments: {
      max_count: 8,
      max_bytes: 262_144,
      max_total_bytes: 1_048_576,
      model_readable_media_types: ["text/*"],
    },
  });
  state.chatModelChoices.mockResolvedValue({
    status: "ok",
    reason: null,
    choices: [],
    default_choice_id: "opaque-default-route",
    default_model_name: "openai/gpt-5.4",
    default_available: true,
  });
  state.conversation.mockResolvedValue({ messages: [], active_run_id: null });
  state.conversations.mockResolvedValue({
    conversations: [{
      id: "conversation-a",
      title: "Renewal outreach",
      status: "active",
      updated_at: "2026-08-11T00:00:00Z",
    }],
  });
  state.knowledgeAssets.mockResolvedValue({
    assets: [{
      id: "source-a",
      title: "Renewal playbook",
      filename: "renewal.md",
      asset_type: "text",
      revision_id: "revision-a",
      source_kind: "upload",
      segment_count: 3,
      created_at: "2026-08-10T00:00:00Z",
    }],
    next_offset: null,
  });
  state.knowledgeProviders.mockResolvedValue({ providers: [] });
  state.modelProfiles.mockResolvedValue({ profiles: [] });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  window.history.replaceState(null, "", "#/chat");
});

describe("desktop parity gaps", () => {
  it("starts the existing conversation's real voice handoff from the Familiar title", async () => {
    render(
      <ChatView
        conversationId="conversation-a"
        onChanged={vi.fn()}
        onConversation={vi.fn()}
      />,
    );

    const titleControl = await screen.findByRole("button", {
      name: "Talk to the chief of staff about Renewal outreach",
    });
    const heading = screen.getByRole("heading", { level: 1, name: "Renewal outreach" });
    expect(titleControl.parentElement).toBe(heading.parentElement);
    expect(titleControl.parentElement?.querySelector(".chat-header-familiar-mark .familiar-orb"))
      .toBeTruthy();

    fireEvent.click(titleControl);
    expect(state.voiceStart).toHaveBeenCalledTimes(1);
  });

  it("keeps Skills canonical and collapses advanced Build authoring by default", () => {
    window.history.replaceState(null, "", "#/build/skills");
    render(<BuildView />);

    expect(screen.getByRole("heading", { level: 1, name: "Skills" })).toBeTruthy();
    expect(screen.getByText("Skills inventory")).toBeTruthy();
    const disclosure = screen.getByRole("button", { name: "Advanced authoring" });
    expect(disclosure.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByRole("navigation", { name: "Advanced build sections" })).toBeNull();

    fireEvent.click(disclosure);
    expect(screen.getByRole("navigation", { name: "Advanced build sections" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Adapters" })).toBeTruthy();
  });

  it("offers only the real governed Skills authoring handoff", () => {
    window.history.replaceState(null, "", "#/build/skills");
    render(<BuildView />);

    fireEvent.click(screen.getByRole("button", { name: "Record a skill" }));
    expect(screen.getByRole("dialog", { name: "Record a skill" })).toBeTruthy();
    const corrected = screen.getByRole("button", { name: /^From work you corrected/ }) as HTMLButtonElement;
    const write = screen.getByRole("button", { name: /^Write it down/ }) as HTMLButtonElement;
    const recorded = screen.getByRole("button", { name: /^Record yourself doing it/ }) as HTMLButtonElement;
    expect(corrected.disabled).toBe(true);
    expect(write.disabled).toBe(false);
    expect(recorded.disabled).toBe(true);

    fireEvent.click(write);
    expect(screen.queryByRole("dialog", { name: "Record a skill" })).toBeNull();
    expect(screen.getByText("Skill authoring")).toBeTruthy();
  });

  it("keeps the governed creation chooser modal and restores its trigger", async () => {
    window.history.replaceState(null, "", "#/build/skills");
    render(<BuildView />);

    const trigger = screen.getByRole("button", { name: "Record a skill" });
    trigger.focus();
    fireEvent.click(trigger);
    const dialog = screen.getByRole("dialog", { name: "Record a skill" });
    const enabledMethod = screen.getByRole("button", { name: /^Write it down/ });
    await waitFor(() => expect(document.activeElement).toBe(enabledMethod));
    expect(document.body.style.overflow).toBe("hidden");

    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "Record a skill" })).toBeNull();
    expect(document.activeElement).toBe(trigger);
    expect(document.body.style.overflow).toBe("");
  });

  it("routes each supported plugin method to its real governed surface", async () => {
    window.history.replaceState(null, "", "#/build/actions");
    const view = render(<BuildView />);

    fireEvent.click(screen.getByRole("button", { name: "Add a plugin" }));
    expect(screen.getByRole("dialog", { name: "Add a plugin" })).toBeTruthy();
    const system = screen.getByRole("button", { name: /^Choose a system/ }) as HTMLButtonElement;
    const address = screen.getByRole("button", { name: /^Point at an address/ }) as HTMLButtonElement;
    const tools = screen.getByRole("button", { name: /^Use another app's tools/ }) as HTMLButtonElement;
    expect(system.disabled).toBe(false);
    expect(address.disabled).toBe(false);
    expect(tools.disabled).toBe(false);

    fireEvent.click(system);
    await waitFor(() => expect(window.location.hash).toBe("#/integrations"));

    view.unmount();
    window.history.replaceState(null, "", "#/build/actions");
    render(<BuildView />);
    fireEvent.click(screen.getByRole("button", { name: "Add a plugin" }));
    fireEvent.click(screen.getByRole("button", { name: /^Point at an address/ }));
    await waitFor(() => expect(window.location.hash).toBe("#/build/adapters"));
    expect(screen.getByText("Adapter authoring")).toBeTruthy();
  });

  it("keeps an advanced Build deep link visible and selected", () => {
    window.history.replaceState(null, "", "#/build/adapters");
    render(<BuildView />);

    expect(screen.getByRole("heading", { level: 1, name: "Adapters" })).toBeTruthy();
    expect(screen.getByText("Adapter authoring")).toBeTruthy();
    expect(screen.getByRole("button", { name: /Advanced authoring/ }).getAttribute("aria-expanded"))
      .toBe("true");
    expect(screen.getByRole("button", { name: "Adapters" }).getAttribute("aria-current"))
      .toBe("page");
  });

  it("routes the Knowledge storage CTA to the real Knowledge settings section", async () => {
    window.history.replaceState(null, "", "#/knowledge");
    render(<KnowledgeView />);

    fireEvent.click(await screen.findByRole("button", { name: "Change where files are kept" }));
    await waitFor(() => expect(window.location.hash).toBe("#/settings/knowledge"));
  });
});
