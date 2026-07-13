import { describe, it, expect, vi, beforeEach } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { AuthGate } from "@/panels/AuthGate";
import { ChallengeStep } from "@/panels/AuthGate/ChallengeStep";
import { LoginPage } from "@/panels/AuthGate/LoginPage";
import { AcceptInvitePage } from "@/panels/AuthGate/AcceptInvitePage";
import { EnrollFlow } from "@/panels/AuthGate/EnrollFlow";
import { api } from "@/api/client";
import { ApiError } from "@/api/transport";
import { navigate } from "@/router";
import { getAuthState, markEnrollRequired, markUnauthenticated, probeSession } from "@/auth";

beforeEach(() => {
  vi.restoreAllMocks();
  cleanup();
  markUnauthenticated();
});

function mockEnrollBegin() {
  return vi.spyOn(api, "twoFactorEnrollBegin").mockResolvedValue({
    status: "ok",
    secret: "TESTSECRET",
    otpauth_uri: "otpauth://test",
    recovery_codes: ["aaaa-bbbb-cccc", "dddd-eeee-ffff"],
  } as Awaited<ReturnType<typeof api.twoFactorEnrollBegin>>);
}

describe("AuthGate", () => {
  it("renders the public accept-invite page without crashing", async () => {
    render(
      <AuthGate>
        <div>App</div>
      </AuthGate>,
    );
    navigate("/accept-invite?token=test-token");
    expect(await waitFor(() => screen.getByRole("heading", { name: "Set your password" }))).toBeDefined();
  });

  it("renders the login gate when unauthenticated", async () => {
    render(
      <AuthGate>
        <div>App</div>
      </AuthGate>,
    );
    navigate("/");
    expect(await waitFor(() => screen.getByRole("heading", { name: "Sign in" }))).toBeDefined();
  });

  it("renders the enrollment flow when required", async () => {
    mockEnrollBegin();
    markEnrollRequired();
    render(
      <AuthGate>
        <div>App</div>
      </AuthGate>,
    );
    expect(await screen.findByRole("heading", { name: "Set up two-factor" })).toBeDefined();
  });
});

describe("auth probe", () => {
  it("fails closed on probe errors", async () => {
    vi.spyOn(api, "meSettings").mockRejectedValue(
      new ApiError(500, "GET /v1/me/settings -> 500", { status: "error" }),
    );

    await probeSession();

    expect(getAuthState().status).toBe("unauthenticated");
  });
});

describe("AuthGate internal components", () => {
  it("renders the login page directly", () => {
    render(<LoginPage />);
    expect(screen.getByRole("heading", { name: "Sign in" })).toBeDefined();
  });

  it("renders the challenge step directly", () => {
    render(<ChallengeStep challengeToken="test-challenge" />);
    expect(screen.getByRole("button", { name: "Verify and sign in" })).toBeDefined();
  });

  it("renders the accept-invite page directly", () => {
    navigate("/accept-invite?token=test-token");
    render(<AcceptInvitePage />);
    expect(screen.getByRole("heading", { name: "Set your password" })).toBeDefined();
  });

  it("renders the enrollment flow directly", async () => {
    mockEnrollBegin();
    render(<EnrollFlow />);
    expect(await screen.findByRole("heading", { name: "Set up two-factor" })).toBeDefined();
  });
});
