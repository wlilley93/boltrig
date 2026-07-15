import { afterEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";

import { api } from "@/api/client";
import { DeckSlideContext } from "@/deck/context";
import { AdapterStudio } from "@/panels/studio/AdapterStudio";
import { clearApiMocks, mockApi } from "../../helpers";

const OPENAPI_TEXT = JSON.stringify({
  openapi: "3.0.0",
  info: { title: "Petstore", version: "1.0.0" },
  paths: {
    "/pets": {
      get: {
        operationId: "pet.list",
        responses: { 200: { description: "ok" } },
      },
    },
  },
});

afterEach(() => {
  cleanup();
  clearApiMocks();
});

describe("AdapterStudio integrations", () => {
  it("imports an OpenAPI file while keeping the raw editor under Advanced", async () => {
    mockApi({
      adapters: { adapters: [] },
      generateAdapter: {
        status: "ok",
        id: "petstore",
        activated: false,
        verbs: ["pet.list"],
      },
    });
    render(<AdapterStudio />);

    const advancedSummary = screen.getByText("Advanced: raw OpenAPI JSON");
    expect(advancedSummary.closest("details")?.hasAttribute("open")).toBe(false);
    fireEvent.click(advancedSummary);
    expect(advancedSummary.closest("details")?.hasAttribute("open")).toBe(true);
    expect(
      screen.getByRole("textbox", { name: "Raw OpenAPI JSON" }),
    ).toBeTruthy();

    const file = new File([OPENAPI_TEXT], "petstore.json", {
      type: "application/json",
    });
    Object.defineProperty(file, "text", {
      value: vi.fn().mockResolvedValue(OPENAPI_TEXT),
    });
    fireEvent.change(screen.getByLabelText("OpenAPI document"), {
      target: { files: [file] },
    });
    await screen.findByText(/Imported petstore\.json/);

    fireEvent.change(screen.getByLabelText("adapter_id"), {
      target: { value: "petstore" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Generate" }));

    await waitFor(() =>
      expect(api.generateAdapter).toHaveBeenCalledWith({
        adapter_id: "petstore",
        spec: JSON.parse(OPENAPI_TEXT),
      }),
    );
  });

  it("never accepts or transmits an MCP token through verb-space", async () => {
    mockApi({
      adapters: { adapters: [] },
      registerMcpServer: { status: "ok" },
    });
    render(<AdapterStudio />);

    expect(screen.queryByRole("textbox", { name: /token/i })).toBeNull();
    expect(document.querySelector('input[type="password"]')).toBeNull();
    expect(
      screen.getByText(/server-side credential store/i),
    ).toBeTruthy();

    fireEvent.change(screen.getByLabelText("MCP server id"), {
      target: { value: "docs-mcp" },
    });
    fireEvent.change(screen.getByLabelText("MCP server URL"), {
      target: { value: "https://mcp.example.test" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Register" }));

    await waitFor(() =>
      expect(api.registerMcpServer).toHaveBeenCalledWith({
        id: "docs-mcp",
        url: "https://mcp.example.test",
      }),
    );
    expect(vi.mocked(api.registerMcpServer).mock.calls[0]?.[0]).not.toHaveProperty(
      "token",
    );
  });

  it("reviews, reads source, and arms activation from the selected row", async () => {
    mockApi({
      adapters: {
        adapters: [
          {
            id: "generated-one",
            runtime: "http",
            version: "1.0.0",
            source: "generated",
            activated: false,
            health: "ok",
          },
          {
            id: "active-but-down",
            runtime: "http",
            version: "2.0.0",
            source: "manual",
            activated: true,
            health: "down",
          },
        ],
      },
      adapterSource: {
        id: "generated-one",
        source: "class GeneratedOneAdapter: pass",
      },
      invoke: { status: "pending_human", hitl_request_id: "hitl-adapter-1" },
    });
    render(
      <DeckSlideContext.Provider value={{ active: false, neighbour: false }}>
        <AdapterStudio />
      </DeckSlideContext.Provider>,
    );

    const inertRow = await screen.findByRole("article", {
      name: "Adapter generated-one",
    });
    expect(within(inertRow).getByText("inert")).toBeTruthy();
    expect(within(inertRow).getByText("health: ok")).toBeTruthy();

    const activeRow = screen.getByRole("article", {
      name: "Adapter active-but-down",
    });
    expect(within(activeRow).getByText("active")).toBeTruthy();
    expect(within(activeRow).getByText("health: down")).toBeTruthy();
    expect(
      within(activeRow).getByRole("button", { name: "Active" }).hasAttribute(
        "disabled",
      ),
    ).toBe(true);

    fireEvent.click(within(inertRow).getByRole("button", { name: "Review" }));
    expect(
      within(inertRow).getByLabelText("Review generated-one"),
    ).toBeTruthy();
    fireEvent.click(within(inertRow).getByRole("button", { name: "Source" }));
    await waitFor(() =>
      expect(api.adapterSource).toHaveBeenCalledWith("generated-one"),
    );
    expect(
      await within(inertRow).findByText("class GeneratedOneAdapter: pass"),
    ).toBeTruthy();

    fireEvent.click(within(inertRow).getByRole("button", { name: "Activate" }));
    expect(api.invoke).not.toHaveBeenCalled();
    fireEvent.click(
      within(inertRow).getByRole("button", { name: "Confirm activation" }),
    );

    await waitFor(() =>
      expect(api.invoke).toHaveBeenCalledWith({
        noun: "control",
        verb: "control.adapter.activate",
        params: { adapter_id: "generated-one" },
      }),
    );
    expect(await within(inertRow).findByText("Paused for approval")).toBeTruthy();
  });
});
