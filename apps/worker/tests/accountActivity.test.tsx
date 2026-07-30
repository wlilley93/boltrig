// @vitest-environment happy-dom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  meActivity: vi.fn(async ({ offset }: { offset: number }) => offset === 0 ? {
    results: [{
      seq: 3, ts: "2026-01-03T00:00:00Z", verb: "own.newest", status: "ok",
    }],
    limit: 8, offset: 0, next_offset: 8,
  } : {
    results: [{
      seq: 2, ts: "2026-01-02T00:00:00Z", verb: "own.older", status: "ok",
    }],
    limit: 8, offset: 8, next_offset: null,
  }),
  meExport: vi.fn(),
}));

vi.mock("../src/client", () => ({ client: api }));

import { ActivityAndExport } from "../src/components/AccountProfileSections";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

it("pages account activity through the SDK and keeps export scope honest", async () => {
  render(<ActivityAndExport />);

  await screen.findByText("own.newest");
  expect(api.meActivity).toHaveBeenCalledWith({ limit: 8, offset: 0 });
  fireEvent.click(screen.getByRole("button", { name: "Older" }));

  await screen.findByText("own.older");
  await waitFor(() => expect(api.meActivity).toHaveBeenLastCalledWith({
    limit: 8, offset: 8,
  }));
  expect((screen.getByRole("button", { name: "Older" }) as HTMLButtonElement).disabled)
    .toBe(true);
  expect(screen.getByText(/not a complete content or compliance export/i)).toBeTruthy();
  expect(screen.getByRole("button", { name: "Export account summary" })).toBeTruthy();
});
