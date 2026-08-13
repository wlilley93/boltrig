// @vitest-environment happy-dom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  conversationsPage: vi.fn(),
}));

vi.mock("../src/client", () => ({ client: api }));
vi.mock("../src/components/ChatView", () => ({ ChatView: () => null }));
vi.mock("../src/components/CommandPalette", () => ({ CommandPalette: () => null }));
vi.mock("../src/components/Shell", () => ({
  Sidebar: ({
    onSettingsQuery,
    onSettingsSection,
    settingsSection,
  }: {
    onSettingsQuery?(query: string): void;
    onSettingsSection?(section: "health" | "knowledge"): void;
    settingsSection?: string;
  }) => (
    <aside>
      <span aria-label="Sidebar settings section">{settingsSection}</span>
      <button onClick={() => onSettingsSection?.("health")} type="button">Open Health</button>
      <button onClick={() => onSettingsQuery?.("theme")} type="button">Search theme</button>
    </aside>
  ),
}));
vi.mock("../src/components/Views", () => ({
  SettingsView: ({ section }: { section: string }) => (
    <div aria-label="Current settings section">{section}</div>
  ),
}));
vi.mock("../src/components/settings/SearchResults", () => ({
  SettingsSearchResults: ({
    onOpenSection,
  }: {
    onOpenSection(section: "knowledge"): void;
  }) => (
    <button onClick={() => onOpenSection("knowledge")} type="button">
      Open Knowledge result
    </button>
  ),
}));

import { App } from "../src/App";

beforeEach(() => {
  window.location.hash = "#/settings/you";
  api.conversationsPage.mockResolvedValue({ conversations: [], next_offset: null });
  vi.stubGlobal("matchMedia", vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })));
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.unstubAllGlobals();
  window.location.hash = "";
});

describe("Settings route navigation", () => {
  it("keeps sidebar and search-result section changes in the durable hash", async () => {
    render(<App />);
    expect((await screen.findByLabelText("Current settings section")).textContent).toBe("you");

    fireEvent.click(screen.getByRole("button", { name: "Open Health" }));
    await waitFor(() => expect(window.location.hash).toBe("#/settings/health"));
    expect(screen.getByLabelText("Current settings section").textContent).toBe("health");

    fireEvent.click(screen.getByRole("button", { name: "Search theme" }));
    fireEvent.click(await screen.findByRole("button", { name: "Open Knowledge result" }));
    await waitFor(() => expect(window.location.hash).toBe("#/settings/knowledge"));
    expect(screen.getByLabelText("Current settings section").textContent).toBe("knowledge");
  });

  it("restores a copied settings URL and follows history hash changes", async () => {
    window.location.hash = "#/settings/knowledge";
    render(<App />);
    expect((await screen.findByLabelText("Current settings section")).textContent).toBe("knowledge");

    window.location.hash = "#/settings/health";
    fireEvent(window, new HashChangeEvent("hashchange"));
    await waitFor(() => {
      expect(screen.getByLabelText("Current settings section").textContent).toBe("health");
    });
  });
});
