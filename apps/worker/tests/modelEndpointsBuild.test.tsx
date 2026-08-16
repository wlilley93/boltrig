// @vitest-environment happy-dom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  invoke: vi.fn(),
  invokeApprovalState: vi.fn(),
  modelEndpoint: vi.fn(),
  modelEndpoints: vi.fn(),
  modelPolicy: vi.fn(),
  restoreModelEndpoint: vi.fn(),
  retireModelEndpoint: vi.fn(),
}));

vi.mock("../src/client", () => ({ client: api }));

import { ModelEndpointsBuild } from "../src/components/build/ModelEndpointsBuild";

const active = {
  id: "active-endpoint",
  kind: "openai",
  model: "served-model",
  data_class: "standard",
  is_active: true,
  status: "active" as const,
};
const retired = {
  ...active,
  id: "retired-endpoint",
  model: "withdrawn-model",
  is_active: false,
  status: "retired" as const,
};

beforeEach(() => {
  api.modelEndpoints.mockResolvedValue({ endpoints: [active, retired] });
  api.modelPolicy.mockResolvedValue({
    policy: {
      state: "configured",
      source: "process_start_manifest",
      generation: "1234567890abcdef",
      default: {
        endpoint_id: active.id,
        state: "active",
        serving_state: "inactive_no_consumer",
      },
      sensitive: {
        endpoint_id: "private-local",
        state: "active",
        serving_state: "active_process_policy",
        eligible: true,
      },
      prices: [{
        model: "gpt-governed",
        input_micros_per_token: 0.25,
        output_micros_per_token: 1.5,
      }],
      price_serving_state: "active_process_cost_accountant",
      changes_apply_at: "process_restart",
    },
  });
  api.modelEndpoint.mockImplementation(async (id: string) => ({
    endpoint: {
      ...(id === active.id ? active : retired),
      base_url: "https://models.example.test/v1",
      fallback: active.id,
      references: {
        capabilities: ["researcher"],
        fallbacks: ["secondary"],
      },
    },
  }));
  api.retireModelEndpoint.mockResolvedValue({
    status: "pending_human",
    hitl_request_id: "hitl-retire",
  });
  api.restoreModelEndpoint.mockResolvedValue({
    status: "pending_human",
    hitl_request_id: "hitl-restore",
  });
  api.invokeApprovalState.mockResolvedValue({ status: "approved" });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("Worker model endpoint lifecycle", () => {
  it("distinguishes process policy from stored endpoint inventory", async () => {
    render(<ModelEndpointsBuild />);

    // The section heading exists before either independent request settles, so
    // it is not an async readiness marker. Wait for one fact from each mocked
    // contract before asserting the complete inventory/policy projection.
    expect(await screen.findByText("1/2 active")).toBeTruthy();
    expect(await screen.findByText("private-local · active")).toBeTruthy();
    expect(screen.getByText("Effective model policy")).toBeTruthy();
    expect(screen.getByText("inactive · no serving consumer")).toBeTruthy();
    expect(screen.getByText("gpt-governed")).toBeTruthy();
    expect(screen.getByText("in 0.25 · out 1.5")).toBeTruthy();
    expect(screen.getByText(/Policy changes apply only after process restart/)).toBeTruthy();
  });

  it("keeps retired endpoints visible and exposes only the valid lifecycle action", async () => {
    render(<ModelEndpointsBuild />);

    expect(await screen.findByText("1/2 active")).toBeTruthy();
    expect(screen.getByText("retired · standard")).toBeTruthy();

    fireEvent.click(screen.getByText(retired.id));
    fireEvent.click(await screen.findByRole("button", { name: "Restore endpoint" }));
    await waitFor(() => expect(api.restoreModelEndpoint).toHaveBeenCalledWith(retired.id));
    expect(await screen.findByText(/Restore is waiting for approval/)).toBeTruthy();

    fireEvent.click(screen.getByText(active.id));
    fireEvent.click(await screen.findByRole("button", { name: "Retire endpoint" }));
    await waitFor(() => expect(api.retireModelEndpoint).toHaveBeenCalledWith(active.id));
    expect(screen.queryByRole("button", { name: "Restore endpoint" })).toBeNull();
  });

  it("replays the same lifecycle SDK method and endpoint after approval", async () => {
    api.restoreModelEndpoint
      .mockResolvedValueOnce({
        status: "pending_human",
        hitl_request_id: "hitl-restore-exact",
      })
      .mockResolvedValueOnce({
        status: "ok",
        id: retired.id,
        model_endpoint_status: "active",
      });

    render(<ModelEndpointsBuild />);
    fireEvent.click(await screen.findByText(retired.id));
    fireEvent.click(await screen.findByRole("button", { name: "Restore endpoint" }));
    await screen.findByText("Model endpoint restore is waiting for approval");
    fireEvent.click(screen.getByRole("button", {
      name: "Check approval and apply exact change",
    }));

    await waitFor(() => expect(api.invokeApprovalState).toHaveBeenCalledWith(
      "hitl-restore-exact",
    ));
    await waitFor(() => expect(api.restoreModelEndpoint).toHaveBeenNthCalledWith(
      2,
      retired.id,
      "hitl-restore-exact",
    ));
    expect(await screen.findByText(`${retired.id} restored.`)).toBeTruthy();
  });

  it("replays the exact cloned endpoint upsert request", async () => {
    api.invoke
      .mockResolvedValueOnce({
        status: "pending_human",
        hitl_request_id: "hitl-upsert-exact",
      })
      .mockResolvedValueOnce({ status: "ok", output: {} });

    render(<ModelEndpointsBuild />);
    await screen.findByText("1/2 active");
    fireEvent.change(screen.getByLabelText("Identifier"), {
      target: { value: "new-endpoint" },
    });
    fireEvent.change(screen.getByLabelText("Model"), {
      target: { value: "gpt-approved" },
    });
    fireEvent.click(screen.getByRole("button", {
      name: "Request endpoint change",
    }));

    await screen.findByText("Model endpoint change is waiting for approval");
    const firstRequest = api.invoke.mock.calls[0][0];
    fireEvent.click(screen.getByRole("button", {
      name: "Check approval and apply exact change",
    }));

    await waitFor(() => expect(api.invoke).toHaveBeenNthCalledWith(2, {
      ...firstRequest,
      approval_id: "hitl-upsert-exact",
    }));
    expect(await screen.findByText("Model endpoint saved.")).toBeTruthy();
  });

  it("invalidates a lifecycle continuation when another endpoint is selected", async () => {
    render(<ModelEndpointsBuild />);
    fireEvent.click(await screen.findByText(retired.id));
    fireEvent.click(await screen.findByRole("button", { name: "Restore endpoint" }));
    await screen.findByText("Model endpoint restore is waiting for approval");

    fireEvent.click(screen.getByText(active.id));

    expect(await screen.findByText("Model endpoint restore changed")).toBeTruthy();
    expect(screen.queryByRole("button", {
      name: "Check approval and apply exact change",
    })).toBeNull();
  });

  it("refreshes canonical endpoint state without inferring consumed success", async () => {
    api.invokeApprovalState.mockResolvedValue({ status: "consumed" });

    render(<ModelEndpointsBuild />);
    fireEvent.click(await screen.findByText(retired.id));
    fireEvent.click(await screen.findByRole("button", { name: "Restore endpoint" }));
    await screen.findByText("Model endpoint restore is waiting for approval");
    fireEvent.click(screen.getByRole("button", {
      name: "Check approval and apply exact change",
    }));

    expect(await screen.findByText(
      "Model endpoint restore approval was already consumed",
    )).toBeTruthy();
    await waitFor(() => expect(api.modelEndpoints).toHaveBeenCalledTimes(2));
    expect(api.restoreModelEndpoint).toHaveBeenCalledTimes(1);
  });
});
