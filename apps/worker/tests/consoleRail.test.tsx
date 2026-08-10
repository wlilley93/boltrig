// @vitest-environment happy-dom

import { cleanup, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  artifacts: vi.fn(),
  chatConfig: vi.fn(),
  conversation: vi.fn(),
  conversations: vi.fn(),
  modelProfiles: vi.fn(),
  streamChat: vi.fn(),
}));

vi.mock("../src/client", () => ({ client: api }));
vi.mock("../src/components/VoiceCall", () => ({
  VoiceCall: () => null,
}));

import { ChatView } from "../src/components/ChatView";

beforeEach(() => {
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
  api.conversations.mockResolvedValue({ conversations: [] });
  api.modelProfiles.mockResolvedValue({ profiles: [] });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  delete document.documentElement.dataset.theme;
});

describe("console rail", () => {
  // The defect this guards is the one VDS S-1(4)(b) names: a showpiece drawn in
  // the outgoing card idiom while the doctrine requiring one flush panel lives
  // only in prose. The decided target draws the rail as ONE card whose groups
  // are divided by hairlines, so a group that carries its own border is the
  // regression, and counting cards is the way to catch it.
  it("draws the rail as one card of hairline-divided groups", async () => {
    render(
      <ChatView conversationId={null} onConversation={vi.fn()} onChanged={vi.fn()} />,
    );

    await waitFor(() => {
      expect(document.querySelectorAll(".right-rail .rail-card").length).toBe(1);
    });

    const groups = document.querySelectorAll(".right-rail .rail-group");
    expect(groups.length).toBeGreaterThan(1);
    // Every group is a direct child of the single card: a group nested inside
    // another group would reintroduce a box within a box.
    for (const group of groups) {
      expect(group.parentElement?.classList.contains("rail-card")).toBe(true);
    }
  });

  it("states the run before anything else in the rail", async () => {
    render(
      <ChatView conversationId={null} onConversation={vi.fn()} onChanged={vi.fn()} />,
    );

    await waitFor(() => {
      const first = document.querySelector(".right-rail .rail-group .rail-group-head span");
      expect(first?.textContent).toBe("This run");
    });
    // Ready, not a fabricated spend line: the turn carries no cost, and the
    // decided target's "£0.92 of £5.00" row has no source in this client.
    const labels = [...document.querySelectorAll(".right-rail .rail-label")]
      .map((node) => node.textContent);
    expect(labels).toContain("Ready");
    expect(labels.some((label) => label?.includes("£"))).toBe(false);
  });
});
