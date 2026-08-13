// @vitest-environment happy-dom

import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { BoltrigApiError } from "@wlilley93/boltrig-web-sdk";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  answerQuestion: vi.fn(),
  capabilities: vi.fn(),
  capabilityChangelog: vi.fn(),
  channels: vi.fn(),
  hitl: vi.fn(),
  hitlPolicy: vi.fn(),
  respondHitl: vi.fn(),
  workflow: vi.fn(),
  workflowRuns: vi.fn(),
  workflowScheduleOccurrences: vi.fn(),
  workflows: vi.fn(),
  workflowStats: vi.fn(),
  workflowTriggerFinalizations: vi.fn(),
  workflowTriggers: vi.fn(),
}));

vi.mock("../src/client", () => ({ client: api }));

import { AutomationsView } from "../src/components/AutomationView";
import { InboxQueue } from "../src/components/InboxHitl";

interface Deferred<T> {
  promise: Promise<T>;
  resolve(value: T): void;
}

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((accept) => {
    resolve = accept;
  });
  return { promise, resolve };
}

beforeEach(() => {
  api.hitlPolicy.mockRejectedValue(new Error("not an author"));
  api.workflowScheduleOccurrences.mockImplementation(async (id: string) => ({
    workflow_id: id,
    occurrences: [],
    truncated: false,
    backfill: {
      status: "unavailable",
      reason: "historical_backfill_not_supported_by_canonical_claim",
    },
  }));
  api.capabilities.mockResolvedValue({ verbs: [] });
  api.capabilityChangelog.mockResolvedValue({ changes: [] });
  api.channels.mockResolvedValue({ channels: [] });
  api.workflowRuns.mockImplementation(async (id: string) => ({
    workflow_id: id,
    runs: [],
  }));
  api.workflowStats.mockResolvedValue({ stats: [] });
  api.workflowTriggerFinalizations.mockImplementation(async (id: string) => ({
    workflow_id: id,
    finalizations: [],
  }));
  api.workflowTriggers.mockImplementation(async (id: string) => ({
    workflow_id: id,
    triggers: [],
  }));
});

afterEach(() => {
  cleanup();
  vi.resetAllMocks();
  window.location.hash = "";
});

describe("Inbox primary-surface honesty", () => {
  it("distinguishes initial loading from a successful empty Inbox", async () => {
    const request = deferred<{ requests: [] }>();
    api.hitl.mockReturnValue(request.promise);

    render(<InboxQueue />);

    expect(screen.getByRole("heading", { name: "Loading Inbox" })).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Nothing waiting" })).toBeNull();

    await act(async () => request.resolve({ requests: [] }));
    expect(await screen.findByRole("heading", { name: "Nothing waiting" })).toBeTruthy();
  });

  it.each([
    [403, "Inbox access denied"],
    [503, "Inbox unavailable"],
  ])("renders an honest %s failure state", async (status, title) => {
    api.hitl.mockRejectedValue(new BoltrigApiError(status, {}));

    render(<InboxQueue />);

    expect(await screen.findByRole("heading", { name: title })).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Nothing waiting" })).toBeNull();
  });

  it("keeps a settled request hidden when a stale refresh returns it", async () => {
    const request = {
      id: "approval-stale",
      type: "approval",
      question: "Approve once?",
      options: ["approve"],
    };
    api.hitl.mockResolvedValue({ requests: [request] });
    api.respondHitl.mockResolvedValue({ status: "answered", response_id: "response-a" });

    render(<InboxQueue />);
    fireEvent.click(await screen.findByRole("button", { name: "approve" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm approve" }));
    await waitFor(() => expect(screen.queryByText("Approve once?")).toBeNull());

    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await waitFor(() => expect(api.hitl).toHaveBeenCalledTimes(2));
    expect(screen.queryByText("Approve once?")).toBeNull();
    expect(screen.getByRole("heading", { name: "Nothing waiting" })).toBeTruthy();
  });
});

describe("Automation primary-surface honesty", () => {
  it("distinguishes initial loading from a successful empty workflow library", async () => {
    const request = deferred<{ workflows: [] }>();
    api.workflows.mockReturnValue(request.promise);

    render(<AutomationsView />);

    expect(screen.getByRole("heading", { name: "Loading automations" })).toBeTruthy();
    expect(screen.queryByText("No saved workflows yet.")).toBeNull();

    await act(async () => request.resolve({ workflows: [] }));
    expect(await screen.findByText("No saved workflows yet.")).toBeTruthy();
    expect(screen.getByText(/Repeatable work boltrig can run the same way each time/))
      .toBeTruthy();
    expect(screen.queryByText(/reconciled on a loop|what it queued|held as data/i))
      .toBeNull();
  });

  it.each([
    [403, "Automation access denied"],
    [503, "Automations unavailable"],
  ])("renders an honest %s failure state", async (status, title) => {
    api.workflows.mockRejectedValue(new BoltrigApiError(status, {}));

    render(<AutomationsView />);

    expect(await screen.findByRole("heading", { name: title })).toBeTruthy();
    expect(screen.queryByText("No saved workflows yet.")).toBeNull();
  });

  it("keeps the authorized workflow list without exposing a duplicate refresh bar", async () => {
    api.workflows.mockResolvedValueOnce({
      workflows: [{
        id: "retained-workflow",
        version: "1.0.0",
        source: "precreated",
        status: "active",
        schedule: null,
      }],
    });

    render(<AutomationsView />);
    expect(await screen.findByText("retained-workflow")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Refresh workflows" })).toBeNull();
    expect(screen.getByText("retained-workflow")).toBeTruthy();
  });

  it("never renders workflow A after workflow B is selected", async () => {
    const detailA = deferred<unknown>();
    const detailB = deferred<unknown>();
    api.workflows.mockResolvedValue({
      workflows: [
        {
          id: "workflow-a",
          version: "1.0.0",
          source: "precreated",
          status: "active",
          schedule: null,
        },
        {
          id: "workflow-b",
          version: "1.0.0",
          source: "precreated",
          status: "active",
          schedule: null,
        },
      ],
    });
    api.workflow.mockImplementation((id: string) => (
      id === "workflow-a" ? detailA.promise : detailB.promise
    ));

    render(<AutomationsView />);
    fireEvent.click(await screen.findByRole("button", { name: /workflow-a/ }));
    await waitFor(() => expect(api.workflow).toHaveBeenCalledWith("workflow-a"));
    fireEvent.click(screen.getByRole("button", { name: /workflow-b/ }));
    await waitFor(() => expect(api.workflow).toHaveBeenCalledWith("workflow-b"));

    await act(async () => detailB.resolve({
      id: "workflow-b",
      version: "1.0.0",
      source: "precreated",
      definition: { steps: [] },
      intent_tags: [],
      status: "active",
      schedule: null,
    }));
    expect((await screen.findByLabelText("Workflow id") as HTMLInputElement).value)
      .toBe("workflow-b");

    await act(async () => detailA.resolve({
      id: "workflow-a",
      version: "1.0.0",
      source: "precreated",
      definition: { steps: [] },
      intent_tags: [],
      status: "active",
      schedule: null,
    }));
    expect((screen.getByLabelText("Workflow id") as HTMLInputElement).value)
      .toBe("workflow-b");
  });

  it("locks code while exposing the bounded loop contract", async () => {
    api.workflows.mockResolvedValue({
      workflows: [{
        id: "advanced",
        version: "1.0.0",
        source: "precreated",
        status: "active",
        schedule: null,
      }],
    });
    api.workflow.mockResolvedValue({
      id: "advanced",
      version: "1.0.0",
      source: "precreated",
      definition: {
        steps: [
          {
            id: "script",
            action: "code.run",
            parents: [],
            params: { script: "return 1" },
          },
          {
            id: "repeat",
            action: "flow.loop",
            parents: ["script"],
            params: { items: ["a", "b"] },
          },
          {
            id: "create",
            action: "ticket.create",
            parents: ["repeat"],
            params: { title: null, position: null },
            loop_bindings: { title: "item", position: "index" },
          },
        ],
      },
      intent_tags: [],
      status: "active",
      schedule: null,
    });

    render(<AutomationsView />);
    fireEvent.click(await screen.findByRole("button", { name: /advanced/ }));

    // The editor is now a canvas: each step is a node whose fields live in
    // the inspector rail, one selection at a time. Selecting the preserved
    // code step must show every field locked; selecting the loop must keep
    // the bounded-loop contract visible and editable.
    const rail = await screen.findByLabelText("Routine rail");

    fireEvent.click(await screen.findByRole("button", { name: /^Step script/ }));
    expect((within(rail).getByLabelText("Governed action") as HTMLInputElement).disabled)
      .toBe(true);
    expect((within(rail).getByLabelText("Parameters (JSON object)") as HTMLTextAreaElement).disabled)
      .toBe(true);
    expect((within(rail).getByRole("button", { name: "Remove script" }) as HTMLButtonElement).disabled)
      .toBe(true);
    // The rail states the never-runs contract in both registers (the read-first
    // fact and the locked fields), so more than one match is the honest shape.
    expect(within(rail).getAllByText(/executed=false/).length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole("button", { name: /^Step repeat/ }));
    expect((within(rail).getByLabelText("Governed action") as HTMLInputElement).disabled)
      .toBe(false);
    expect((within(rail).getByLabelText("Parameters (JSON object)") as HTMLTextAreaElement).disabled)
      .toBe(false);
    expect(within(rail).getByText(/at most 100 items/)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: /^Step create/ }));
    const bindings = within(rail).getByLabelText("Loop bindings for create");
    expect((bindings as HTMLTextAreaElement).disabled).toBe(false);
    expect((bindings as HTMLTextAreaElement).value).toContain("\"title\": \"item\"");
    expect((bindings as HTMLTextAreaElement).value).toContain("\"position\": \"index\"");
  });
});
