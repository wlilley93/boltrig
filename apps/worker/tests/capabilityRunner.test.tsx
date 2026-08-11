// @vitest-environment happy-dom

import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  capabilities: vi.fn(),
  invoke: vi.fn(),
  invokeApprovalState: vi.fn(),
}));

vi.mock("../src/client", () => ({ client: api }));

import { CapabilityRunner } from "../src/components/build/CapabilityRunner";

const safeVerb = {
  id: "ticket.create",
  noun: "ticket",
  consequence: "high",
  idempotency_mode: "cacheable",
  binding: { target_type: "adapter", target_ref: "jira" },
  health: "ok",
  input_schema: {
    type: "object",
    additionalProperties: false,
    required: ["title"],
    properties: {
      title: { type: "string", description: "Short ticket title." },
      priority: { type: "integer", minimum: 1, maximum: 5 },
      notify: { type: "boolean" },
      labels: { type: "array", items: { type: "string" } },
    },
  },
  output_schema: {
    type: "object",
    additionalProperties: false,
    properties: {
      ticket_id: { type: "string" },
    },
  },
};

beforeEach(() => {
  api.capabilities.mockResolvedValue({ verbs: [safeVerb] });
  api.invoke.mockResolvedValue({
    status: "ok",
    output: { ticket_id: "T-42", raw_adapter_payload: "not-for-worker" },
  });
  api.invokeApprovalState.mockResolvedValue({ status: "pending" });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("Worker safe capability invocation", () => {
  it("invokes only a discovered capability with generated typed parameters", async () => {
    render(<CapabilityRunner />);

    expect(await screen.findByRole("combobox", { name: "Capability" })).toBeTruthy();
    expect(screen.queryByLabelText(/Parameters \(JSON/i)).toBeNull();
    expect(screen.queryByLabelText(/Context/i)).toBeNull();
    expect(screen.queryByLabelText(/Approval id/i)).toBeNull();
    expect(screen.queryByLabelText(/Credential/i)).toBeNull();

    fireEvent.change(screen.getByLabelText("Title (required)"), {
      target: { value: "Investigate outage" },
    });
    fireEvent.change(screen.getByLabelText("Priority"), {
      target: { value: "4" },
    });
    fireEvent.change(screen.getByLabelText("Notify"), {
      target: { value: "false" },
    });
    fireEvent.change(screen.getByLabelText("Labels"), {
      target: { value: "urgent\ncustomer" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run through kernel" }));

    await waitFor(() => expect(api.invoke).toHaveBeenCalledWith({
      noun: "ticket",
      verb: "ticket.create",
      params: {
        title: "Investigate outage",
        priority: 4,
        notify: false,
        labels: ["urgent", "customer"],
      },
      idempotency_key: expect.any(String),
    }));
    expect(await screen.findByLabelText("Completed receipt")).toBeTruthy();
    expect(screen.getByText(/"ticket_id": "T-42"/)).toBeTruthy();
    expect(screen.queryByText(/raw_adapter_payload/)).toBeNull();
    expect(screen.queryByText(/not-for-worker/)).toBeNull();
  });

  it("discards a late result after another capability is selected", async () => {
    const alternateVerb = {
      ...safeVerb,
      id: "report.inspect",
      noun: "report",
      consequence: "low",
      input_schema: {
        type: "object",
        additionalProperties: false,
        properties: {},
      },
      output_schema: {
        type: "object",
        additionalProperties: false,
        properties: {
          diagnostic: { type: "string" },
        },
      },
    };
    api.capabilities.mockResolvedValue({
      verbs: [{
        ...safeVerb,
        output_schema: {
          type: "object",
          properties: {
            ticket_id: { type: "string" },
          },
        },
      }, alternateVerb],
    });
    let resolveInvoke: (result: unknown) => void = () => undefined;
    api.invoke.mockImplementation(() => new Promise((resolve) => {
      resolveInvoke = resolve;
    }));

    render(<CapabilityRunner />);
    const picker = await screen.findByRole("combobox", { name: "Capability" });
    fireEvent.change(screen.getByLabelText("Title (required)"), {
      target: { value: "Investigate outage" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run through kernel" }));
    await waitFor(() => expect(api.invoke).toHaveBeenCalledTimes(1));

    fireEvent.change(picker, {
      target: { value: JSON.stringify([alternateVerb.noun, alternateVerb.id]) },
    });
    expect(await screen.findByRole("heading", {
      name: "report.inspect",
    })).toBeTruthy();

    await act(async () => {
      resolveInvoke({
        status: "ok",
        output: {
          ticket_id: "T-42",
          diagnostic: "A-only output must not be projected through B",
        },
      });
    });

    expect(screen.queryByLabelText("Completed receipt")).toBeNull();
    expect(screen.queryByText(/A-only output/)).toBeNull();
  });

  it("renders secret or unsupported schemas as unavailable without a raw bypass", async () => {
    api.capabilities.mockResolvedValue({
      verbs: [{
        ...safeVerb,
        id: "integration.configure",
        input_schema: {
          type: "object",
          properties: { api_key: { type: "string" } },
        },
      }],
    });
    render(<CapabilityRunner />);

    expect(await screen.findByText("Invocation unavailable for this schema")).toBeTruthy();
    expect(screen.getByText(/secret-shaped fields require/)).toBeTruthy();
    expect(screen.queryByLabelText(/Api key/i)).toBeNull();
    expect(screen.queryByRole("button", { name: "Run through kernel" })).toBeNull();
    expect(api.invoke).not.toHaveBeenCalled();
  });

  it("does not dispatch invalid string constraints", async () => {
    api.capabilities.mockResolvedValue({
      verbs: [{
        ...safeVerb,
        input_schema: {
          type: "object",
          additionalProperties: false,
          required: ["title", "labels"],
          properties: {
            title: { type: "string", minLength: 5, pattern: "^[A-Z]" },
            labels: {
              type: "array",
              items: { type: "string", minLength: 3 },
            },
          },
        },
      }],
    });
    render(<CapabilityRunner />);
    await screen.findByRole("combobox", { name: "Capability" });
    fireEvent.change(screen.getByLabelText("Title (required)"), {
      target: { value: "no" },
    });
    fireEvent.change(screen.getByLabelText("Labels (required)"), {
      target: { value: "x" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run through kernel" }));

    expect(await screen.findByText("Enter at least 5 characters.")).toBeTruthy();
    expect(screen.getByText("Enter at least 3 characters.")).toBeTruthy();
    expect(api.invoke).not.toHaveBeenCalled();
  });

  it("retries an ambiguous cacheable invocation with the exact same key and params", async () => {
    api.invoke
      .mockResolvedValueOnce({ status: "unavailable", reason: "gateway offline" })
      .mockResolvedValueOnce({ status: "ok", output: { ticket_id: "T-44" } });
    render(<CapabilityRunner />);
    await screen.findByRole("combobox", { name: "Capability" });
    fireEvent.change(screen.getByLabelText("Title (required)"), {
      target: { value: "Investigate outage" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run through kernel" }));
    await screen.findByLabelText("Unavailable receipt");
    fireEvent.click(screen.getByRole("button", { name: "Retry same invocation" }));
    await screen.findByLabelText("Completed receipt");

    expect(api.invoke).toHaveBeenCalledTimes(2);
    expect(api.invoke.mock.calls[1]?.[0]).toEqual(api.invoke.mock.calls[0]?.[0]);
  });

  it("finalizes an approved invocation with the exact component-held request", async () => {
    api.invoke
      .mockResolvedValueOnce({
        status: "pending_human",
        hitl_request_id: "approval/42",
      })
      .mockResolvedValueOnce({
        status: "ok",
        output: { ticket_id: "T-45" },
      });
    api.invokeApprovalState.mockResolvedValue({ status: "approved" });
    render(<CapabilityRunner />);
    await screen.findByRole("combobox", { name: "Capability" });
    fireEvent.change(screen.getByLabelText("Title (required)"), {
      target: { value: "Investigate outage" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run through kernel" }));
    await screen.findByLabelText("Pending human receipt");
    fireEvent.click(screen.getByRole("button", { name: "Check approval and continue" }));

    await waitFor(() => expect(api.invoke).toHaveBeenCalledTimes(2));
    const first = api.invoke.mock.calls[0]?.[0];
    expect(api.invokeApprovalState).toHaveBeenCalledWith("approval/42");
    expect(api.invoke.mock.calls[1]?.[0]).toEqual({
      ...first,
      approval_id: "approval/42",
    });
    expect(await screen.findByLabelText("Completed receipt")).toBeTruthy();
  });

  it("refuses pending finalization after generated inputs change", async () => {
    api.invoke.mockResolvedValue({
      status: "pending_human",
      hitl_request_id: "approval/43",
    });
    render(<CapabilityRunner />);
    await screen.findByRole("combobox", { name: "Capability" });
    fireEvent.change(screen.getByLabelText("Title (required)"), {
      target: { value: "Investigate outage" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run through kernel" }));
    await screen.findByLabelText("Pending human receipt");
    fireEvent.change(screen.getByLabelText("Title (required)"), {
      target: { value: "Different request" },
    });

    expect(await screen.findByLabelText("invalidated approval receipt")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Check approval and continue" })).toBeNull();
    expect(api.invokeApprovalState).not.toHaveBeenCalled();
    expect(api.invoke).toHaveBeenCalledTimes(1);
  });

  it.each(["rejected", "expired"] as const)(
    "renders an approval %s state without executing",
    async (status) => {
      api.invoke.mockResolvedValue({
        status: "pending_human",
        hitl_request_id: `approval/${status}`,
      });
      api.invokeApprovalState.mockResolvedValue({ status });
      render(<CapabilityRunner />);
      await screen.findByRole("combobox", { name: "Capability" });
      fireEvent.change(screen.getByLabelText("Title (required)"), {
        target: { value: "Investigate outage" },
      });
      fireEvent.click(screen.getByRole("button", { name: "Run through kernel" }));
      await screen.findByLabelText("Pending human receipt");
      fireEvent.click(screen.getByRole("button", { name: "Check approval and continue" }));

      expect(await screen.findByLabelText(`${status} approval receipt`)).toBeTruthy();
      expect(api.invoke).toHaveBeenCalledTimes(1);
    },
  );

  it("does not invent cacheable recovery for a replay-disabled capability", async () => {
    api.capabilities.mockResolvedValue({
      verbs: [{ ...safeVerb, idempotency_mode: "disabled" }],
    });
    api.invoke.mockResolvedValue({
      status: "pending_human",
      hitl_request_id: "approval/consumed",
    });
    api.invokeApprovalState.mockResolvedValue({ status: "consumed" });
    render(<CapabilityRunner />);
    await screen.findByRole("combobox", { name: "Capability" });
    fireEvent.change(screen.getByLabelText("Title (required)"), {
      target: { value: "Investigate outage" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run through kernel" }));
    await screen.findByLabelText("Pending human receipt");
    expect(api.invoke.mock.calls[0]?.[0]).not.toHaveProperty("idempotency_key");
    fireEvent.click(screen.getByRole("button", { name: "Check approval and continue" }));

    expect(await screen.findByLabelText("consumed approval receipt")).toBeTruthy();
    expect(api.invoke).toHaveBeenCalledTimes(1);
  });

  it.each([
    [
      { status: "pending_human", hitl_request_id: "approval/42" },
      "Pending human receipt",
      "Waiting for approval in the originating chat",
    ],
    [
      { status: "denied", reason: "grant revoked" },
      "Denied receipt",
      "The kernel refused this invocation",
    ],
    [
      { status: "unavailable", reason: "adapter offline" },
      "Unavailable receipt",
      "The invocation service is unavailable",
    ],
    [
      { status: "degraded", output: { ticket_id: "T-43" } },
      "Degraded receipt",
      "The capability returned a degraded result",
    ],
  ])("preserves the %s invocation receipt distinctly", async (result, label, heading) => {
    api.invoke.mockResolvedValue(result);
    render(<CapabilityRunner />);
    await screen.findByRole("combobox", { name: "Capability" });
    fireEvent.change(screen.getByLabelText("Title (required)"), {
      target: { value: "Investigate outage" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run through kernel" }));

    expect(await screen.findByLabelText(label)).toBeTruthy();
    expect(screen.getByText(heading)).toBeTruthy();
  });
});
