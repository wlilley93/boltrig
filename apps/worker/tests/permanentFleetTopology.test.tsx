// @vitest-environment happy-dom

import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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

async function openTopologyEditor() {
  fireEvent.click(await screen.findByRole("button", { name: "Inspect chief-of-staff" }));
  fireEvent.click(screen.getByRole("button", { name: "Edit topology" }));
}

type FleetOverlayKind = "inspector" | "handoff" | "editor";

const modalCases: ReadonlyArray<{
  kind: FleetOverlayKind;
  label: string;
  initialFocus: string;
  leavesInspectorOpen: boolean;
}> = [
  {
    kind: "inspector",
    label: "chief-of-staff fleet inspector",
    initialFocus: "Close fleet inspector",
    leavesInspectorOpen: false,
  },
  {
    kind: "handoff",
    label: "Create a profile from chief-of-staff",
    initialFocus: "Open profile author",
    leavesInspectorOpen: false,
  },
  {
    kind: "editor",
    label: "Permanent fleet topology editor",
    initialFocus: "Request hierarchy change",
    leavesInspectorOpen: true,
  },
];

async function openFleetOverlay(kind: FleetOverlayKind) {
  const { container } = render(
    <PermanentFleetTopology onCreateProfile={vi.fn()} />,
  );
  const inspectChief = await screen.findByRole("button", {
    name: "Inspect chief-of-staff",
  });
  const backgroundControl = screen.getByRole("button", {
    name: "Inspect research-head",
  });
  let opener: HTMLElement;

  if (kind === "handoff") {
    opener = screen.getByRole("button", {
      name: "Start child profile handoff from chief-of-staff",
    });
    opener.focus();
    fireEvent.click(opener);
  } else {
    inspectChief.focus();
    fireEvent.click(inspectChief);
    if (kind === "inspector") {
      opener = inspectChief;
    } else {
      const inspector = screen.getByRole("dialog", {
        name: "chief-of-staff fleet inspector",
      });
      opener = within(inspector).getByRole("button", { name: "Edit topology" });
      opener.focus();
      fireEvent.click(opener);
    }
  }

  return {
    backgroundControl,
    container,
    opener,
  };
}

describe("Permanent fleet exact approval continuation", () => {
  it.each(modalCases)(
    "makes the $kind overlay modal, traps focus, and restores its exact opener",
    async ({ kind, label, initialFocus, leavesInspectorOpen }) => {
      const { backgroundControl, container, opener } = await openFleetOverlay(kind);
      const dialog = screen.getByRole("dialog", { name: label });
      const surface = container.querySelector<HTMLElement>(".fleet-surface")!;

      expect(dialog.getAttribute("aria-modal")).toBe("true");
      expect(surface.hasAttribute("inert")).toBe(true);
      expect(surface.getAttribute("aria-hidden")).toBe("true");
      expect(document.activeElement).toBe(within(dialog).getByRole("button", {
        name: initialFocus,
      }));
      if (leavesInspectorOpen) {
        const underlyingInspector = screen.getByRole("dialog", {
          hidden: true,
          name: "chief-of-staff fleet inspector",
        });
        expect(underlyingInspector.getAttribute("aria-modal")).toBeNull();
        expect(underlyingInspector.parentElement?.hasAttribute("inert")).toBe(true);
        expect(screen.queryByRole("dialog", {
          name: "chief-of-staff fleet inspector",
        })).toBeNull();
      }

      const focusable = [...dialog.querySelectorAll<HTMLElement>(
        "button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])",
      )];
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      expect(first).toBeTruthy();
      expect(last).toBeTruthy();

      first.focus();
      fireEvent.keyDown(first, { key: "Tab", shiftKey: true });
      expect(document.activeElement).toBe(last);
      fireEvent.keyDown(last, { key: "Tab" });
      expect(document.activeElement).toBe(first);

      // Even synthetic clicks cannot punch through the inert fleet surface.
      fireEvent.click(backgroundControl);
      expect(screen.getByRole("dialog", { name: label })).toBe(dialog);

      fireEvent.keyDown(document.activeElement ?? dialog, { key: "Escape" });
      await waitFor(() => expect(screen.queryByRole("dialog", { name: label })).toBeNull());
      await waitFor(() => expect(document.activeElement).toBe(opener));
      expect(surface.hasAttribute("inert")).toBe(leavesInspectorOpen);
    },
  );

  it.each(modalCases)(
    "closes the $kind overlay only when the scrim itself is pressed",
    async ({ kind, label }) => {
      const { opener } = await openFleetOverlay(kind);
      const dialog = screen.getByRole("dialog", { name: label });
      const scrim = dialog.parentElement!;

      fireEvent.mouseDown(dialog);
      expect(screen.getByRole("dialog", { name: label })).toBe(dialog);
      fireEvent.mouseDown(scrim);

      await waitFor(() => expect(screen.queryByRole("dialog", { name: label })).toBeNull());
      await waitFor(() => expect(document.activeElement).toBe(opener));
    },
  );

  it("centres a narrow authored hierarchy in the scroll plane", async () => {
    const { container } = render(<PermanentFleetTopology />);

    await screen.findByRole("button", { name: "Inspect chief-of-staff" });
    const wraps = [...container.querySelectorAll<HTMLElement>(".fleet-node-wrap")];
    expect(wraps).toHaveLength(2);
    expect(wraps.map((node) => node.style.left)).toEqual(["380px", "380px"]);
  });

  it("centres the truthful six-head row within the framed target canvas", async () => {
    api.permanentFleet.mockResolvedValue({
      ...canonical,
      hierarchy: {
        ...hierarchy,
        departments: Array.from({ length: 6 }, (_, index) => ({
          ...hierarchy.departments[0],
          name: `department-${index + 1}`,
          routing_id: `department-${index + 1}`,
        })),
      },
    });

    const { container } = render(<PermanentFleetTopology />);
    const canvas = container.querySelector<HTMLElement>(".fleet-canvas")!;
    Object.defineProperties(canvas, {
      // The 1,142px target border box has a 1px border on either side.
      clientWidth: { configurable: true, value: 1140 },
      scrollWidth: { configurable: true, value: 1178 },
    });

    await screen.findByRole("button", { name: "Inspect department-6" });
    await waitFor(() => expect(canvas.scrollLeft).toBe(19));
    const plane = container.querySelector<HTMLElement>(".fleet-plane")!;
    expect(plane.style.width).toBe("1178px");
    const first = screen.getByRole("button", { name: "Inspect department-1" })
      .closest<HTMLElement>(".fleet-node-wrap")!;
    const last = screen.getByRole("button", { name: "Inspect department-6" })
      .closest<HTMLElement>(".fleet-node-wrap")!;
    const clippedAtStart = Number.parseFloat(first.style.left) - 98 - canvas.scrollLeft;
    const clippedAtEnd = Number.parseFloat(last.style.left) + 98
      - canvas.scrollLeft - canvas.clientWidth;
    expect(canvas.clientWidth + 2).toBe(1142);
    expect(clippedAtStart).toBe(-18);
    expect(clippedAtEnd).toBe(18);
  });

  it("keeps a narrower six-head viewport centred and horizontally scrollable", async () => {
    api.permanentFleet.mockResolvedValue({
      ...canonical,
      hierarchy: {
        ...hierarchy,
        departments: Array.from({ length: 6 }, (_, index) => ({
          ...hierarchy.departments[0],
          name: `department-${index + 1}`,
          routing_id: `department-${index + 1}`,
        })),
      },
    });

    const { container } = render(<PermanentFleetTopology />);
    const canvas = container.querySelector<HTMLElement>(".fleet-canvas")!;
    Object.defineProperties(canvas, {
      clientWidth: { configurable: true, value: 900 },
      scrollWidth: { configurable: true, value: 1178 },
    });

    await screen.findByRole("button", { name: "Inspect department-6" });
    await waitFor(() => expect(canvas.scrollLeft).toBe(139));
    expect(canvas.scrollWidth).toBeGreaterThan(canvas.clientWidth);
  });

  it("uses exact lowercase authority labels", async () => {
    render(<PermanentFleetTopology />);

    const legend = await screen.findByLabelText("Authority legend");
    expect([...legend.querySelectorAll(".fleet-authority-key-item")].map((item) => (
      item.textContent
    ))).toEqual(["read", "write", "send", "spend", "delegate"]);
    expect(within(legend).queryByText("Read")).toBeNull();
  });

  it("uses a genotype-backed badge inside Fleet nodes without mounting a premium Stage", async () => {
    const genotype = {
      source: "agent_capability.name.v1" as const,
      seed: 898153330,
      body: "kepler",
      palette: ["#ffedd5", "#f97316", "#7c2d12"],
      markings: ["orbit"],
      accessories: ["antenna"],
      voice_id: null,
    };
    render(<PermanentFleetTopology profiles={[{
      name: "research-head",
      runtime: "codex",
      supported_skills: ["research/*"],
      max_depth: 2,
      is_ephemeral: false,
      cost_tier: "cheap",
      model_endpoint: null,
      source: "control-plane",
      is_active: true,
      status: "active",
      familiar_genotype: genotype,
    }]} />);

    const familiar = await screen.findByRole("img", {
      name: "research-head profile Familiar",
    });
    expect(familiar.dataset.genotypeSource).toBe("agent_capability.name.v1");
    const badge = familiar.querySelector<HTMLElement>(".familiar-orb");
    expect(badge).toBeTruthy();
    expect(badge?.dataset.familiarBody).toBe("kepler");
    expect(badge?.dataset.renderer).toBe("badge");
    expect(badge?.style.width).toBe("32px");
    expect(familiar.querySelector(".familiar-stage")).toBeNull();
  });

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
    await openTopologyEditor();
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
    await openTopologyEditor();
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
    await openTopologyEditor();
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
    await openTopologyEditor();
    const routingInput = screen.getAllByLabelText("Routing identity")[1];
    fireEvent.change(routingInput, { target: { value: "researchops" } });
    expect(screen.getAllByLabelText("Routing identity")[1]).toBe(routingInput);
    expect(routingInput).toHaveProperty("value", "researchops");
  });
});
