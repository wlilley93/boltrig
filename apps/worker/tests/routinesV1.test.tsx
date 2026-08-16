// @vitest-environment happy-dom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  invokeApprovalState: vi.fn(),
  scheduleWorkflow: vi.fn(),
  triggerWorkflow: vi.fn(),
  unscheduleWorkflow: vi.fn(),
  upsertWorkflow: vi.fn(),
  workflow: vi.fn(),
  workflows: vi.fn(),
}));

vi.mock("../src/client", () => ({ client: api }));
vi.mock("../src/components/familiar/FamiliarStage", () => ({
  FamiliarStage: () => <span>Familiar portrait</span>,
}));
vi.mock("../src/components/jarvis/JarvisStage", () => ({
  JarvisStage: () => <span>Jarvis portrait</span>,
}));

import { RoutinesView } from "../src/components/RoutinesView";

const routine = {
  version: 1 as const,
  name: "Morning priorities",
  goal: "Review overnight changes",
  companion_id: "familiar" as const,
  notify: { completion: true },
};
const summary = {
  id: "morning-priorities",
  version: "1.0.0",
  source: "precreated" as const,
  intent_tags: ["routine"],
  status: "active" as const,
  routine,
  schedule: null,
};

beforeEach(() => {
  window.location.hash = "#/automations";
  api.workflows.mockResolvedValue({ workflows: [summary] });
  api.workflow.mockResolvedValue({
    ...summary,
    definition: { steps: [], _boltrig_routine: routine },
  });
  api.upsertWorkflow.mockResolvedValue({ status: "ok", id: summary.id });
  api.triggerWorkflow.mockResolvedValue({
    status: "queued",
    run_id: "run-1",
    conversation_id: "routine-chat-1",
  });
  api.scheduleWorkflow.mockResolvedValue({ status: "ok" });
  api.unscheduleWorkflow.mockResolvedValue({ status: "ok" });
  api.invokeApprovalState.mockResolvedValue({ status: "approved" });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("conversational routines v1", () => {
  it("shows simple saved routines without exposing the legacy graph or Advanced", async () => {
    render(<RoutinesView />);

    expect(await screen.findByRole("button", { name: /Morning priorities/ })).toBeTruthy();
    expect(screen.queryByText("Advanced")).toBeNull();
    expect(document.querySelector(".routine-canvas")).toBeNull();
    expect(screen.getByText(/Follow each run as a chat/)).toBeTruthy();
  });

  it("authors one closed plain-language routine contract", async () => {
    render(<RoutinesView />);
    fireEvent.click(await screen.findByRole("button", { name: "New routine" }));
    fireEvent.change(screen.getByLabelText("Routine name"), {
      target: { value: "Daily customer pulse" },
    });
    fireEvent.change(screen.getByLabelText("Routine goal"), {
      target: { value: "Review customer signals and tell me what needs attention." },
    });
    fireEvent.click(screen.getByRole("radio", { name: /Jarvis/ }));
    fireEvent.click(screen.getByRole("button", { name: "Save routine" }));

    await waitFor(() => expect(api.upsertWorkflow).toHaveBeenCalledTimes(1));
    expect(api.upsertWorkflow.mock.calls[0][0]).toMatchObject({
      version: "1.0.0",
      intent_tags: ["routine"],
      definition: {
        steps: [],
        _boltrig_routine: {
          version: 1,
          name: "Daily customer pulse",
          goal: "Review customer signals and tell me what needs attention.",
          companion_id: "jarvis",
          notify: { completion: true },
        },
      },
    });
  });

  it("opens the conversation allocated for a manual occurrence", async () => {
    render(<RoutinesView />);
    fireEvent.click(await screen.findByRole("button", { name: /Morning priorities/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Run now" }));

    await waitFor(() => expect(window.location.hash).toBe("#/chat/routine-chat-1"));
    expect(api.triggerWorkflow).toHaveBeenCalledWith("morning-priorities", {}, undefined);
  });

  it("shows an unscheduled routine as manual until timing is explicitly saved", async () => {
    render(<RoutinesView />);
    fireEvent.click(await screen.findByRole("button", { name: /Morning priorities/ }));

    const timing = await screen.findByLabelText("Routine timing") as HTMLSelectElement;
    expect(timing.value).toBe("manual");
    fireEvent.change(timing, { target: { value: "weekdays" } });
    fireEvent.change(screen.getByLabelText("Routine time"), { target: { value: "08:15" } });
    fireEvent.click(screen.getByRole("button", { name: "Save timing" }));

    await waitFor(() => expect(api.scheduleWorkflow).toHaveBeenCalledWith(
      "morning-priorities",
      { cron: "15 8 * * 1-5", timezone: expect.any(String) },
      undefined,
    ));
  });
});
