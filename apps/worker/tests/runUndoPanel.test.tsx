// @vitest-environment happy-dom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { RunUndoPanel } from "../src/components/chat/RunUndoPanel";

afterEach(cleanup);

const effect = (seq: number, undoable: boolean, summary: string) => ({
  seq,
  verb: undoable ? "calendar.create_event" : "email.send",
  status: undoable ? ("recorded" as const) : ("not_undoable" as const),
  undoable,
  summary,
  created_at: "2026-08-21T12:00:00Z",
});

describe("RunUndoPanel", () => {
  it("lists each step with its honest undoability and only counts what reverts", async () => {
    const api = {
      runEffects: vi.fn().mockResolvedValue({
        run_id: "r1",
        effects: [effect(1, true, "meeting created"), effect(2, false, "email sent")],
      }),
      revertRun: vi.fn(),
    };
    render(<RunUndoPanel runId="r1" api={api} />);
    fireEvent.click(screen.getByRole("button", { name: /Undo actions/ }));

    await waitFor(() => expect(screen.getByText("meeting created")).toBeTruthy());
    expect(screen.getByText("Can't be undone")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Undo this action" })).toBeTruthy();
    expect(api.revertRun).not.toHaveBeenCalled();
  });

  it("reverts on confirm and renders per-step outcomes", async () => {
    const api = {
      runEffects: vi.fn().mockResolvedValue({
        run_id: "r2",
        effects: [effect(1, true, "meeting created")],
      }),
      revertRun: vi.fn().mockResolvedValue({
        run_id: "r2",
        results: [{ ...effect(1, false, "meeting created"), outcome: "reverted" }],
      }),
    };
    render(<RunUndoPanel runId="r2" api={api} />);
    fireEvent.click(screen.getByRole("button", { name: /Undo actions/ }));
    await waitFor(() => screen.getByRole("button", { name: "Undo this action" }));
    fireEvent.click(screen.getByRole("button", { name: "Undo this action" }));

    await waitFor(() => expect(screen.getByText("Undone")).toBeTruthy());
    expect(api.revertRun).toHaveBeenCalledExactlyOnceWith("r2", undefined);
  });

  it("carries a pending approval back so the SAME grant finishes the undo", async () => {
    const api = {
      runEffects: vi.fn().mockResolvedValue({
        run_id: "r3",
        effects: [effect(3, true, "event removed pending")],
      }),
      revertRun: vi
        .fn()
        .mockResolvedValueOnce({
          run_id: "r3",
          results: [{
            ...effect(3, true, "event removed pending"),
            outcome: "approval_pending",
            approval_id: "req-9",
          }],
        })
        .mockResolvedValueOnce({
          run_id: "r3",
          results: [{ ...effect(3, false, "event removed pending"), outcome: "reverted" }],
        }),
    };
    render(<RunUndoPanel runId="r3" api={api} />);
    fireEvent.click(screen.getByRole("button", { name: /Undo actions/ }));
    await waitFor(() => screen.getByRole("button", { name: "Undo this action" }));
    fireEvent.click(screen.getByRole("button", { name: "Undo this action" }));

    await waitFor(() => expect(screen.getByText("Waiting for your approval")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "Finish undo" }));

    await waitFor(() => expect(screen.getByText("Undone")).toBeTruthy());
    expect(api.revertRun).toHaveBeenLastCalledWith("r3", { "3": "req-9" });
  });

  it("says so plainly when a turn changed nothing", async () => {
    const api = {
      runEffects: vi.fn().mockResolvedValue({ run_id: "r4", effects: [] }),
      revertRun: vi.fn(),
    };
    render(<RunUndoPanel runId="r4" api={api} />);
    fireEvent.click(screen.getByRole("button", { name: /Undo actions/ }));

    await waitFor(() =>
      expect(screen.getByText("This turn made no reversible changes.")).toBeTruthy(),
    );
  });
});
