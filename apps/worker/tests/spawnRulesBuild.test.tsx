// @vitest-environment happy-dom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  spawnRules: vi.fn(),
  simulateSpawnRules: vi.fn(),
}));

vi.mock("../src/client", () => ({ client: api }));

import { SpawnRulesBuild } from "../src/components/build/SpawnRulesBuild";

beforeEach(() => {
  api.spawnRules.mockResolvedValue({
    policy: {
      state: "conflicted",
      source: "config_revision",
      revision_id: 7,
      generation: "policy-generation",
      execution_input: "server_trusted_classification_only",
      rules: [{
        id: "research-route",
        priority: 50,
        intent_tags: ["analysis", "research"],
        capability: "researcher",
        skills_added: ["web/read"],
        max_depth: 2,
      }],
      conflicts: [{
        priority: 50,
        rules: ["research-route", "other-route"],
        example_intent_tags: ["analysis", "research"],
      }],
    },
  });
  api.simulateSpawnRules.mockResolvedValue({
    status: "matched",
    input_trust: "untrusted_preview_only",
    selection: {
      id: "research-route",
      priority: 50,
      intent_tags: ["analysis", "research"],
      capability: "researcher",
      skills_added: ["web/read"],
      max_depth: 2,
    },
    generation: "policy-generation",
  });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("effective spawn-rule policy", () => {
  it("shows conflicts and keeps simulation explicitly preview-only", async () => {
    render(<SpawnRulesBuild />);

    expect(await screen.findByText("research-route")).toBeTruthy();
    expect(screen.getByText("Rule conflicts fail closed")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Intent tags, comma separated"), {
      target: { value: "Analysis, research, analysis" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Preview rule" }));

    await waitFor(() => expect(api.simulateSpawnRules).toHaveBeenCalledWith([
      "analysis",
      "research",
    ]));
    expect(await screen.findByText(/research-route selects capability researcher/)).toBeTruthy();
    expect(screen.getByText("Preview-only input; no runtime trusted these tags.")).toBeTruthy();
  });
});
