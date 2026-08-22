// @vitest-environment happy-dom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { MoodResetRow } from "../src/components/settings/CompanionRows";

afterEach(cleanup);

describe("MoodResetRow", () => {
  it("arms on the first press and resets only on the second", async () => {
    const api = { resetEmotion: vi.fn().mockResolvedValue({ status: "ok" }) };
    render(<MoodResetRow busy={false} api={api} />);

    fireEvent.click(screen.getByRole("button", { name: "Reset mood" }));
    expect(api.resetEmotion).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Really reset?" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Mood reset" })).toBeTruthy());
    expect(api.resetEmotion).toHaveBeenCalledOnce();
    expect(screen.getByText(/Memory, knowledge and your data are untouched/)).toBeTruthy();
  });

  it("says plainly when the reset failed", async () => {
    const api = { resetEmotion: vi.fn().mockRejectedValue(new Error("down")) };
    render(<MoodResetRow busy={false} api={api} />);
    fireEvent.click(screen.getByRole("button", { name: "Reset mood" }));
    fireEvent.click(screen.getByRole("button", { name: "Really reset?" }));

    await waitFor(() => expect(screen.getByText(/didn't go through/)).toBeTruthy());
  });
});
