import { afterEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { EvalPanel } from "@/panels/EvalPanel";
import { clearApiMocks, mockApi } from "../helpers";

afterEach(() => {
  cleanup();
  clearApiMocks();
});

describe("EvalPanel saved cases", () => {
  it("shows tenant-scoped saved cases and selects one for a run", async () => {
    mockApi({
      evalCases: {
        cases: [
          {
            id: "safe-triage",
            target_kind: "skill",
            target_ref: "triage",
            input: { ticket: "42" },
            assertions: { forbidden_grants: ["ticket.delete"] },
            labels: ["security", "regression"],
          },
        ],
      },
      evalRuns: { runs: [] },
      skills: { skills: [] },
      workflows: { workflows: [] },
      capabilities: { verbs: [] },
    });

    render(<EvalPanel />);

    expect(await screen.findByRole("heading", { name: "Saved cases" })).toBeTruthy();
    expect(await screen.findByText("safe-triage")).toBeTruthy();
    expect(screen.getByText("skill · triage")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Use case safe-triage" }));
    expect((screen.getByLabelText("Case to run") as HTMLSelectElement).value).toBe(
      "safe-triage",
    );
  });
});
