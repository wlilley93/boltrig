// @vitest-environment happy-dom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  applyPermanentFleet: vi.fn(),
  invokeApprovalState: vi.fn(),
  modelEndpoints: vi.fn(),
  permanentFleet: vi.fn(),
}));

vi.mock("../src/client", () => ({ client: api }));

import { PermanentFleetTopology } from "../src/components/PermanentFleetTopology";

const hierarchy = {
  chief: {
    name: "chief-of-staff",
    routing_id: "cos",
    purpose: "Coordinate approved work",
    brief: "",
    runtime: "codex" as const,
    model_endpoint: null,
    supported_skills: ["*"],
    max_depth: 4,
    cost_tier: "standard" as const,
    budget: null,
  },
  departments: [{
    name: "research-head",
    routing_id: "research",
    purpose: "Own research",
    brief: "",
    runtime: "codex" as const,
    model_endpoint: null,
    supported_skills: ["research"],
    max_depth: 3,
    cost_tier: "standard" as const,
    budget: null,
  }],
};

const canonical = {
  status: "configured" as const,
  hierarchy,
  generation: "fleet-generation-7",
  revision: 7,
  apply_state: "restart_required" as const,
  hot_applied: false as const,
  profiles_reconciled: false,
  reconcile_at: "next_manifest_apply_or_redeploy" as const,
  observations: [],
};

beforeEach(() => {
  api.modelEndpoints.mockResolvedValue({ endpoints: [] });
  api.permanentFleet.mockResolvedValue(canonical);
  api.invokeApprovalState.mockResolvedValue({ status: "approved" });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("Permanent fleet exact approval continuation", () => {
  it("renders construction evidence without claiming runtime liveness", async () => {
    api.permanentFleet.mockResolvedValue({
      ...canonical,
      apply_state: "startup_applied_liveness_unknown",
      runtime_liveness: "unknown_not_probed_by_startup",
      observations: [{
        worker_id: "opaque-worker",
        generation: canonical.generation,
        status: "applied",
        apply_mode: "startup_snapshot",
        applied_fields: ["runtime", "model_endpoint", "purpose", "brief"],
        inactive_fields: [],
      }],
    });

    render(<PermanentFleetTopology />);

    expect(await screen.findAllByText(
      "policy constructed · liveness unknown",
    )).toHaveLength(2);
    expect(screen.getAllByText(
      /Runtime admission happens only when the head reasons/,
    )).toHaveLength(2);
    expect(screen.queryByText(/not active permanent reasoning/)).toBeNull();
    expect(screen.queryByText(/Not active until a model-backed permanent runtime/)).toBeNull();
  });

  it("replays the exact hierarchy against the same desired revision", async () => {
    api.applyPermanentFleet
      .mockResolvedValueOnce({
        status: "pending_human",
        hitl_request_id: "approval-fleet",
      })
      .mockResolvedValueOnce({
        status: "ok",
        generation: "fleet-generation-8",
        revision: 8,
      });

    render(<PermanentFleetTopology />);
    fireEvent.click(await screen.findByRole("button", { name: "Edit topology" }));
    fireEvent.change(screen.getAllByLabelText("Purpose")[0], {
      target: { value: "Coordinate exact approved work" },
    });
    fireEvent.click(screen.getByRole("button", {
      name: "Request hierarchy change",
    }));

    await screen.findByText(
      "Permanent fleet hierarchy change is waiting for approval",
    );
    const firstHierarchy = api.applyPermanentFleet.mock.calls[0][0];
    fireEvent.click(screen.getByRole("button", {
      name: "Check approval and apply exact change",
    }));

    await waitFor(() => expect(api.invokeApprovalState).toHaveBeenCalledWith(
      "approval-fleet",
    ));
    await waitFor(() => expect(api.applyPermanentFleet).toHaveBeenNthCalledWith(
      2,
      firstHierarchy,
      "approval-fleet",
    ));
    expect(await screen.findByText(/Desired hierarchy saved/)).toBeTruthy();
  });

  it("invalidates the continuation when the form changes or canonical state refreshes", async () => {
    api.applyPermanentFleet.mockResolvedValue({
      status: "pending_human",
      hitl_request_id: "approval-stale-fleet",
    });

    render(<PermanentFleetTopology />);
    fireEvent.click(await screen.findByRole("button", { name: "Edit topology" }));
    fireEvent.click(screen.getByRole("button", {
      name: "Request hierarchy change",
    }));
    await screen.findByText(
      "Permanent fleet hierarchy change is waiting for approval",
    );

    fireEvent.change(screen.getAllByLabelText("Purpose")[0], {
      target: { value: "Changed after review" },
    });
    expect(await screen.findByText(
      "Permanent fleet hierarchy change changed",
    )).toBeTruthy();

    fireEvent.click(screen.getByRole("button", {
      name: "Request hierarchy change",
    }));
    await screen.findByText(
      "Permanent fleet hierarchy change is waiting for approval",
    );
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    expect(await screen.findByText(
      "Permanent fleet hierarchy change changed",
    )).toBeTruthy();
    expect(api.applyPermanentFleet).toHaveBeenCalledTimes(2);
  });

  it("refreshes canonical desired state without inferring consumed success", async () => {
    api.applyPermanentFleet.mockResolvedValue({
      status: "pending_human",
      hitl_request_id: "approval-consumed-fleet",
    });
    api.invokeApprovalState.mockResolvedValue({ status: "consumed" });

    render(<PermanentFleetTopology />);
    fireEvent.click(await screen.findByRole("button", { name: "Edit topology" }));
    fireEvent.click(screen.getByRole("button", {
      name: "Request hierarchy change",
    }));
    await screen.findByText(
      "Permanent fleet hierarchy change is waiting for approval",
    );
    fireEvent.click(screen.getByRole("button", {
      name: "Check approval and apply exact change",
    }));

    expect(await screen.findByText(
      "Permanent fleet hierarchy change approval was already consumed",
    )).toBeTruthy();
    await waitFor(() => expect(api.permanentFleet).toHaveBeenCalledTimes(2));
    expect(api.applyPermanentFleet).toHaveBeenCalledTimes(1);
  });

  it("keeps the department routing-identity input mounted while it is edited", async () => {
    render(<PermanentFleetTopology />);
    fireEvent.click(await screen.findByRole("button", { name: "Edit topology" }));
    const routingInput = screen.getAllByLabelText("Routing identity")[1];
    fireEvent.change(routingInput, { target: { value: "researchops" } });
    expect(screen.getAllByLabelText("Routing identity")[1]).toBe(routingInput);
    expect(routingInput).toHaveProperty("value", "researchops");
  });
});
