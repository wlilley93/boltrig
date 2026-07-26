// Forced rotation of a provisioning credential ([2026] VJS-COUNTY 8, D7).
//
// The backend clamp is proved in tests/security/test_forced_password_rotation.py.
// This proves the console does not STRAND the operator it clamps: without a
// screen, a seeded account holds a session that can reach exactly two endpoints
// and the app renders nothing useful for either.

import { describe, it, expect, vi, beforeEach } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { AuthGate } from "@/panels/AuthGate";
import { ChangePasswordPage } from "@/panels/AuthGate/ChangePasswordPage";
import { api } from "@/api/client";
import { ApiError } from "@/api/transport";
import {
  getAuthState,
  markPasswordChangeRequired,
  markUnauthenticated,
  probeSession,
} from "@/auth";

beforeEach(() => {
  vi.restoreAllMocks();
  cleanup();
  markUnauthenticated();
});

function fill(label: string, value: string) {
  const field = screen.getByText(label).parentElement?.querySelector("input");
  expect(field).toBeDefined();
  fireEvent.change(field as HTMLInputElement, { target: { value } });
}

describe("forced password rotation (COUNTY 8 D7)", () => {
  it("renders the rotation screen when the account is clamped", async () => {
    markPasswordChangeRequired();
    render(
      <AuthGate>
        <div>App</div>
      </AuthGate>,
    );
    expect(
      await waitFor(() =>
        screen.getByRole("heading", { name: "Choose a new password" }),
      ),
    ).toBeDefined();
    // The app itself must NOT be behind it.
    expect(screen.queryByText("App")).toBeNull();
  });

  it("routes a clamped PROBE to the screen rather than the login page", async () => {
    // The clamp is evaluated every request, so a session that was fine a moment
    // ago is clamped the instant the flag is set. Treating that 403 as "logged
    // out" would bounce the operator to a login they can complete forever without
    // getting anywhere.
    vi.spyOn(api, "meSettings").mockRejectedValue(
      new ApiError(403, "forbidden", { detail: "password_change_required" }),
    );
    await probeSession();
    expect(getAuthState().status).toBe("password_change_required");
  });

  it("sends the current and new password, then opens the app", async () => {
    const call = vi
      .spyOn(api, "changePassword")
      .mockResolvedValue({ status: "ok" });
    render(<ChangePasswordPage />);

    fill("Current password", "provisioning-password-123");
    fill("New password", "a-properly-rotated-password-456");
    fill("Confirm new password", "a-properly-rotated-password-456");
    fireEvent.click(screen.getByRole("button", { name: "Save and continue" }));

    await waitFor(() => expect(call).toHaveBeenCalled());
    expect(call).toHaveBeenCalledWith({
      current_password: "provisioning-password-123",
      new_password: "a-properly-rotated-password-456",
    });
    await waitFor(() => expect(getAuthState().status).toBe("authenticated"));
  });

  it("shows the server's refusal instead of pretending it worked", async () => {
    vi.spyOn(api, "changePassword").mockResolvedValue({
      status: "error",
      reason: "the new password must differ",
    });
    render(<ChangePasswordPage />);

    fill("Current password", "provisioning-password-123");
    fill("New password", "provisioning-password-123");
    fill("Confirm new password", "provisioning-password-123");
    fireEvent.click(screen.getByRole("button", { name: "Save and continue" }));

    expect(
      await waitFor(() => screen.getByText("the new password must differ")),
    ).toBeDefined();
    // Still clamped: a refused rotation must not open the app.
    expect(getAuthState().status).not.toBe("authenticated");
  });

  it("will not submit a mismatched confirmation", () => {
    const call = vi.spyOn(api, "changePassword");
    render(<ChangePasswordPage />);

    fill("Current password", "provisioning-password-123");
    fill("New password", "a-properly-rotated-password-456");
    fill("Confirm new password", "something-else-entirely-789");

    expect(screen.getByText("Those do not match.")).toBeDefined();
    const submit = screen.getByRole("button", { name: "Save and continue" });
    expect((submit as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(submit);
    expect(call).not.toHaveBeenCalled();
  });

  it("offers no way past the screen except signing out", () => {
    render(<ChangePasswordPage />);
    const labels = screen
      .getAllByRole("button")
      .map((b) => b.textContent?.trim());
    // A skip or "later" control would be the whole defect: the hazard is that the
    // provisioning credential SURVIVES, and a dismissable prompt is how it does.
    expect(labels).toEqual(["Save and continue", "Sign out"]);
  });
});
