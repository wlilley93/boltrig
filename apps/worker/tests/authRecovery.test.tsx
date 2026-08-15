// @vitest-environment happy-dom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { BoltrigApiError } from "@wlilley93/boltrig-web-sdk";

const api = vi.hoisted(() => ({
  acceptInvite: vi.fn(),
  changePassword: vi.fn(),
  confirmPasswordReset: vi.fn(),
  devices: vi.fn(),
  login: vi.fn(),
  meSettings: vi.fn(),
  refreshSession: vi.fn(),
  sessionCsrf: vi.fn(),
  requestPasswordReset: vi.fn(),
  startDeviceEnrollment: vi.fn(),
  twoFactorChallenge: vi.fn(),
  twoFactorEnrollBegin: vi.fn(),
  twoFactorVerifyEnroll: vi.fn(),
}));
const session = vi.hoisted(() => ({ rememberSessionCsrf: vi.fn() }));
const native = vi.hoisted(() => ({
  clearDesktopSession: vi.fn(),
  completeDesktopEnrollment: vi.fn(),
  desktopDeviceStatus: vi.fn(),
  isDesktop: true,
}));

vi.mock("../src/client", () => ({
  client: api,
  rememberSessionCsrf: session.rememberSessionCsrf,
}));
vi.mock("../src/desktop", () => native);

import { AuthGate } from "../src/components/AuthGate";

const completedAccount = (settings: Record<string, unknown> = {}) => ({
  profile: { id: "owner", email: "owner@example.io", role: "owner" },
  settings: { "setup.onboarding_version": 1, ...settings },
});

beforeEach(() => {
  window.location.hash = "#/chat";
  vi.stubEnv("VITE_API_BASE", "https://kernel.boltrig.test");
  api.acceptInvite.mockReset();
  api.changePassword.mockReset();
  api.confirmPasswordReset.mockReset();
  api.devices.mockReset();
  api.login.mockReset();
  api.meSettings.mockReset();
  api.refreshSession.mockReset();
  api.sessionCsrf.mockReset();
  api.requestPasswordReset.mockReset();
  api.startDeviceEnrollment.mockReset();
  api.twoFactorChallenge.mockReset();
  api.twoFactorEnrollBegin.mockReset();
  api.twoFactorVerifyEnroll.mockReset();
  api.meSettings.mockRejectedValue(new Error("no session"));
  api.refreshSession.mockResolvedValue({ status: "ok" });
  api.sessionCsrf.mockResolvedValue({ status: "ok", csrf_token: "desktop-csrf" });
  api.devices.mockResolvedValue({
    devices: [{
      id: "device_current",
      label: "Boltrig Desktop",
      public_key_fingerprint: "f".repeat(64),
      presence: "online",
      availability_mode: "unlocked_session",
      roots: [],
    }],
  });
  native.clearDesktopSession.mockResolvedValue(undefined);
  native.completeDesktopEnrollment.mockResolvedValue({
    device_id: "device_current",
    label: "Boltrig Desktop",
    public_key_fingerprint: "f".repeat(64),
    session_expires_at: "2030-01-02T00:00:00Z",
    lease_verifier_key_id: "a".repeat(64),
  });
  native.desktopDeviceStatus.mockResolvedValue({
    state: "online",
    device_id: "device_current",
    root_ids: [],
    reason: null,
  });
  session.rememberSessionCsrf.mockReset();
  localStorage.clear();
  document.documentElement.removeAttribute("data-character");
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.unstubAllEnvs();
  localStorage.clear();
});

describe("Worker password recovery", () => {
  it("applies the authoritative character before private UI first renders", async () => {
    api.meSettings.mockResolvedValue(completedAccount({ "agent.character": "jarvis" }));
    function PrivateWorker() {
      return (
        <div data-character-at-render={document.documentElement.dataset.character}>
          Private Worker
        </div>
      );
    }

    render(<AuthGate><PrivateWorker /></AuthGate>);

    const privateWorker = await screen.findByText("Private Worker");
    expect(privateWorker.getAttribute("data-character-at-render")).toBe("jarvis");
    expect(document.documentElement.dataset.character).toBe("jarvis");
    expect(api.meSettings).toHaveBeenCalledTimes(1);
    expect(api.sessionCsrf).toHaveBeenCalledTimes(1);
    expect(session.rememberSessionCsrf).toHaveBeenCalledWith("desktop-csrf");
  });

  it("retains the login response CSRF token before desktop connection starts", async () => {
    api.meSettings
      .mockRejectedValueOnce(new Error("no session"))
      .mockResolvedValue(completedAccount());
    api.login.mockResolvedValue({ status: "ok", csrf_token: "login-csrf" });
    render(<AuthGate><div>Private Worker</div></AuthGate>);

    fireEvent.change(await screen.findByLabelText("Email"), {
      target: { value: "owner@example.io" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "owner-password" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByText("Private Worker")).toBeTruthy();
    expect(session.rememberSessionCsrf).toHaveBeenCalledWith("login-csrf");
  });

  it("connects a new desktop automatically after account authentication", async () => {
    api.meSettings.mockResolvedValue(completedAccount());
    api.startDeviceEnrollment.mockResolvedValue({
      authorization_code: "one-time-bootstrap",
      expires_at: "2030-01-01T00:00:00Z",
      verification_uri: "/#/settings",
      lease_verifier: {
        algorithm: "Ed25519",
        key_id: "a".repeat(64),
        public_key: "pinned-public-key",
      },
    });
    native.desktopDeviceStatus.mockResolvedValue({
      state: "unenrolled",
      device_id: null,
      root_ids: [],
      reason: null,
    });

    render(<AuthGate><div>Private Worker</div></AuthGate>);

    expect(await screen.findByText("Private Worker")).toBeTruthy();
    expect(api.startDeviceEnrollment).toHaveBeenCalledWith("Boltrig Desktop");
    expect(native.completeDesktopEnrollment).toHaveBeenCalledWith(
      expect.objectContaining({ authorization_code: "one-time-bootstrap" }),
    );
  });

  it("requires confirmation before replacing a different account's local key", async () => {
    api.meSettings.mockResolvedValue(completedAccount());
    api.devices.mockResolvedValue({ devices: [] });
    native.desktopDeviceStatus.mockResolvedValue({
      state: "online",
      device_id: "device_from_another_account",
      root_ids: ["root_old"],
      reason: null,
    });
    api.startDeviceEnrollment.mockResolvedValue({
      authorization_code: "fresh-bootstrap",
      expires_at: "2030-01-01T00:00:00Z",
      verification_uri: "/#/settings",
      lease_verifier: {
        algorithm: "Ed25519",
        key_id: "a".repeat(64),
        public_key: "pinned-public-key",
      },
    });

    render(<AuthGate><div>Private Worker</div></AuthGate>);

    expect(await screen.findByText("Connect this computer")).toBeTruthy();
    expect(native.clearDesktopSession).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Replace local connection" }));
    await waitFor(() => expect(native.clearDesktopSession).toHaveBeenCalledTimes(1));
    expect(await screen.findByText("Private Worker")).toBeTruthy();
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
    api.acceptInvite.mockResolvedValue({ status: "ok", email: "invitee@example.io" });
    render(<AuthGate><div>Private Worker</div></AuthGate>);
    await screen.findByLabelText("Email");

    window.location.hash = "#/accept-invite?token=invite-token";
    fireEvent(window, new Event("hashchange"));

    expect(await screen.findByText("Accept your invitation")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("New password"), {
      target: { value: "invite-password-123" },
    });
    fireEvent.change(screen.getByLabelText("Confirm password"), {
      target: { value: "invite-password-123" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Set password" }));
    await waitFor(() => expect(api.acceptInvite).toHaveBeenCalledWith({
      token: "invite-token",
      password: "invite-password-123",
    }));
    expect(await screen.findByText("Your password is set for invitee@example.io."))
      .toBeTruthy();
  });

  it("completes the two-factor challenge without changing the login challenge token", async () => {
    api.meSettings
      .mockRejectedValueOnce(new Error("no session"))
      .mockResolvedValue(completedAccount());
    api.login.mockResolvedValue({
      status: "2fa_required",
      challenge_token: "challenge-exact-token",
    });
    api.twoFactorChallenge.mockResolvedValue({ status: "ok", csrf_token: "2fa-csrf" });
    render(<AuthGate><div>Private Worker</div></AuthGate>);

    fireEvent.change(await screen.findByLabelText("Email"), {
      target: { value: "owner@example.io" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "owner-password" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    fireEvent.change(await screen.findByLabelText("Verification code"), {
      target: { value: " 123456 " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Verify" }));

    await waitFor(() => expect(api.twoFactorChallenge).toHaveBeenCalledWith({
      challenge_token: "challenge-exact-token",
      code: "123456",
    }));
    expect(session.rememberSessionCsrf).toHaveBeenCalledWith("2fa-csrf");
    expect(await screen.findByText("Private Worker")).toBeTruthy();
  });

  it("requires the temporary password to be rotated before private UI mounts", async () => {
    api.meSettings
      .mockRejectedValueOnce(new BoltrigApiError(403, {
        detail: "password_change_required",
      }))
      .mockResolvedValue(completedAccount());
    api.changePassword.mockResolvedValue({ status: "ok" });
    render(<AuthGate><div>Private Worker</div></AuthGate>);

    fireEvent.change(await screen.findByLabelText("Current password"), {
      target: { value: "temporary-password" },
    });
    fireEvent.change(screen.getByLabelText("New password"), {
      target: { value: "new-password-456" },
    });
    fireEvent.change(screen.getByLabelText("Confirm new password"), {
      target: { value: "new-password-456" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Change password" }));

    await waitFor(() => expect(api.changePassword).toHaveBeenCalledWith({
      current_password: "temporary-password",
      new_password: "new-password-456",
    }));
    expect(await screen.findByText("Private Worker")).toBeTruthy();
  });

  it("finishes required two-factor enrollment before private UI mounts", async () => {
    api.meSettings
      .mockRejectedValueOnce(new BoltrigApiError(403, {
        detail: "two_factor_enrollment_required",
      }))
      .mockResolvedValue(completedAccount());
    api.twoFactorEnrollBegin.mockResolvedValue({
      status: "ok",
      secret: "AUTH-SECRET",
      otpauth_uri: "otpauth://totp/Boltrig:test",
      recovery_codes: ["recovery-one", "recovery-two"],
    });
    api.twoFactorVerifyEnroll.mockResolvedValue({ status: "ok" });
    render(<AuthGate><div>Private Worker</div></AuthGate>);

    expect(await screen.findByText("AUTH-SECRET")).toBeTruthy();
    expect(screen.getByText(/recovery-one/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Authenticator code"), {
      target: { value: " 654321 " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Finish setup" }));

    await waitFor(() => expect(api.twoFactorVerifyEnroll).toHaveBeenCalledWith({
      code: "654321",
    }));
    expect(await screen.findByText("Private Worker")).toBeTruthy();
  });

  it("rechecks a refresh 401 before returning an authenticated tab to sign-in", async () => {
    api.meSettings
      .mockResolvedValueOnce({
        ...completedAccount(),
      })
      .mockRejectedValueOnce(new BoltrigApiError(401, {}));
    api.refreshSession.mockRejectedValueOnce(new BoltrigApiError(401, {}));
    render(<AuthGate><div>Private Worker</div></AuthGate>);

    await screen.findByText("Private Worker");
    fireEvent(document, new Event("visibilitychange"));

    await waitFor(() => expect(api.refreshSession).toHaveBeenCalled());
    await waitFor(() => expect(api.meSettings).toHaveBeenCalledTimes(2));
    expect(await screen.findByLabelText("Email")).toBeTruthy();
  });
});
