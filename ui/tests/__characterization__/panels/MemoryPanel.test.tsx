import { afterEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { api } from "@/api/client";
import { MemoryPanel } from "@/panels/MemoryPanel";
import { FactCard } from "@/panels/memoryPanel/FactCard";
import { RecallTab } from "@/panels/memoryPanel/RecallTab";
import { BrowseTab } from "@/panels/memoryPanel/BrowseTab";
import { RememberTab } from "@/panels/memoryPanel/RememberTab";
import { IngestTab } from "@/panels/memoryPanel/IngestTab";
import { clearApiMocks, mockApi } from "../helpers";
import type { MemoryFactView } from "@/api/types";

const mockFact: MemoryFactView = {
  id: "fact-1",
  owner_scope: "user/test",
  kind: "entity",
  content: "Priya owns Acme.",
  data_class: "standard",
  provenance: {
    source_kind: "conversation",
    source_ref: "chat-1",
    created_at: "2026-01-01",
    hops: 0,
  },
};

describe("MemoryPanel", () => {
  afterEach(() => {
    cleanup();
    clearApiMocks();
  });

  it("renders without crashing", () => {
    mockApi();
    render(<MemoryPanel />);
    expect(screen.getByRole("tab", { name: "Recall" }).getAttribute("aria-selected")).toBe("true");
    expect(screen.getByRole("radiogroup", { name: "Search mode" })).toBeTruthy();
  });

  it("FactCard renders a fact", () => {
    render(<FactCard fact={mockFact} />);
  });

  it("RecallTab renders without crashing", () => {
    mockApi();
    render(<RecallTab />);
  });

  it("BrowseTab renders without crashing", () => {
    mockApi({ memoryFacts: { facts: [], scopes: [] } });
    render(<BrowseTab />);
  });

  it("RememberTab renders without crashing", () => {
    mockApi();
    render(<RememberTab />);
  });

  it("IngestTab renders without crashing", () => {
    mockApi({ memoryIngestions: { ingestions: [] } });
    render(<IngestTab />);
  });

  it("requires an in-frame arm-confirm before forgetting a fact", async () => {
    mockApi({
      memoryFacts: { facts: [mockFact], scopes: ["user/test"] },
      memoryForget: { status: "ok", facts_removed: 1 },
    });
    render(<BrowseTab />);
    await screen.findByText("Priya owns Acme.");

    fireEvent.click(screen.getByRole("button", { name: "Forget" }));
    expect(api.memoryForget).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Erase fact fact-1" }));
    await waitFor(() => expect(api.memoryForget).toHaveBeenCalledWith({ target: "fact-1" }));
  });

  it("supports exact source erasure with the same deliberate confirmation", async () => {
    mockApi({
      memoryFacts: { facts: [], scopes: ["user/test"] },
      memoryForget: { status: "ok", facts_removed: 2 },
    });
    render(<BrowseTab />);
    await screen.findByText(/No facts in your scope yet/);
    fireEvent.change(screen.getByLabelText("Erase by source"), {
      target: { value: "document:plan-v3" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Forget source" }));
    expect(api.memoryForget).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Erase source memory" }));
    await waitFor(() => expect(api.memoryForget).toHaveBeenCalledWith({ source_ref: "document:plan-v3" }));
  });

  it("submits structured scope, provenance, and relation fields", async () => {
    mockApi({ memoryRemember: { status: "ok", fact_ids: ["fact-2"], owner_scope: "user/test" } });
    render(<RememberTab />);
    fireEvent.change(screen.getByLabelText("What should the assistant remember?"), {
      target: { value: "The launch window is Friday." },
    });
    fireEvent.click(screen.getByText("Scope and provenance"));
    fireEvent.change(screen.getByLabelText("Owner scope"), { target: { value: "user/test" } });
    fireEvent.change(screen.getByLabelText("Source type"), { target: { value: "document" } });
    fireEvent.change(screen.getByLabelText("Source reference"), { target: { value: "doc-7" } });
    const related = screen.getByRole("combobox", { name: "Related fact IDs" });
    fireEvent.change(related, { target: { value: "fact-1" } });
    fireEvent.keyDown(related, { key: "Enter" });
    fireEvent.click(screen.getByRole("button", { name: "Remember" }));

    await waitFor(() => expect(api.memoryRemember).toHaveBeenCalledWith(expect.objectContaining({
      content: "The launch window is Friday.",
      owner_scope: "user/test",
      source_kind: "document",
      source_ref: "doc-7",
      relates_to: ["fact-1"],
    })));
  });
});
