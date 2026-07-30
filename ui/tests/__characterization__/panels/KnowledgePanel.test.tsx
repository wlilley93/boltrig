import { afterEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import { api } from "@/api/client";
import { KnowledgePanel } from "@/panels/KnowledgePanel";
import { clearApiMocks, mockApi } from "../helpers";

const asset = {
  id: "ast-1",
  title: "Rig handbook",
  filename: "rig.pdf",
  asset_type: "pdf",
  revision_id: "rev-1",
  source_kind: "upload",
  segment_count: 4,
  created_at: "2026-07-21T00:00:00Z",
};

const providers = {
  providers: [
    {
      id: "cognee",
      display_name: "Cognee",
      role: "knowledge_compiler",
      enabled: true,
      bundled: true,
      health: "ok",
      status: "enabled",
    },
    {
      id: "supermemory",
      display_name: "Supermemory",
      role: "managed_context",
      enabled: false,
      bundled: false,
      health: "unavailable",
      status: "unavailable",
      last_error: "Credential-backed projection adapter is not implemented in this build.",
    },
  ],
};

describe("KnowledgePanel", () => {
  afterEach(() => {
    cleanup();
    clearApiMocks();
  });

  it("shows canonical assets and requires a deliberate erase confirmation", async () => {
    mockApi({ knowledgeAssets: { assets: [asset] }, knowledgeProviders: providers });
    render(<KnowledgePanel />);
    await screen.findByText("Rig handbook");

    fireEvent.click(screen.getByRole("button", { name: "Erase Rig handbook" }));
    expect(api.eraseKnowledgeAsset).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Confirm erase Rig handbook" }));
    await waitFor(() => expect(api.eraseKnowledgeAsset).toHaveBeenCalledWith("ast-1"));
  });

  it("searches sources and renders a stable citation locator", async () => {
    mockApi({
      knowledgeAssets: { assets: [] },
      knowledgeProviders: providers,
      knowledgeSearch: {
        query: "shackle",
        hits: [{
          asset_id: "ast-1",
          revision_id: "rev-1",
          segment_id: "seg-1",
          title: "Rig handbook",
          filename: "rig.pdf",
          text: "The shackle is rated to ninety kilograms.",
          locator: { page: 4 },
          score: 2.1,
          citation: {
            asset_id: "ast-1",
            revision_id: "rev-1",
            segment_id: "seg-1",
            title: "Rig handbook",
            filename: "rig.pdf",
            locator: { page: 4 },
            source_kind: "upload",
            content_hash: "abc",
          },
        }],
      },
    });
    render(<KnowledgePanel />);
    fireEvent.click(screen.getByRole("tab", { name: "Search" }));
    fireEvent.change(screen.getByLabelText("Search Knowledge"), { target: { value: "shackle" } });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));

    await screen.findByText("The shackle is rated to ninety kilograms.");
    expect(screen.getByText("page 4")).toBeTruthy();
    expect(api.knowledgeSearch).toHaveBeenCalledWith("shackle");
  });

  it("presents Cognee as bundled and keeps unimplemented add-ons unavailable", async () => {
    mockApi({
      knowledgeAssets: { assets: [] },
      knowledgeProviders: providers,
    });
    render(<KnowledgePanel />);
    fireEvent.click(screen.getByRole("tab", { name: "Providers" }));
    await screen.findByText("Bundled default");
    const unavailable = screen.getByRole("button", { name: "Unavailable" });
    expect(unavailable.hasAttribute("disabled")).toBe(true);
    expect(api.setKnowledgeProvider).not.toHaveBeenCalled();
  });

  it("uploads a selected document into canonical Knowledge", async () => {
    mockApi({
      knowledgeAssets: { assets: [] },
      knowledgeProviders: providers,
      uploadKnowledge: {
        asset_id: "ast-2",
        revision_id: "rev-2",
        status: "committed",
        segment_count: 2,
        digest: "abc",
        projections: [],
      },
    });
    render(<KnowledgePanel />);
    const file = new File(["hello"], "notes.md", { type: "text/markdown" });
    fireEvent.change(screen.getByLabelText("Knowledge document"), {
      target: { files: [file] },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add to Knowledge" }));
    await waitFor(() => expect(api.uploadKnowledge).toHaveBeenCalledWith(file, "notes"));
  });
});
