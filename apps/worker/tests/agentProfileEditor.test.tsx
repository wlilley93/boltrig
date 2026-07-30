// @vitest-environment happy-dom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  agentCapabilities: vi.fn(),
  invoke: vi.fn(),
  invokeApprovalState: vi.fn(),
  modelEndpoints: vi.fn(),
}));

vi.mock("../src/client", () => ({ client: api }));

import { AgentProfileEditor } from "../src/components/AgentProfileEditor";

beforeEach(() => {
  api.agentCapabilities.mockResolvedValue({ agent_capabilities: [] });
  api.modelEndpoints.mockResolvedValue({ endpoints: [] });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

it("authors only the runtime's canonical expensive cost tier", async () => {
  api.invoke.mockResolvedValue({ status: "ok", result: {} });

  render(
    <AgentProfileEditor
      onSaved={vi.fn()}
      onCancel={vi.fn()}
    />,
  );

  expect(screen.queryByRole("option", { name: "Premium" })).toBeNull();
  expect(screen.getByRole("option", { name: "Expensive" })).toBeTruthy();
  fireEvent.change(screen.getByLabelText("Name"), {
    target: { value: "researcher" },
  });
  fireEvent.change(screen.getByLabelText("Cost tier"), {
    target: { value: "expensive" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Request profile change" }));

  await waitFor(() => expect(api.invoke).toHaveBeenCalledWith(
    expect.objectContaining({
      params: expect.objectContaining({ cost_tier: "expensive" }),
    }),
  ));
});

it("continues only the exact cloned profile request after approval", async () => {
  const onSaved = vi.fn();
  api.invoke
    .mockResolvedValueOnce({
      status: "pending_human",
      hitl_request_id: "approval-profile",
    })
    .mockResolvedValueOnce({ status: "ok", output: {} });
  api.invokeApprovalState.mockResolvedValue({ status: "approved" });

  render(
    <AgentProfileEditor
      onSaved={onSaved}
      onCancel={vi.fn()}
    />,
  );

  fireEvent.change(screen.getByLabelText("Name"), {
    target: { value: "researcher" },
  });
  fireEvent.change(screen.getByLabelText("Maximum delegation depth"), {
    target: { value: "4" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Request profile change" }));

  await screen.findByText("Agent profile change is waiting for approval");
  const firstRequest = api.invoke.mock.calls[0][0];
  fireEvent.click(screen.getByRole("button", {
    name: "Check approval and apply exact change",
  }));

  await waitFor(() => expect(api.invokeApprovalState).toHaveBeenCalledWith(
    "approval-profile",
  ));
  await waitFor(() => expect(api.invoke).toHaveBeenNthCalledWith(2, {
    ...firstRequest,
    approval_id: "approval-profile",
  }));
  expect(onSaved).toHaveBeenCalledTimes(1);
});

it("invalidates a held profile request on edit", async () => {
  api.invoke.mockResolvedValue({
    status: "pending_human",
    hitl_request_id: "approval-stale-profile",
  });

  render(
    <AgentProfileEditor
      onSaved={vi.fn()}
      onCancel={vi.fn()}
    />,
  );
  fireEvent.change(screen.getByLabelText("Name"), {
    target: { value: "researcher" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Request profile change" }));
  await screen.findByText("Agent profile change is waiting for approval");

  fireEvent.change(screen.getByLabelText("Cost tier"), {
    target: { value: "expensive" },
  });

  expect(await screen.findByText("Agent profile change changed")).toBeTruthy();
  expect(screen.queryByRole("button", {
    name: "Check approval and apply exact change",
  })).toBeNull();
  expect(api.invoke).toHaveBeenCalledTimes(1);
});

it("refreshes canonical profiles without inferring success for consumed approval", async () => {
  const onSaved = vi.fn();
  api.agentCapabilities.mockResolvedValueOnce({
    agent_capabilities: [{
      name: "researcher",
      runtime: "codex",
      supported_skills: ["canonical"],
      max_depth: 5,
      is_ephemeral: false,
      cost_tier: "cheap",
      model_endpoint: null,
    }],
  });
  api.invoke.mockResolvedValue({
    status: "pending_human",
    hitl_request_id: "approval-consumed-profile",
  });
  api.invokeApprovalState.mockResolvedValue({ status: "consumed" });

  render(
    <AgentProfileEditor
      onSaved={onSaved}
      onCancel={vi.fn()}
    />,
  );
  fireEvent.change(screen.getByLabelText("Name"), {
    target: { value: "researcher" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Request profile change" }));
  await screen.findByText("Agent profile change is waiting for approval");
  fireEvent.click(screen.getByRole("button", {
    name: "Check approval and apply exact change",
  }));

  expect(await screen.findByText(
    "Agent profile change approval was already consumed",
  )).toBeTruthy();
  expect(api.agentCapabilities).toHaveBeenCalledTimes(1);
  expect(
    (screen.getByLabelText("Maximum delegation depth") as HTMLInputElement).value,
  ).toBe("5");
  expect(
    (screen.getByLabelText("Supported skill patterns") as HTMLTextAreaElement).value,
  ).toBe("canonical");
  expect(onSaved).not.toHaveBeenCalled();
  expect(api.invoke).toHaveBeenCalledTimes(1);
});
