// @vitest-environment happy-dom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  activateAdapter: vi.fn(),
  adapterSource: vi.fn(),
  adapters: vi.fn(),
  deactivateAdapter: vi.fn(),
  deleteAdapter: vi.fn(),
  generateAdapter: vi.fn(),
  invokeApprovalState: vi.fn(),
  registerMcpServer: vi.fn(),
}));

vi.mock("../src/client", () => ({ client: api }));
vi.mock("../src/components/build/McpServersBuild", () => ({
  McpServersBuild: () => <div data-testid="mcp-operations" />,
}));

import { AdaptersBuild } from "../src/components/build/AdaptersBuild";

beforeEach(() => {
  api.adapters.mockResolvedValue({
    adapters: [
      {
        id: "external-docs",
        runtime: "mcp",
        version: "1.0.0",
        source: "manual",
        activated: false,
        health: "unknown",
      },
      {
        id: "ticket-script",
        runtime: "python",
        version: "1.0.0",
        source: "generated",
        activated: false,
        health: "unknown",
      },
      {
        id: "active-script",
        runtime: "python",
        version: "1.0.0",
        source: "generated",
        activated: true,
        health: "ok",
      },
    ],
  });
  api.adapterSource.mockResolvedValue({ source: "def invoke(): pass" });
  api.invokeApprovalState.mockResolvedValue({ status: "approved" });
  api.registerMcpServer.mockResolvedValue({ status: "ok" });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("Worker adapter and MCP boundaries", () => {
  it("keeps an inventory-selected MCP server out of generic adapter controls", async () => {
    render(<AdaptersBuild />);

    fireEvent.click(await screen.findByRole("button", { name: /external-docs/i }));

    expect(screen.getByText(/Use MCP operations below/i)).toBeTruthy();
    expect(api.adapterSource).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Load source" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Request activation" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Deactivate" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Delete inert adapter" })).toBeNull();
  });

  it("offers only deactivation for an inventory-selected active adapter", async () => {
    render(<AdaptersBuild />);

    fireEvent.click(await screen.findByRole("button", { name: /active-script/i }));

    expect(await screen.findByRole("button", { name: "Deactivate" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Request activation" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Delete inert adapter" })).toBeNull();
  });

  it("offers only activation and deletion for an inventory-selected inert adapter", async () => {
    render(<AdaptersBuild />);

    fireEvent.click(await screen.findByRole("button", { name: /ticket-script/i }));

    expect(await screen.findByRole("button", { name: "Request activation" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Delete inert adapter" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Deactivate" })).toBeNull();
  });

  it("requires an MCP URL and sends the validated URL value", async () => {
    render(<AdaptersBuild />);

    const url = await screen.findByLabelText("URL");
    expect((url as HTMLInputElement).required).toBe(true);
    fireEvent.change(screen.getByLabelText("Identifier"), {
      target: { value: "external-docs" },
    });
    fireEvent.change(url, {
      target: { value: "https://mcp.example.test/server" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Register server" }));

    await waitFor(() => expect(api.registerMcpServer).toHaveBeenCalledWith(
      expect.objectContaining({
        id: "external-docs",
        url: "https://mcp.example.test/server",
      }),
    ));
    expect(api.registerMcpServer.mock.calls[0]?.[0].url).not.toBeUndefined();
  });

  it("replays the exact approved adapter activation inputs", async () => {
    api.activateAdapter
      .mockResolvedValueOnce({
        status: "pending_human",
        hitl_request_id: "hitl-activate",
      })
      .mockResolvedValueOnce({ status: "ok" });

    render(<AdaptersBuild />);
    fireEvent.click(await screen.findByRole("button", { name: /ticket-script/i }));
    await waitFor(() => expect(api.adapterSource).toHaveBeenCalledWith("ticket-script"));
    fireEvent.change(screen.getByLabelText("Reviewer identity"), {
      target: { value: "reviewer-a" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Request activation" }));

    fireEvent.click(await screen.findByRole("button", {
      name: "Check approval and apply exact change",
    }));

    await waitFor(() => expect(api.activateAdapter).toHaveBeenLastCalledWith(
      "ticket-script",
      { reviewer: "reviewer-a" },
      "hitl-activate",
    ));
    expect(await screen.findByText("Adapter ticket-script activated.")).toBeTruthy();
  });

  it("replays the exact approved adapter deactivation", async () => {
    api.deactivateAdapter
      .mockResolvedValueOnce({
        status: "pending_human",
        hitl_request_id: "hitl-deactivate",
      })
      .mockResolvedValueOnce({ status: "ok" });

    render(<AdaptersBuild />);
    fireEvent.click(await screen.findByRole("button", { name: /active-script/i }));
    fireEvent.click(await screen.findByRole("button", { name: "Deactivate" }));
    fireEvent.click(await screen.findByRole("button", { name: "Confirm deactivate" }));
    fireEvent.click(await screen.findByRole("button", {
      name: "Check approval and apply exact change",
    }));

    await waitFor(() => expect(api.deactivateAdapter).toHaveBeenLastCalledWith(
      "active-script",
      "hitl-deactivate",
    ));
    expect(await screen.findByText("Adapter active-script deactivated.")).toBeTruthy();
  });

  it("replays the exact approved inert-adapter deletion", async () => {
    api.deleteAdapter
      .mockResolvedValueOnce({
        status: "pending_human",
        hitl_request_id: "hitl-delete",
      })
      .mockResolvedValueOnce({ status: "ok" });

    render(<AdaptersBuild />);
    fireEvent.click(await screen.findByRole("button", { name: /ticket-script/i }));
    fireEvent.click(await screen.findByRole("button", { name: "Delete inert adapter" }));
    fireEvent.click(await screen.findByRole("button", { name: "Confirm delete" }));
    fireEvent.click(await screen.findByRole("button", {
      name: "Check approval and apply exact change",
    }));

    await waitFor(() => expect(api.deleteAdapter).toHaveBeenLastCalledWith(
      "ticket-script",
      "hitl-delete",
    ));
    expect(await screen.findByText("Adapter ticket-script deleted.")).toBeTruthy();
  });

  it("invalidates a pending activation when its requester-owned inputs change", async () => {
    api.activateAdapter.mockResolvedValue({
      status: "pending_human",
      hitl_request_id: "hitl-stale",
    });

    render(<AdaptersBuild />);
    fireEvent.click(await screen.findByRole("button", { name: /ticket-script/i }));
    await waitFor(() => expect(api.adapterSource).toHaveBeenCalledWith("ticket-script"));
    fireEvent.click(screen.getByRole("button", { name: "Request activation" }));
    await screen.findByRole("button", {
      name: "Check approval and apply exact change",
    });

    fireEvent.change(screen.getByLabelText("Reviewer identity"), {
      target: { value: "changed-reviewer" },
    });

    expect(await screen.findByText("Adapter ticket-script activation changed")).toBeTruthy();
    expect(screen.queryByRole("button", {
      name: "Check approval and apply exact change",
    })).toBeNull();
    expect(api.invokeApprovalState).not.toHaveBeenCalled();
    expect(api.activateAdapter).toHaveBeenCalledTimes(1);
  });
});
