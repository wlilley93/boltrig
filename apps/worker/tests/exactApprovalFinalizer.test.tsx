// @vitest-environment happy-dom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  invokeApprovalState: vi.fn(),
}));

vi.mock("../src/client", () => ({ client: api }));

import {
  ExactApprovalFinalizer,
  useExactApprovalFinalizer,
} from "../src/components/ExactApprovalFinalizer";

afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

it("keeps a fresh exact approval handle when a stale resource snapshot re-pends", async () => {
  const replay = vi.fn()
    .mockResolvedValueOnce({
      status: "pending_human",
      hitl_request_id: "approval-2",
    })
    .mockResolvedValueOnce({ status: "ok" });
  const applied = vi.fn();
  api.invokeApprovalState.mockResolvedValue({ status: "approved" });

  function Harness() {
    const controller = useExactApprovalFinalizer<
      { value: string },
      { status: string; hitl_request_id?: string }
    >({
      isCurrent: (input) => input.value === "exact",
      replay,
      onApplied: applied,
    });
    return (
      <>
        <button
          onClick={() => controller.begin(
            { value: "exact" },
            { status: "pending_human", hitl_request_id: "approval-1" },
            "Exact change",
          )}
        >
          Begin
        </button>
        <ExactApprovalFinalizer controller={controller} />
      </>
    );
  }

  render(<Harness />);
  fireEvent.click(screen.getByRole("button", { name: "Begin" }));
  fireEvent.click(await screen.findByRole("button", {
    name: "Check approval and apply exact change",
  }));
  await waitFor(() => expect(replay).toHaveBeenCalledWith(
    { value: "exact" },
    "approval-1",
  ));

  fireEvent.click(await screen.findByRole("button", {
    name: "Check approval and apply exact change",
  }));
  await waitFor(() => expect(replay).toHaveBeenLastCalledWith(
    { value: "exact" },
    "approval-2",
  ));
  expect(applied).toHaveBeenCalledOnce();
});
