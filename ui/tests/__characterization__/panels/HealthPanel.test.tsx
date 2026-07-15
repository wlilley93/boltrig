import { afterEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import { api } from "@/api/client";
import { HealthPanel } from "@/panels/HealthPanel";
import { clearApiMocks, mockApi } from "../helpers";

afterEach(() => {
  cleanup();
  clearApiMocks();
});

describe("HealthPanel", () => {
  it("renders coarse readiness checks without inventing dependency detail", async () => {
    mockApi({
      health: { status: "ok" },
      readiness: {
        status: "not_ready",
        checks: {
          postgres: { status: "down", required: true, reason: "connection_failed" },
          model_gateway: { status: "disabled", required: false },
        },
      },
    });

    render(<HealthPanel />);

    expect(await screen.findByText("Not ready for traffic")).toBeTruthy();
    expect(screen.getByText("Postgres")).toBeTruthy();
    expect(screen.getByText("Connection Failed")).toBeTruthy();
    expect(screen.getByText("Model Gateway")).toBeTruthy();
    expect(screen.getByText(/Kernel is live/)).toBeTruthy();
  });

  it("refreshes both readiness and liveness", async () => {
    mockApi({
      health: { status: "ok" },
      readiness: { status: "ready", checks: {} },
    });

    render(<HealthPanel />);
    await screen.findByText("Ready for traffic");
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));

    await waitFor(() => {
      expect(api.readiness).toHaveBeenCalledTimes(2);
      expect(api.health).toHaveBeenCalledTimes(2);
    });
  });
});
