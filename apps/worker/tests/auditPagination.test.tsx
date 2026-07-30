// @vitest-environment happy-dom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  auditExport: vi.fn(),
  auditSearch: vi.fn(async ({ offset }: { offset: number }) => offset === 0 ? {
    results: [{
      seq: 4, ts: "2026-01-04T00:00:00Z", actor: "alice",
      verb: "ticket.newest", status: "ok",
    }],
    stream: "audit", scope: "all", limit: 100, offset: 0, next_offset: 100,
  } : {
    results: [{
      seq: 2, ts: "2026-01-02T00:00:00Z", actor: "alice",
      verb: "ticket.older", status: "ok",
    }],
    stream: "audit", scope: "all", limit: 100, offset: 100, next_offset: null,
  }),
  auditVerify: vi.fn(),
  modelTelemetry: vi.fn(async () => ({ models: [] })),
  platformStatus: vi.fn(async () => ({ components: [], runtimes: [] })),
  readiness: vi.fn(async () => ({ status: "ready", checks: {} })),
}));

vi.mock("../src/client", () => ({ client: api }));

import { OperateView } from "../src/components/OperationsView";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

it("pages the scoped audit browser without reversing the server page", async () => {
  render(<OperateView />);
  fireEvent.click(screen.getByRole("button", { name: "Audit" }));
  fireEvent.click(screen.getByRole("button", { name: "Search" }));

  await screen.findByText("ticket.newest");
  expect(api.auditSearch).toHaveBeenLastCalledWith(expect.objectContaining({
    limit: 100, offset: 0,
  }));
  fireEvent.click(screen.getByRole("button", { name: "Older" }));

  await screen.findByText("ticket.older");
  await waitFor(() => expect(api.auditSearch).toHaveBeenLastCalledWith(
    expect.objectContaining({ limit: 100, offset: 100 }),
  ));
  expect((screen.getByRole("button", { name: "Older" }) as HTMLButtonElement).disabled)
    .toBe(true);
});
