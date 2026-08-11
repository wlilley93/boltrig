// @vitest-environment happy-dom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  activateMcpServer: vi.fn(),
  deactivateMcpServer: vi.fn(),
  deleteMcpServer: vi.fn(),
  invokeApprovalState: vi.fn(),
  mcpServer: vi.fn(),
  mcpServers: vi.fn(),
  probeMcpServer: vi.fn(),
  retireMcpServer: vi.fn(),
  restoreMcpServer: vi.fn(),
  updateMcpServer: vi.fn(),
}));

vi.mock("../src/client", () => ({ client: api }));

import { McpServersBuild } from "../src/components/build/McpServersBuild";

const inert = {
  id: "external-docs",
  config_revision: 1,
  version: "1.0.0",
  source: "manual",
  state: "inert" as const,
  activated: false,
  runtime_loaded: false,
  endpoint: {
    origin: "https://mcp.example.test",
    path_redacted: true,
    internal_egress_allowed: false,
  },
  credential_configured: true,
  recorded_health: "unknown" as const,
  health: {
    status: "unknown" as const,
    source: "unverified" as const,
    checked_at: null,
  },
  operability: {
    status: "unavailable" as const,
    reason: "pending_activation",
  },
  last_probe: null,
  tool_snapshot: {
    status: "never_discovered" as const,
    observed_at: null,
    count: 0,
    publication_status: "never_discovered" as const,
  },
  available_actions: ["probe", "activate", "retire", "update", "delete"] as const,
};

beforeEach(() => {
  api.mcpServers.mockResolvedValue({ servers: [inert], truncated: false });
  api.mcpServer.mockResolvedValue({
    server: inert,
    tools: [],
    tools_truncated: false,
    probe_history: [],
    probe_history_truncated: false,
  });
  api.probeMcpServer.mockResolvedValue({ status: "ok" });
  api.activateMcpServer.mockResolvedValue({ status: "ok" });
  api.deactivateMcpServer.mockResolvedValue({ status: "ok" });
  api.deleteMcpServer.mockResolvedValue({ status: "ok", deleted: true });
  api.retireMcpServer.mockResolvedValue({ status: "ok" });
  api.restoreMcpServer.mockResolvedValue({ status: "ok" });
  api.updateMcpServer.mockResolvedValue({
    status: "ok",
    updated: true,
    reprobe_required: true,
    config_revision: 2,
  });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("Worker external MCP operations", () => {
  it("distinguishes never checked from a live probe and exposes inert actions", async () => {
    render(<McpServersBuild />);

    fireEvent.click(await screen.findByText("external-docs"));
    expect(await screen.findByText("Never checked")).toBeTruthy();
    expect(screen.getByText("Configuration revision")).toBeTruthy();
    expect(screen.getByText(/Opening or refreshing this view never contacts/i)).toBeTruthy();
    expect(screen.getByText(/No successful discovery snapshot has been stored/i)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Probe server" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Request activation" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Retire server" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Replace configuration" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Delete server" })).toBeTruthy();
    expect(api.probeMcpServer).not.toHaveBeenCalled();
  });

  it("requires a complete replacement URL and sends preserve without hidden credential fields", async () => {
    const internalAllowed = {
      ...inert,
      endpoint: { ...inert.endpoint, internal_egress_allowed: true },
    };
    api.mcpServers.mockResolvedValue({
      servers: [internalAllowed],
      truncated: false,
    });
    api.mcpServer.mockResolvedValue({
      server: internalAllowed,
      tools: [],
      tools_truncated: false,
      probe_history: [],
      probe_history_truncated: false,
    });
    render(<McpServersBuild />);
    fireEvent.click(await screen.findByText("external-docs"));
    fireEvent.click(await screen.findByRole("button", {
      name: "Replace configuration",
    }));

    const url = screen.getByLabelText("Complete replacement URL") as HTMLInputElement;
    expect(url.value).toBe("");
    expect(screen.queryByDisplayValue("https://mcp.example.test")).toBeNull();
    expect((screen.getByRole("checkbox", {
      name: /Allow operator-vetted internal egress/,
    }) as HTMLInputElement).checked).toBe(true);
    expect(screen.getByText(/visible origin cannot reconstruct a hidden endpoint path/i)).toBeTruthy();
    expect(screen.getByText(/clears the saved tool snapshot plus all prior probe history/i)).toBeTruthy();
    expect((screen.getByLabelText("Credential handling") as HTMLSelectElement).value)
      .toBe("preserve");
    expect(screen.queryByLabelText(/Credential reference/)).toBeNull();
    fireEvent.change(screen.getByLabelText("Credential handling"), {
      target: { value: "replace" },
    });
    fireEvent.change(screen.getByLabelText(/Credential reference/), {
      target: { value: "SHOULD_NOT_LEAK" },
    });
    fireEvent.change(screen.getByLabelText("Credential handling"), {
      target: { value: "preserve" },
    });
    expect(screen.queryByLabelText(/Credential reference/)).toBeNull();

    fireEvent.change(url, {
      target: { value: "https://replacement.example.test/private/mcp" },
    });
    fireEvent.click(screen.getByRole("button", {
      name: "Request configuration replacement",
    }));

    await waitFor(() => expect(api.updateMcpServer).toHaveBeenCalledWith(
      "external-docs",
      {
        url: "https://replacement.example.test/private/mcp",
        allow_internal: true,
        credential_mode: "preserve",
      },
      undefined,
    ));
    const sent = api.updateMcpServer.mock.calls[0]?.[1];
    expect(sent).not.toHaveProperty("credential_ref");
    expect(sent).not.toHaveProperty("credential_id");
    expect(await screen.findByText(/run Probe server before activation/i)).toBeTruthy();
  });

  it("replays the exact full replacement and named credential after approval", async () => {
    api.updateMcpServer
      .mockResolvedValueOnce({
        status: "pending_human",
        hitl_request_id: "approval/mcp-update",
      })
      .mockResolvedValueOnce({
        status: "ok",
        updated: true,
        reprobe_required: true,
        config_revision: 2,
      });
    api.invokeApprovalState.mockResolvedValue({ status: "approved" });

    render(<McpServersBuild />);
    fireEvent.click(await screen.findByText("external-docs"));
    fireEvent.click(await screen.findByRole("button", {
      name: "Replace configuration",
    }));
    fireEvent.change(screen.getByLabelText("Complete replacement URL"), {
      target: { value: "https://replacement.example.test/private/mcp" },
    });
    fireEvent.change(screen.getByLabelText("Credential handling"), {
      target: { value: "replace" },
    });
    fireEvent.change(screen.getByLabelText(/Credential reference/), {
      target: { value: "DOCS_TOKEN_V2" },
    });
    fireEvent.change(screen.getByLabelText("Credential id (optional)"), {
      target: { value: "docs-v2" },
    });
    fireEvent.change(screen.getByLabelText("Credential store (optional)"), {
      target: { value: "env" },
    });
    fireEvent.change(screen.getByLabelText("Credential kind (optional)"), {
      target: { value: "bearer" },
    });
    fireEvent.click(screen.getByRole("button", {
      name: "Request configuration replacement",
    }));

    const body = {
      url: "https://replacement.example.test/private/mcp",
      allow_internal: false,
      credential_mode: "replace",
      credential_ref: "DOCS_TOKEN_V2",
      credential_id: "docs-v2",
      credential_store: "env",
      credential_kind: "bearer",
    };
    await waitFor(() => expect(api.updateMcpServer).toHaveBeenCalledWith(
      "external-docs",
      body,
      undefined,
    ));
    expect(await screen.findByText(/waiting for approval in the originating chat/i)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", {
      name: "Check approval and apply exact change",
    }));
    await waitFor(() => expect(api.updateMcpServer).toHaveBeenLastCalledWith(
      "external-docs",
      body,
      "approval/mcp-update",
    ));
  });

  it("arms deletion before requesting it and replays the exact server after approval", async () => {
    api.deleteMcpServer
      .mockResolvedValueOnce({
        status: "pending_human",
        hitl_request_id: "approval/mcp-delete",
      })
      .mockResolvedValueOnce({ status: "ok", deleted: true });
    api.invokeApprovalState.mockResolvedValue({ status: "approved" });

    render(<McpServersBuild />);
    fireEvent.click(await screen.findByText("external-docs"));
    fireEvent.click(await screen.findByRole("button", { name: "Delete server" }));
    expect(api.deleteMcpServer).not.toHaveBeenCalled();
    expect(await screen.findByText(/Deletion is permanent/i)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Confirm delete server" }));
    await waitFor(() => expect(api.deleteMcpServer).toHaveBeenCalledWith(
      "external-docs",
      undefined,
    ));
    fireEvent.click(await screen.findByRole("button", {
      name: "Check approval and apply exact change",
    }));
    await waitFor(() => expect(api.deleteMcpServer).toHaveBeenLastCalledWith(
      "external-docs",
      "approval/mcp-delete",
    ));
  });

  it("keeps a failed stale probe and last-known tools visible while retired", async () => {
    const retired = {
      ...inert,
      state: "retired" as const,
      last_probe: {
        checked_at: "2020-01-01T00:00:00Z",
        outcome: "failed" as const,
        failure_code: "transport_unavailable" as const,
        tool_count: 0,
      },
      tool_snapshot: {
        status: "snapshot" as const,
        observed_at: "2020-01-01T00:00:00Z",
        count: 1,
        publication_status: "retired" as const,
      },
      available_actions: ["restore", "delete"] as const,
    };
    api.mcpServers.mockResolvedValue({ servers: [retired], truncated: false });
    api.mcpServer.mockResolvedValue({
      server: retired,
      tools: [{
        id: "external-docs.search",
        name: "search",
        description: "Search the saved catalogue",
        consequence: "low",
        input_schema: {},
        output_schema: {},
      }],
      tools_truncated: false,
      probe_history: [{
        probe_id: "probe-old",
        checked_at: "2020-01-01T00:00:00Z",
        outcome: "failed",
        failure_code: "transport_unavailable",
        tool_count: 0,
      }],
      probe_history_truncated: false,
    });

    render(<McpServersBuild />);
    fireEvent.click(await screen.findByText("external-docs"));

    expect(await screen.findByText(/Transport unavailable.*stale/i)).toBeTruthy();
    expect(screen.getByText("search")).toBeTruthy();
    expect(screen.getByText("1 shown")).toBeTruthy();
    expect(screen.getByLabelText("MCP probe history")).toBeTruthy();
    expect(screen.getAllByText(/stale/i).length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText(/historical, not live/i)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Restore server" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Delete server" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Probe server" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Request activation" })).toBeNull();
  });

  it("renders unknown failure codes only as an allowlisted fallback label", async () => {
    const failed = {
      ...inert,
      last_probe: {
        checked_at: "2099-01-01T00:00:00Z",
        outcome: "failed" as const,
        failure_code: "provider_secret_detail",
        tool_count: 0,
      },
    };
    api.mcpServers.mockResolvedValue({ servers: [failed], truncated: false });
    api.mcpServer.mockResolvedValue({
      server: failed,
      tools: [],
      tools_truncated: false,
      probe_history: [],
      probe_history_truncated: false,
    });

    render(<McpServersBuild />);
    fireEvent.click(await screen.findByText("external-docs"));
    expect(await screen.findByText(/Unclassified probe failure/i)).toBeTruthy();
    expect(screen.queryByText(/provider_secret_detail/i)).toBeNull();
  });

  it("offers deactivation, but not retirement, for an active server", async () => {
    const active = {
      ...inert,
      state: "active" as const,
      activated: true,
      runtime_loaded: true,
      operability: { status: "ready" as const, reason: null },
      last_probe: {
        checked_at: "2099-01-01T00:00:00Z",
        outcome: "succeeded" as const,
        failure_code: null,
        tool_count: 0,
      },
      tool_snapshot: {
        status: "snapshot" as const,
        observed_at: "2099-01-01T00:00:00Z",
        count: 0,
        publication_status: "drifted" as const,
      },
      available_actions: ["probe", "deactivate", "update"] as const,
    };
    api.mcpServers.mockResolvedValue({ servers: [active], truncated: false });
    api.mcpServer.mockResolvedValue({
      server: active,
      tools: [],
      tools_truncated: false,
      probe_history: [{
        probe_id: "probe-current",
        checked_at: "2099-01-01T00:00:00Z",
        outcome: "succeeded",
        failure_code: null,
        tool_count: 0,
      }],
      probe_history_truncated: false,
    });

    render(<McpServersBuild />);
    fireEvent.click(await screen.findByText("external-docs"));
    expect(await screen.findByText(/Probe did not hot-publish it/i)).toBeTruthy();
    fireEvent.click(await screen.findByRole("button", {
      name: "Request deactivation",
    }));
    await waitFor(() => expect(api.deactivateMcpServer).toHaveBeenCalledWith(
      "external-docs",
      undefined,
    ));
    expect(screen.queryByRole("button", { name: "Retire server" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Replace configuration" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Delete server" })).toBeNull();
  });

  it("finalizes a probe with the exact server snapshot and approval id", async () => {
    api.probeMcpServer
      .mockResolvedValueOnce({
        status: "pending_human",
        hitl_request_id: "approval/mcp-probe",
      })
      .mockResolvedValueOnce({ status: "ok" });
    api.invokeApprovalState.mockResolvedValue({ status: "approved" });

    render(<McpServersBuild />);
    fireEvent.click(await screen.findByText("external-docs"));
    fireEvent.click(await screen.findByRole("button", { name: "Probe server" }));
    expect(api.probeMcpServer).toHaveBeenCalledWith("external-docs", undefined);
    expect(await screen.findByText(/waiting for approval in the originating chat/i)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", {
      name: "Check approval and apply exact change",
    }));
    await waitFor(() => expect(api.probeMcpServer).toHaveBeenLastCalledWith(
      "external-docs",
      "approval/mcp-probe",
    ));
    expect(api.invokeApprovalState).toHaveBeenCalledWith("approval/mcp-probe");
  });
});
