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

  it("separates running from creation and blocks invalid advanced JSON", async () => {
    mockApi({
      evalCases: { cases: [] },
      evalRuns: { runs: [] },
      skills: { skills: [{ id: "triage", version: "1", tool_grants: [] }] },
      workflows: { workflows: [] },
      capabilities: { verbs: [] },
    });

    const { container } = render(<EvalPanel />);
    expect(screen.getByRole("button", { name: "Run case" })).toBeTruthy();
    expect(container.querySelectorAll(".btn--primary")).toHaveLength(1);

    fireEvent.click(screen.getByRole("radio", { name: "Create case" }));
    expect(screen.queryByRole("button", { name: "Run case" })).toBeNull();
    const request = screen.getByRole("button", { name: "Request case change" });
    expect(container.querySelectorAll(".btn--primary")).toHaveLength(1);

    fireEvent.click(screen.getByText("Advanced: edit case input as JSON"));
    fireEvent.change(screen.getByLabelText("Advanced: edit case input as JSON"), {
      target: { value: "{" },
    });
    expect(request).toHaveProperty("disabled", true);
    expect(screen.getByText("invalid JSON")).toBeTruthy();
  });
});
