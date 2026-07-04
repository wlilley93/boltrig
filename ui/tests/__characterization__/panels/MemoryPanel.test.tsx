import { afterEach, describe, it } from "vitest";
import { render } from "@testing-library/react";
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
  afterEach(clearApiMocks);

  it("renders without crashing", () => {
    mockApi();
    render(<MemoryPanel />);
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
});
