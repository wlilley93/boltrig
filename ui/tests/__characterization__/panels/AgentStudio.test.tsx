import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import { api } from "@/api/client";
import { AgentsSlide } from "@/panels/AgentsSlide";
import { mergeCapabilityProfiles } from "@/panels/agents/model";
import { nextAgentName } from "@/panels/agentsSlide/AgentCreateCard";
import { clearApiMocks, mockApi } from "../helpers";

afterEach(() => {
  cleanup();
  clearApiMocks();
});

describe("Agent Studio", () => {
  it("merges live capability profiles without duplicating configured agents", () => {
    const configured = [{
      name: "worker-1",
      kind: "worker" as const,
      runtime: "pi",
      cost_tier: "standard",
      max_depth: 2,
      supported_skills: ["*"],
      is_ephemeral: true,
    }];
    const merged = mergeCapabilityProfiles(configured, [
      { ...configured[0], runtime: "hermes" },
      {
        name: "worker-2",
        runtime: "hermes",
        cost_tier: "cheap",
        max_depth: 1,
        supported_skills: ["research/*"],
        is_ephemeral: true,
      },
    ]);

    expect(merged.map((agent) => agent.name)).toEqual(["worker-1", "worker-2"]);
    expect(merged[0].runtime).toBe("pi");
    expect(nextAgentName(merged)).toBe("worker-3");
  });

  it("creates an agent through the governed capability verb", async () => {
    mockApi({
      skills: { skills: [] },
      capabilities: { verbs: [], agent_capabilities: [] },
      budgets: { budgets: [] },
      work: { items: [] },
      invoke: { status: "ok", output: { id: "worker-1" } },
    });
    vi.mocked(api.getConfig).mockImplementation(async (section) => ({
      section,
      value: section === "hierarchy" ? {} : [],
    }));
    render(<AgentsSlide />);

    fireEvent.click(screen.getByRole("button", { name: "New agent" }));
    fireEvent.click(screen.getByRole("button", { name: "Request agent creation" }));

    await waitFor(() => expect(api.invoke).toHaveBeenCalledWith({
      noun: "control",
      verb: "control.capability.upsert",
      params: {
        name: "worker-1",
        runtime: "hermes",
        supported_skills: ["*"],
        max_depth: 2,
        is_ephemeral: true,
        cost_tier: "standard",
      },
    }));
  });
});
