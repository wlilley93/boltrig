// @vitest-environment happy-dom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  aiKeys: vi.fn(),
  chatModelChoices: vi.fn(),
  meSettings: vi.fn(),
  putMeSettings: vi.fn(),
  setAiKey: vi.fn(),
  updateMeProfile: vi.fn(),
}));

vi.mock("../src/client", () => ({ client: api }));
vi.mock("../src/components/familiar/FamiliarStage", () => ({
  FamiliarStage: () => <div data-testid="familiar-preview" />,
}));
vi.mock("../src/components/familiar/FamiliarBadge", () => ({
  FamiliarBadge: () => <div data-testid="familiar-poster" />,
}));
vi.mock("../src/components/jarvis/JarvisStage", () => ({
  JarvisStage: () => <div data-testid="jarvis-preview" />,
}));

import { OnboardingGate } from "../src/components/onboarding/OnboardingGate";

const profile = { id: "owner", email: "owner@example.io", role: "superadmin" };

beforeEach(() => {
  localStorage.clear();
  api.aiKeys.mockReset().mockResolvedValue({ allow_own_ai_keys: true, ai_keys: [] });
  api.chatModelChoices.mockReset().mockResolvedValue({
    status: "ok",
    reason: null,
    choices: [],
    default_model_name: "openai/gpt-5.4",
    default_available: true,
  });
  api.meSettings.mockReset();
  api.putMeSettings.mockReset().mockResolvedValue({ status: "ok" });
  api.setAiKey.mockReset().mockResolvedValue({ status: "ok" });
  api.updateMeProfile.mockReset().mockResolvedValue({ status: "ok" });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  localStorage.clear();
});

describe("first-run onboarding", () => {
  it("requires a name and supports keyboard companion selection", () => {
    render(
      <OnboardingGate initialAccount={{
        profile,
        settings: { "setup.onboarding_version": 0 },
      }}>
        <div>Private workspace</div>
      </OnboardingGate>,
    );

    const continueButton = screen.getByRole("button", { name: "Continue" });
    expect((continueButton as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("What should Boltrig call you?"), {
      target: { value: "William" },
    });
    expect((continueButton as HTMLButtonElement).disabled).toBe(false);

    const familiar = screen.getByRole("radio", { name: /Familiar/ });
    familiar.focus();
    fireEvent.keyDown(familiar, { key: "ArrowRight" });
    expect(screen.getByRole("radio", { name: /Jarvis/ }).getAttribute("aria-checked"))
      .toBe("true");
  });

  it("does not interrupt upgraded accounts without the version marker", () => {
    render(
      <OnboardingGate initialAccount={{ profile, settings: {} }}>
        <div>Existing workspace</div>
      </OnboardingGate>,
    );

    expect(screen.getByText("Existing workspace")).toBeTruthy();
    expect(screen.queryByText("Choose your companion")).toBeNull();
    expect(api.chatModelChoices).not.toHaveBeenCalled();
  });

  it("chooses Jarvis, clears a write-only key, and persists completion", async () => {
    render(
      <OnboardingGate initialAccount={{
        profile,
        settings: { "setup.onboarding_version": 0 },
      }}>
        <div>Private workspace</div>
      </OnboardingGate>,
    );

    expect(screen.getByText("Choose your companion")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("What should Boltrig call you?"), {
      target: { value: "William" },
    });
    fireEvent.click(screen.getByRole("radio", { name: /Jarvis/ }));
    expect(screen.getByTestId("jarvis-preview")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));

    expect(await screen.findByText("Workspace AI is ready")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Exact model"), {
      target: { value: "openai/gpt-5.4" },
    });
    const secret = screen.getByLabelText("Provider API key") as HTMLInputElement;
    fireEvent.change(secret, { target: { value: "secret-provider-value" } });
    fireEvent.click(screen.getByRole("button", { name: "Seal provider key" }));

    expect(api.setAiKey).toHaveBeenCalledWith(expect.objectContaining({
      level: "user",
      provider: "openai",
      model: "openai/gpt-5.4",
      api_key: "secret-provider-value",
    }));
    expect(secret.value).toBe("");
    expect(await screen.findByText("Key sealed. Boltrig cannot retrieve or display it."))
      .toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(screen.getByText("You’re ready, William. Meet Jarvis.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Start using Boltrig" }));

    await waitFor(() => expect(api.putMeSettings).toHaveBeenCalledWith({
      settings: {
        "agent.character": "jarvis",
        "setup.onboarding_version": 1,
      },
    }));
    expect(api.updateMeProfile).toHaveBeenCalledWith({ display_name: "William" });
    expect(await screen.findByText("Private workspace")).toBeTruthy();
    expect(localStorage.getItem("boltrig.character")).toBe("jarvis");
  });

  it("lets a member finish when the organisation manages keys", async () => {
    api.chatModelChoices.mockResolvedValue({
      status: "unavailable",
      reason: "not_configured",
      choices: [],
      default_available: false,
    });
    api.aiKeys.mockResolvedValue({ allow_own_ai_keys: false, ai_keys: [] });
    render(
      <OnboardingGate initialAccount={{
        profile: { ...profile, role: "member" },
        settings: { "setup.onboarding_version": 0 },
      }}>
        <div>Member workspace</div>
      </OnboardingGate>,
    );

    fireEvent.change(screen.getByLabelText("What should Boltrig call you?"), {
      target: { value: "Alex" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(await screen.findByText("Your organisation manages provider keys")).toBeTruthy();
    expect(screen.queryByLabelText("Provider API key")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    fireEvent.click(screen.getByRole("button", { name: "Start using Boltrig" }));
    expect(await screen.findByText("Member workspace")).toBeTruthy();
  });
});
