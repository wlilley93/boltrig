// @vitest-environment happy-dom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  capabilityBindings: vi.fn(),
  capabilityCatalogue: vi.fn(),
  routingPolicies: vi.fn(),
  invoke: vi.fn(),
  invokeApprovalState: vi.fn(),
}));

vi.mock("../src/client", () => ({ client: api }));

import { CapabilityCataloguePanel } from "../src/components/integrations/CapabilityCataloguePanel";
import { CapabilityReviewPanel } from "../src/components/integrations/CapabilityReviewPanel";
import { RoutingRulesPanel } from "../src/components/integrations/RoutingRulesPanel";
import { connectionRowMeta } from "../src/components/integrations/ConnectionSurface";
import {
  selectionForTab,
  tabFromSelection,
} from "../src/components/integrations/capabilityTabs";

function binding(overrides: Record<string, unknown> = {}) {
  return {
    binding_id: "cb:open",
    capability: "matter.open@1",
    capability_id: "matter.open",
    capability_version: 1,
    status: "proposed",
    trust_level: "untrusted",
    priority: 100,
    created_from: "mapping_pack",
    reviewed_by: null,
    workspace_predicate: null,
    source_operation_id: "opbox.create_matter",
    source_operation: {
      id: "opbox.create_matter",
      provider: "opbox",
      title: "Create matter",
      description: "Open a new matter for a client",
      consequence_hint: "medium",
    },
    schema_pinned: true,
    schema_current: true,
    connection: {
      id: "pconn:opbox",
      label: "Opbox",
      provider: "opbox",
      status: "active",
      health: "ok",
      eligible: true,
    },
    ...overrides,
  };
}

beforeEach(() => {
  api.capabilityBindings.mockResolvedValue({
    status: "proposed",
    bindings: [binding()],
    needs_review: 1,
  });
  api.capabilityCatalogue.mockResolvedValue({ capabilities: [] });
  api.routingPolicies.mockResolvedValue({ routing_policies: [] });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

// --- the tab vocabulary ------------------------------------------------------

it("treats an unknown or absent tab as the connections list", () => {
  expect(tabFromSelection(null)).toBe("connections");
  expect(tabFromSelection("nonsense")).toBe("connections");
  expect(tabFromSelection("review")).toBe("review");
  // The default clears the hash segment, so a saved #/integrations link keeps
  // meaning what it always meant.
  expect(selectionForTab("connections")).toBeNull();
  expect(selectionForTab("review")).toBe("review");
});

// --- the row meta ------------------------------------------------------------

it("counts canonical capabilities, and falls back only when the field is absent", () => {
  expect(connectionRowMeta({
    enabled_tools: ["opbox.a", "opbox.b", "opbox.c"],
    enabled_capabilities: ["matter.open"],
  } as never)).toBe("1 capability");
  // Tools registered, nothing mapped yet: a real state, and "0 capabilities"
  // would read as broken.
  expect(connectionRowMeta({
    enabled_tools: ["opbox.a", "opbox.b"],
    enabled_capabilities: [],
  } as never)).toBe("2 verbs, none mapped");
  // ABSENT, not empty: an older kernel omits the field, and reporting nothing
  // there would describe a connection with no surface at all.
  expect(connectionRowMeta({ enabled_tools: ["opbox.a"] } as never)).toBe("1 verb");
  expect(connectionRowMeta(null)).toBeNull();
});

// --- the queue ---------------------------------------------------------------

it("shows the evidence a reviewer decides on", async () => {
  render(<CapabilityReviewPanel />);
  await waitFor(() => expect(screen.getByText("matter.open@1")).toBeTruthy());
  expect(screen.getByText(/Open a new matter for a client/)).toBeTruthy();
  expect(screen.getByText(/Opbox · opbox\.create_matter/)).toBeTruthy();
  expect(screen.getByText("1 waiting")).toBeTruthy();
  expect(api.capabilityBindings).toHaveBeenCalledWith("proposed");
});

it("surfaces schema drift, which is what withdrew the approval", async () => {
  api.capabilityBindings.mockResolvedValue({
    status: null,
    bindings: [binding({ status: "approved", schema_current: false })],
    needs_review: 0,
  });
  render(<CapabilityReviewPanel />);
  await waitFor(() => expect(screen.getByText("schema drifted")).toBeTruthy());
  // The counterweight: an in-sync binding says nothing, so the badge is a
  // finding rather than decoration on every row.
  cleanup();
  api.capabilityBindings.mockResolvedValue({
    status: null,
    bindings: [binding({ status: "approved" })],
    needs_review: 0,
  });
  render(<CapabilityReviewPanel />);
  await waitFor(() => expect(screen.getByText("approved")).toBeTruthy());
  expect(screen.queryByText("schema drifted")).toBeNull();
});

it("offers a decision only on a proposed binding", async () => {
  api.capabilityBindings.mockResolvedValue({
    status: null,
    bindings: [binding({ status: "approved" }), binding({ binding_id: "cb:close" })],
    needs_review: 1,
  });
  render(<CapabilityReviewPanel />);
  await waitFor(() => expect(screen.getAllByText("matter.open@1").length).toBe(2));
  // One Approve, not two: an already-approved binding is not re-approvable from
  // the queue, and offering the button would invite a governed no-op.
  expect(screen.getAllByRole("button", { name: "Approve" }).length).toBe(1);
});

it("approves through the governed lane and reloads rather than assuming", async () => {
  api.invoke.mockResolvedValue({ status: "ok", result: {} });
  render(<CapabilityReviewPanel />);
  await waitFor(() => expect(screen.getByText("matter.open@1")).toBeTruthy());

  api.capabilityBindings.mockResolvedValue({
    status: "proposed",
    bindings: [],
    needs_review: 0,
  });
  fireEvent.click(screen.getByRole("button", { name: "Approve" }));

  await waitFor(() => expect(api.invoke).toHaveBeenCalled());
  const request = api.invoke.mock.calls[0][0];
  expect(request.verb).toBe("control.capability_binding.approve");
  expect(request.params).toEqual({ binding_id: "cb:open" });
  expect(typeof request.idempotency_key).toBe("string");
  // The panel re-reads rather than editing its own list, so what it shows is
  // what the kernel says and never what it hoped.
  await waitFor(() => expect(api.capabilityBindings).toHaveBeenCalledTimes(2));
});

it("holds a pending decision open instead of reporting it as applied", async () => {
  api.invoke.mockResolvedValue({
    status: "pending_human",
    hitl_request_id: "hitl-1",
  });
  render(<CapabilityReviewPanel />);
  await waitFor(() => expect(screen.getByText("matter.open@1")).toBeTruthy());
  fireEvent.click(screen.getByRole("button", { name: "Approve" }));
  // TWO notices, and both matter: the panel's own message, and the finalizer's
  // standing offer to redeem the exact approval once a human answers it.
  await waitFor(() => expect(
    screen.getAllByText(/waiting for approval/).length,
  ).toBe(2));
  expect(screen.getByRole("button", {
    name: /Check approval and apply exact change/,
  })).toBeTruthy();
  // Still listed and still proposed: nothing was published.
  expect(screen.getByText("proposed")).toBeTruthy();
});

it("says the queue is unavailable rather than showing it as empty", async () => {
  api.capabilityBindings.mockRejectedValue(new Error("nope"));
  render(<CapabilityReviewPanel />);
  await waitFor(() => expect(
    screen.getByText(/review queue is unavailable/),
  ).toBeTruthy());
  expect(screen.queryByText(/No bindings here/)).toBeNull();
});

// --- catalogue and rules -----------------------------------------------------

it("reports a capability with no approved implementation as not routable", async () => {
  api.capabilityCatalogue.mockResolvedValue({
    capabilities: [
      {
        capability_id: "matter.close",
        implementations: 1,
        approved: 0,
        needs_review: 1,
        providers: ["opbox"],
        routing_policies: 0,
      },
      {
        capability_id: "matter.open",
        implementations: 2,
        approved: 2,
        needs_review: 0,
        providers: ["opbox"],
        routing_policies: 1,
      },
    ],
  });
  render(<CapabilityCataloguePanel />);
  await waitFor(() => expect(screen.getByText("not routable")).toBeTruthy());
  expect(screen.getByText("1 routable of 2")).toBeTruthy();
  expect(screen.getByText(/No rule: selection falls to binding priority/)).toBeTruthy();
});

it("says why there are no rules instead of showing an empty table", async () => {
  render(<RoutingRulesPanel />);
  await waitFor(() => expect(
    screen.getByText(/highest-priority approved binding/),
  ).toBeTruthy());
  expect(screen.getByText("0 in force")).toBeTruthy();
});
