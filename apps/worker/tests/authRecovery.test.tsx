// @vitest-environment happy-dom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  confirmPasswordReset: vi.fn(),
  meSettings: vi.fn(),
  refreshSession: vi.fn(),
  requestPasswordReset: vi.fn(),
}));
const native = vi.hoisted(() => ({
  clearDesktopSession: vi.fn(),
  isDesktop: true,
}));

vi.mock("../src/client", () => ({ client: api }));
vi.mock("../src/desktop", () => native);

import { AuthGate } from "../src/components/AuthGate";

beforeEach(() => {
  window.location.hash = "#/chat";
  vi.stubEnv("VITE_API_BASE", "https://kernel.boltrig.test");
  api.meSettings.mockRejectedValue(new Error("no session"));
  api.refreshSession.mockResolvedValue({ status: "ok" });
  native.clearDesktopSession.mockResolvedValue(undefined);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.unstubAllEnvs();
});

describe("Worker password recovery", () => {
  it("can clear broken local enrollment before cookie authentication", async () => {
    render(<AuthGate><div>Private Worker</div></AuthGate>);
    await screen.findByLabelText("Email");

    fireEvent.click(screen.getByRole("button", {
      name: "Reset local device enrollment",
    }));
    expect(native.clearDesktopSession).not.toHaveBeenCalled();
    expect(screen.getByText(/does not revoke the server device/i)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", {
      name: "Confirm local enrollment reset",
    }));
    await waitFor(() => expect(native.clearDesktopSession).toHaveBeenCalled());
    expect(screen.getByText(/browser sign-in was not changed/i)).toBeTruthy();
  });

  it("names a desktop build with no configured server instead of offering sign-in", async () => {
    vi.stubEnv("VITE_API_BASE", "");
    render(<AuthGate><div>Private Worker</div></AuthGate>);

    expect(await screen.findByText("No Boltrig server configured")).toBeTruthy();
    expect(screen.queryByLabelText("Email")).toBeNull();
    expect(screen.queryByText("Private Worker")).toBeNull();
  });

  it("offers recovery from sign-in and keeps the request result generic", async () => {
    api.requestPasswordReset.mockResolvedValue({
      status: "ok",
      message: "If the account can be recovered, reset instructions have been sent.",
    });
    render(<AuthGate><div>Private Worker</div></AuthGate>);
    const email = await screen.findByLabelText("Email");
    fireEvent.change(email, { target: { value: "owner@example.io" } });
    fireEvent.click(screen.getByRole("button", { name: "Forgot password?" }));
    expect(await screen.findByText("Reset your password")).toBeTruthy();
    expect((screen.getByLabelText("Email") as HTMLInputElement).value)
      .toBe("owner@example.io");
    fireEvent.click(screen.getByRole("button", { name: "Send reset link" }));
    await waitFor(() => expect(api.requestPasswordReset).toHaveBeenCalledWith({
      email: "owner@example.io",
    }));
    expect(await screen.findByText(
      "If the account can be recovered, reset instructions have been sent.",
    )).toBeTruthy();
  });

  it("redeems the reset-link token and hands off to sign-in", async () => {
    window.location.hash = "#/reset-password?token=boltrig_reset_exact-token";
    api.confirmPasswordReset.mockResolvedValue({ status: "ok" });
    render(<AuthGate><div>Private Worker</div></AuthGate>);

    fireEvent.change(await screen.findByLabelText("New password"), {
      target: { value: "new-password-456" },
    });
    fireEvent.change(screen.getByLabelText("Confirm new password"), {
      target: { value: "new-password-456" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Reset password" }));
    await waitFor(() => expect(api.confirmPasswordReset).toHaveBeenCalledWith({
      token: "boltrig_reset_exact-token",
      new_password: "new-password-456",
    }));
    expect(await screen.findByText("All existing browser sessions have been signed out."))
      .toBeTruthy();
    expect(screen.getByRole("button", { name: "Go to sign in" })).toBeTruthy();
  });

  it("renders the invitation screen when the hash changes in an open tab", async () => {
    render(<AuthGate><div>Private Worker</div></AuthGate>);
    await screen.findByLabelText("Email");

    window.location.hash = "#/accept-invite?token=invite-token";
    fireEvent(window, new Event("hashchange"));

    expect(await screen.findByText("Accept your invitation")).toBeTruthy();
  });
});
