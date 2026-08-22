// @vitest-environment happy-dom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  conversations: vi.fn(),
  hitl: vi.fn(),
  respondHitl: vi.fn(),
}));

vi.mock("../src/client", () => ({ client: api }));
vi.mock("../src/components/familiar/FamiliarBadge", () => ({
  FamiliarBadge: ({ label }: { label: string }) => <span aria-label={label} data-testid="badge" />,
}));

import { MobileToday } from "../src/components/MobileToday";

function row(id: string, title: string, extra: Record<string, unknown> = {}) {
  return { id, title, status: "open", updated_at: "2026-08-22T10:00:00Z", ...extra };
}

function mount() {
  return render(
    <MobileToday
      initials="AL"
      onNewChat={() => undefined}
      onOpenConversation={() => undefined}
      onSettings={() => undefined}
      workspace="Private"
    />,
  );
}

beforeEach(() => {
  api.hitl.mockReset().mockResolvedValue({ requests: [] });
  api.conversations.mockReset();
  api.respondHitl.mockReset().mockResolvedValue({ status: "ok" });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("Today on a phone-sized web view", () => {
  it("Working now is the conversation the server says is working, not the most recent one", async () => {
    api.conversations.mockResolvedValue({
      conversations: [row("c1", "Newest, idle"), row("c2", "Still running", { working: true })],
    });
    mount();
    expect(await screen.findByText("Working now")).toBeTruthy();
    const working = screen.getByText("Working now").parentElement as HTMLElement;
    expect(working.textContent).toContain("Still running");
    expect(working.textContent).not.toContain("Newest, idle");
  });

  it("with nothing working there is no Working now group at all", async () => {
    api.conversations.mockResolvedValue({ conversations: [row("c1", "Idle one"), row("c2", "Idle two")] });
    mount();
    expect(await screen.findByText("Earlier")).toBeTruthy();
    expect(screen.queryByText("Working now")).toBeNull();
  });

  it("every earlier conversation is listed, not only the first twelve", async () => {
    api.conversations.mockResolvedValue({
      conversations: Array.from({ length: 15 }, (_, i) => row(`c${i}`, `Conversation ${i}`)),
    });
    mount();
    expect(await screen.findByText("Conversation 14")).toBeTruthy();
    expect(screen.getAllByTestId("badge")).toHaveLength(15);
  });

  it("a failed load is said out loud and can be retried", async () => {
    api.conversations.mockRejectedValueOnce(new Error("offline")).mockResolvedValue({ conversations: [row("c1", "Back again")] });
    mount();
    expect(await screen.findByText("Today could not be loaded.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(screen.getByText("Back again")).toBeTruthy());
    expect(screen.queryByText("Today could not be loaded.")).toBeNull();
  });
});
