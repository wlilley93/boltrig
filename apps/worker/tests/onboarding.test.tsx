// @vitest-environment happy-dom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { providerApiBaseUrl, providerNeedsBaseUrl } from "../src/components/onboarding/providerCatalogue";

const api = vi.hoisted(() => ({
  activateAiKey: vi.fn(),
  aiKeys: vi.fn(),
  approveAiKeyProposal: vi.fn(),
  chatModelChoices: vi.fn(),
  integrationCatalogue: vi.fn(),
  integrationConnections: vi.fn(),
  meSettings: vi.fn(),
  putMeSettings: vi.fn(),
  setAiKey: vi.fn(),
  submitIntegrationSecret: vi.fn(),
  updateMeProfile: vi.fn(),
}));

vi.mock("../src/client", () => ({ client: api }));
vi.mock("../src/components/familiar/FamiliarStage", () => ({
  FamiliarStage: () => <div data-testid="familiar-preview" />,
}));
vi.mock("../src/components/jarvis/JarvisStage", () => ({
  JarvisStage: () => <div data-testid="jarvis-preview" />,
}));

import { OnboardingGate } from "../src/components/onboarding/OnboardingGate";

const profile = { id: "owner", email: "owner@example.io", role: "superadmin" };

beforeEach(() => {
  localStorage.clear();
  vi.stubEnv("VITE_DESKTOP_DOWNLOAD_URL", "https://downloads.boltrig.test/desktop");
  api.activateAiKey.mockReset().mockResolvedValue({ status: "ok" });
  api.aiKeys.mockReset().mockResolvedValue({ allow_own_ai_keys: true, ai_keys: [] });
  api.approveAiKeyProposal.mockReset().mockResolvedValue({ status: "ok" });
  api.chatModelChoices.mockReset().mockResolvedValue({
    status: "ok",
    reason: null,
    choices: [],
    default_model_name: "openai/gpt-5.4",
    default_available: true,
  });
  api.integrationCatalogue.mockReset().mockResolvedValue({
    integrations: [{
      id: "xai-voice",
      label: "xAI Voice",
      category: "communications",
      transport: "rest",
      auth: ["manual_secret"],
      description: "Speech",
      certification: "certified",
      available: true,
      setup_supported: true,
      setup_contract: {
        kind: "manual_secret",
        version: "xai_voice_v1",
        fields: [{
          name: "api_key",
          label: "xAI API key",
          input_kind: "api_key",
          secret: true,
          required: true,
          min_length: 8,
          max_length: 4096,
        }],
      },
      enabled_tools: [],
    }],
  });
  api.integrationConnections.mockReset().mockResolvedValue({ connections: [] });
  api.meSettings.mockReset();
  api.putMeSettings.mockReset().mockResolvedValue({ status: "ok" });
  api.setAiKey.mockReset().mockResolvedValue({ status: "ok" });
  api.submitIntegrationSecret.mockReset().mockResolvedValue({
    status: "connected",
    connection: {
      id: "voice-connection",
      integration_id: "xai-voice",
      label: "xAI Voice",
      health: "pending",
      credential_ref_present: true,
      accounts: [],
      enabled_tools: [],
      created_at: "2026-08-15T10:00:00Z",
    },
  });
  api.updateMeProfile.mockReset().mockResolvedValue({ status: "ok" });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.unstubAllEnvs();
  localStorage.clear();
});

/**
 * Click a control once it is BOTH there and usable.
 *
 * WHY EVERY CLICK IN THIS FILE GOES THROUGH IT. `await findByText("Add vision")`
 * looks like it waits for the vision step, and it does not: that heading is
 * painted by THREE different states -- the Suspense skeleton while the lazy
 * chunk resolves, the real step before its readiness probe returns, and the
 * loaded step. "Skip for now" exists only in the third. So the awaited line was
 * satisfied by a loading state and the synchronous getByRole on the next line
 * raced a dynamic import against one setTimeout(0).
 *
 * It passed because tests earlier in the file had already resolved the lazy()
 * handles, leaving a margin of exactly one macrotask turn -- which is why the
 * failure showed up once, in a full run, and never again in isolation.
 * `--sequence.seed=7` reproduces it every time.
 *
 * The fix is applied to EVERY click rather than to the seven sites that were
 * racing, because deciding per line which ones are safe is precisely the
 * judgement that was wrong seven times. Waiting for a control that was already
 * present and enabled costs nothing.
 *
 * Re-queried inside waitFor rather than captured once: a step transition can
 * replace the node, and reading `disabled` off a detached element is a check
 * that always passes.
 */
async function clickWhenReady(name: string): Promise<void> {
  const control = await waitFor(() => {
    const button = screen.getByRole("button", { name }) as HTMLButtonElement;
    expect(button.disabled).toBe(false);
    return button;
  });
  fireEvent.click(control);
}

describe("first-run onboarding", () => {
  it("requires a name on the first page before showing both companion entities", () => {
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
    expect(screen.getByText("What should Boltrig call you?")).toBeTruthy();
    expect(screen.queryByRole("radiogroup", { name: "Companion" })).toBeNull();
    const nameInput = screen.getByLabelText("Your name");
    fireEvent.keyDown(nameInput, { key: "Enter" });
    expect(screen.getByText("What should Boltrig call you?")).toBeTruthy();
    fireEvent.change(nameInput, {
      target: { value: "William" },
    });
    expect((continueButton as HTMLButtonElement).disabled).toBe(false);
    fireEvent.keyDown(nameInput, { key: "Enter" });

    expect(screen.getByText("Choose your companion")).toBeTruthy();
    const back = screen.getByRole("button", { name: "← Back" });
    expect(back.closest("footer")?.classList.contains("onboarding-actions")).toBe(true);
    // One card at a time: Familiar is slot one, Jarvis is not rendered yet.
    expect(screen.getByTestId("familiar-preview")).toBeTruthy();
    expect(screen.queryByTestId("jarvis-preview")).toBeNull();
    // The dots are the keyboard control, so arrowing along them is the
    // behaviour worth protecting -- it is the only way to walk the rail
    // without a pointer.
    const familiar = screen.getByRole("radio", { name: "Familiar" });
    familiar.focus();
    fireEvent.keyDown(familiar, { key: "ArrowRight" });
    expect(screen.getByRole("radio", { name: "Jarvis" }).getAttribute("aria-checked"))
      .toBe("true");
    expect(screen.getByTestId("jarvis-preview")).toBeTruthy();
    // Arrowing past the end must not wrap: this is a list, not a carousel.
    const jarvis = screen.getByRole("radio", { name: "Jarvis" });
    fireEvent.keyDown(jarvis, { key: "ArrowRight" });
    expect(screen.getByRole("radio", { name: "Ultron" }).getAttribute("aria-checked"))
      .toBe("true");
    fireEvent.keyDown(screen.getByRole("radio", { name: "Ultron" }), { key: "ArrowRight" });
    expect(screen.getByRole("radio", { name: "Colossus" }).getAttribute("aria-checked"))
      .toBe("true");
    // And Colossus is the end of the rail, so this one goes nowhere.
    fireEvent.keyDown(screen.getByRole("radio", { name: "Colossus" }), { key: "ArrowRight" });
    expect(screen.getByRole("radio", { name: "Colossus" }).getAttribute("aria-checked"))
      .toBe("true");
  });

  it("uses Enter to continue without stealing Enter from an open picker", async () => {
    render(
      <OnboardingGate initialAccount={{
        profile,
        settings: { "setup.onboarding_version": 0 },
      }}>
        <div>Private workspace</div>
      </OnboardingGate>,
    );

    const nameInput = screen.getByLabelText("Your name");
    fireEvent.change(nameInput, { target: { value: "Alex" } });
    fireEvent.keyDown(nameInput, { key: "Enter" });
    expect(screen.getByText("Choose your companion")).toBeTruthy();

    fireEvent.keyDown(document.body, { key: "Enter" });
    expect(await screen.findByText("Choose your AI provider")).toBeTruthy();
    await clickWhenReady("OpenAI");
    const providerSearch = screen.getByRole("searchbox", { name: "Search providers" });
    fireEvent.change(providerSearch, { target: { value: "Llama" } });
    fireEvent.keyDown(providerSearch, { key: "Enter" });
    expect(screen.getByText("Choose your AI provider")).toBeTruthy();

    fireEvent.keyDown(providerSearch, { key: "Escape" });
    fireEvent.keyDown(document.body, { key: "Enter" });
    expect(await screen.findByText("Add vision")).toBeTruthy();
    await waitFor(() => expect((screen.getByRole("button", { name: "Continue" }) as HTMLButtonElement).disabled).toBe(false));
    fireEvent.keyDown(document.body, { key: "Enter" });
    expect(await screen.findByText("Add voice")).toBeTruthy();
    await waitFor(() => expect((screen.getByRole("button", { name: "Continue" }) as HTMLButtonElement).disabled).toBe(false));
    fireEvent.keyDown(document.body, { key: "Enter" });
    expect(await screen.findByText("You’re ready, Alex. Meet Familiar.")).toBeTruthy();
  });

  it("keeps chat unavailable when the completion marker is missing", () => {
    render(
      <OnboardingGate initialAccount={{ profile, settings: {} }}>
        <div>Existing workspace</div>
      </OnboardingGate>,
    );

    expect(screen.getByText("What should Boltrig call you?")).toBeTruthy();
    expect(screen.queryByText("Existing workspace")).toBeNull();
  });

  it("mounts chat only after the current onboarding version is persisted", () => {
    render(
      <OnboardingGate initialAccount={{
        profile,
        settings: { "setup.onboarding_version": 1 },
      }}>
        <div>Completed workspace</div>
      </OnboardingGate>,
    );

    expect(screen.getByText("Completed workspace")).toBeTruthy();
    expect(screen.queryByText("What should Boltrig call you?")).toBeNull();
    expect(api.chatModelChoices).not.toHaveBeenCalled();
  });

  it("fails closed when setup state cannot be loaded", async () => {
    api.meSettings.mockRejectedValue(new Error("settings unavailable"));
    render(
      <OnboardingGate>
        <div>Private workspace</div>
      </OnboardingGate>,
    );

    expect(await screen.findByText("Setup couldn’t load."))
      .toBeTruthy();
    expect(screen.queryByText("Private workspace")).toBeNull();
  });

  it("chooses Jarvis, connects the selected provider on Continue, and persists completion", async () => {
    render(
      <OnboardingGate initialAccount={{
        profile,
        settings: { "setup.onboarding_version": 0 },
      }}>
        <div>Private workspace</div>
      </OnboardingGate>,
    );

    expect(screen.getByText("What should Boltrig call you?")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Your name"), {
      target: { value: "William" },
    });
    await clickWhenReady("Continue");
    // ONE CARD AT A TIME. Familiar is slot one, so she is what the step opens
    // on and Jarvis is not rendered at all until the rail is walked.
    expect(screen.getByTestId("familiar-preview")).toBeTruthy();
    expect(screen.queryByTestId("jarvis-preview")).toBeNull();
    // No left chevron on the first companion: it is ABSENT, not disabled.
    expect(screen.queryByRole("button", { name: /Show Familiar/ })).toBeNull();
    await clickWhenReady("Show Jarvis");
    expect(screen.getByTestId("jarvis-preview")).toBeTruthy();
    expect(screen.queryByTestId("familiar-preview")).toBeNull();
    // Jarvis is in the MIDDLE now that Ultron exists, so he has both chevrons.
    expect(screen.queryByRole("button", { name: "Show Familiar" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Show Ultron" })).toBeTruthy();
    // The end of the rail is where the right chevron disappears -- that was
    // always the assertion, and the end has simply moved along again.
    await clickWhenReady("Show Ultron");
    expect(document.querySelectorAll(".companion-chevron.right")).toHaveLength(1);
    await clickWhenReady("Show Colossus");
    expect(document.querySelectorAll(".companion-chevron.right")).toHaveLength(0);
    expect(screen.queryByRole("button", { name: /Show / })).toBeTruthy();
    await clickWhenReady("Show Ultron");
    await clickWhenReady("Show Jarvis");
    // The dots carry the choice for anyone not using the picture.
    expect(screen.getByRole("radio", { name: "Jarvis" }).getAttribute("aria-checked"))
      .toBe("true");
    await clickWhenReady("Continue");

    expect(await screen.findByText("Choose your AI provider")).toBeTruthy();
    const secret = await screen.findByLabelText("Provider API key") as HTMLInputElement;
    fireEvent.change(secret, { target: { value: "secret-provider-value" } });
    await clickWhenReady("Choose a model");
    fireEvent.change(screen.getByLabelText("Search models"), { target: { value: "GPT-5.4" } });
    fireEvent.click(screen.getByRole("option", { name: /GPT-5\.4 Text \+ vision$/ }));
    expect(screen.getByText("Text and Vision")).toBeTruthy();
    expect(screen.getByText("Your model handles text and vision — you can skip the vision step.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Save provider" })).toBeNull();
    await clickWhenReady("Continue");

    await waitFor(() => expect(api.setAiKey).toHaveBeenCalledWith(expect.objectContaining({
      level: "user",
      provider: "openai",
      model: "openai/gpt-5.4",
      modality: "text",
      api_key: "secret-provider-value",
    })));
    expect(secret.value).toBe("");
    expect(await screen.findByText("Add vision")).toBeTruthy();
    await clickWhenReady("Skip for now");
    expect(await screen.findByText("Add voice")).toBeTruthy();
    await clickWhenReady("Skip for now");
    expect(await screen.findByText("You’re ready, William. Meet Jarvis.")).toBeTruthy();
    expect(screen.getByText(/run and take approved actions locally on your personal computer/i)).toBeTruthy();
    const download = screen.getByRole("link", { name: /Download Boltrig Desktop/ });
    expect(download.getAttribute("href")).toBe("https://downloads.boltrig.test/desktop");
    await clickWhenReady("Continue in browser");

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

  it("searches the bindable provider catalogue and gates model choice on a key", async () => {
    render(
      <OnboardingGate initialAccount={{
        profile,
        settings: { "setup.onboarding_version": 0 },
      }}>
        <div>Private workspace</div>
      </OnboardingGate>,
    );

    fireEvent.change(screen.getByLabelText("Your name"), { target: { value: "Alex" } });
    await clickWhenReady("Continue");
    await clickWhenReady("Continue");
    expect(await screen.findByText("Choose your AI provider")).toBeTruthy();
    expect((await screen.findByRole("button", { name: "Enter your API key first" }) as HTMLButtonElement).disabled)
      .toBe(true);

    // Was Llama. Meta's Llama API is in the models.dev snapshot but is not one
    // of the providers Bifrost binds, so offering it produced a picker entry
    // that failed at submit. The search is exercised with a provider that can
    // actually complete.
    await clickWhenReady("OpenAI");
    fireEvent.change(screen.getByLabelText("Search providers"), { target: { value: "groq" } });
    fireEvent.click(screen.getByRole("option", { name: /Groq/ }));
    expect(screen.getByRole("button", { name: "Groq" })).toBeTruthy();

    fireEvent.change(screen.getByLabelText("Provider API key"), { target: { value: "groq-key" } });
    await clickWhenReady("Choose a model");
    expect(screen.getAllByRole("option").length).toBeGreaterThan(0);
  });

  it("offers the full catalogue again, now that the kernel custom-binds it", async () => {
    // HISTORY, because this test has said opposite things and both were right
    // at the time. The picker once offered the whole snapshot while the kernel
    // bound 23, so these three providers failed AT SUBMIT and this test pinned
    // their ABSENCE. The kernel now binds any catalogue provider as an
    // OpenAI-compatible custom provider through its published base URL, so
    // their absence would be the defect. Each must be findable and carry a
    // real address for the silent-submit path.
    render(
      <OnboardingGate initialAccount={{
        profile,
        settings: { "setup.onboarding_version": 0 },
      }}>
        <div>Private workspace</div>
      </OnboardingGate>,
    );

    fireEvent.change(screen.getByLabelText("Your name"), { target: { value: "Alex" } });
    await clickWhenReady("Continue");
    await clickWhenReady("Continue");
    expect(await screen.findByText("Choose your AI provider")).toBeTruthy();

    await clickWhenReady("OpenAI");
    for (const present of ["deepseek", "togetherai", "moonshotai"]) {
      fireEvent.change(screen.getByLabelText("Search providers"), { target: { value: present } });
      expect(screen.queryAllByRole("option").length).toBeGreaterThan(0);
      // The custom binding needs an address one way or the other: models.dev
      // publishes one (submitted silently - deepseek, moonshotai), or it does
      // not and the picker must ask (togetherai). Neither is optional.
      const published = providerApiBaseUrl(present);
      if (published) expect(published).toMatch(/^https:\/\//);
      else expect(providerNeedsBaseUrl(present)).toBe(true);
    }
  });

  it("offers self-hosted Ollama and Ollama Cloud as distinct options, without exposing localhost", async () => {
    render(
      <OnboardingGate initialAccount={{
        profile,
        settings: { "setup.onboarding_version": 0 },
      }}>
        <div>Private workspace</div>
      </OnboardingGate>,
    );

    fireEvent.change(screen.getByLabelText("Your name"), { target: { value: "Alex" } });
    await clickWhenReady("Continue");
    await clickWhenReady("Continue");
    expect(await screen.findByText("Choose your AI provider")).toBeTruthy();

    await clickWhenReady("OpenAI");
    fireEvent.change(screen.getByLabelText("Search providers"), { target: { value: "ollama" } });
    // Ollama Cloud stands as its own CUSTOM provider now - hosted API, its own
    // base URL, a real key - rather than being dropped or aliased onto the
    // self-hosted entry. What must never come back is the aliasing: the two
    // remain distinct options with distinct addresses.
    expect(screen.getByRole("option", { name: /Ollama Cloud/ })).toBeTruthy();
    const selfHosted = screen.getByRole("option", { name: /Ollama Self-hosted/ });
    const guidance = "Hosted Boltrig can use Ollama through a secured public HTTPS endpoint. Never expose an unauthenticated Ollama port. Use Boltrig Desktop to keep Ollama local to your computer.";
    expect(screen.getByTitle(guidance)).toBeTruthy();
    fireEvent.click(selfHosted);

    expect(screen.getByRole("button", { name: "Ollama" })).toBeTruthy();
    expect(screen.getByTitle(guidance)).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Provider API key"), { target: { value: "ollama-access-key" } });
    fireEvent.change(screen.getByLabelText("Ollama API address"), {
      target: { value: "https://models.example.com/v1" },
    });
    fireEvent.change(screen.getByLabelText("Exact model"), { target: { value: "qwen3:8b" } });
    await clickWhenReady("Continue");

    await waitFor(() => expect(api.setAiKey).toHaveBeenCalledWith(expect.objectContaining({
      provider: "ollama",
      model: "ollama/qwen3:8b",
      base_url: "https://models.example.com/v1",
      api_key: "ollama-access-key",
    })));
    expect(document.body.textContent).not.toContain("11434");
  });

  it("connects self-hosted Ollama without an API key", async () => {
    render(
      <OnboardingGate initialAccount={{
        profile,
        settings: { "setup.onboarding_version": 0 },
      }}>
        <div>Private workspace</div>
      </OnboardingGate>,
    );

    fireEvent.change(screen.getByLabelText("Your name"), { target: { value: "Alex" } });
    await clickWhenReady("Continue");
    await clickWhenReady("Continue");
    expect(await screen.findByText("Choose your AI provider")).toBeTruthy();
    expect(screen.queryByRole("note")).toBeNull();

    await clickWhenReady("OpenAI");
    fireEvent.change(screen.getByLabelText("Search providers"), { target: { value: "ollama" } });
    fireEvent.click(screen.getByRole("option", { name: /Ollama Self-hosted/ }));

    // Choosing self-hosted Ollama no longer nags about the desktop build. The
    // download lives on the Ready step and in device settings, where someone
    // looking for it will be, rather than attached to picking a local provider.
    expect(screen.queryByRole("note")).toBeNull();

    // The key field is optional for this provider and the model field is
    // usable without one.
    const keyInput = screen.getByLabelText("Provider API key") as HTMLInputElement;
    expect(keyInput.required).toBe(false);
    const modelInput = screen.getByLabelText("Exact model") as HTMLInputElement;
    expect(modelInput.disabled).toBe(false);

    fireEvent.change(screen.getByLabelText("Ollama API address"), {
      target: { value: "http://mac-mini-m1:11434/v1" },
    });
    fireEvent.change(modelInput, { target: { value: "qwen3vl-abliterated" } });
    await clickWhenReady("Continue");

    await waitFor(() => expect(api.setAiKey).toHaveBeenCalledWith(expect.objectContaining({
      provider: "ollama",
      model: "ollama/qwen3vl-abliterated",
      base_url: "http://mac-mini-m1:11434/v1",
      api_key: "",
    })));
  });

  it("keeps the AI step open when a started provider setup is incomplete", async () => {
    render(
      <OnboardingGate initialAccount={{
        profile,
        settings: { "setup.onboarding_version": 0 },
      }}>
        <div>Private workspace</div>
      </OnboardingGate>,
    );

    fireEvent.change(screen.getByLabelText("Your name"), { target: { value: "Alex" } });
    await clickWhenReady("Continue");
    await clickWhenReady("Continue");
    expect(await screen.findByText("Choose your AI provider")).toBeTruthy();
    fireEvent.change(await screen.findByLabelText("Provider API key"), { target: { value: "partial-key" } });
    await clickWhenReady("Continue");

    expect(await screen.findByText("Choose a provider, add its key and pick a model to continue."))
      .toBeTruthy();
    expect(screen.getByText("Choose your AI provider")).toBeTruthy();
    expect(api.setAiKey).not.toHaveBeenCalled();
  });

  it("answers a parked provider approval inside the same Continue press", async () => {
    api.setAiKey.mockResolvedValueOnce({
      status: "pending_human",
      proposal: {
        id: "proposal-1",
        level: "user",
        scope_id: "owner",
        provider: "openai",
        model: "openai/gpt-5.4",
        modality: "text",
        status: "pending",
        created_at: "2026-08-15T09:00:00Z",
        expires_at: "2026-08-15T09:15:00Z",
      },
    });
    render(
      <OnboardingGate initialAccount={{
        profile,
        settings: { "setup.onboarding_version": 0 },
      }}>
        <div>Private workspace</div>
      </OnboardingGate>,
    );

    fireEvent.change(screen.getByLabelText("Your name"), { target: { value: "Alex" } });
    await clickWhenReady("Continue");
    await clickWhenReady("Continue");
    fireEvent.change(await screen.findByLabelText("Provider API key"), {
      target: { value: "provider-secret" },
    });
    await clickWhenReady("Choose a model");
    fireEvent.change(screen.getByLabelText("Search models"), { target: { value: "GPT-5.4" } });
    fireEvent.click(screen.getByRole("option", { name: /GPT-5\.4 Text \+ vision$/ }));
    await clickWhenReady("Continue");

    // One press covers the whole journey: a parked approval is answered inside
    // the same Continue, never by asking the person to press it twice.
    await waitFor(() => expect(api.approveAiKeyProposal).toHaveBeenCalledWith("proposal-1"));
    expect(await screen.findByText("Add vision")).toBeTruthy();
    await clickWhenReady("Skip for now");
    expect(await screen.findByText("Add voice")).toBeTruthy();
    await clickWhenReady("Skip for now");
    expect(await screen.findByText("You’re ready, Alex. Meet Familiar.")).toBeTruthy();
  });

  it("waits with a plain sentence when the approval belongs to an administrator", async () => {
    api.setAiKey.mockResolvedValueOnce({
      status: "pending_human",
      proposal: {
        id: "proposal-2",
        level: "org",
        scope_id: "acme",
        provider: "openai",
        model: "openai/gpt-5.4",
        modality: "text",
        status: "pending",
        created_at: "2026-08-15T09:00:00Z",
        expires_at: "2026-08-15T09:15:00Z",
      },
    });
    api.approveAiKeyProposal.mockResolvedValue({
      status: "pending",
      reason: "This connection is waiting for an administrator's approval.",
    });
    render(
      <OnboardingGate initialAccount={{
        profile,
        settings: { "setup.onboarding_version": 0 },
      }}>
        <div>Private workspace</div>
      </OnboardingGate>,
    );

    fireEvent.change(screen.getByLabelText("Your name"), { target: { value: "Alex" } });
    await clickWhenReady("Continue");
    await clickWhenReady("Continue");
    fireEvent.change(await screen.findByLabelText("Provider API key"), {
      target: { value: "provider-secret" },
    });
    await clickWhenReady("Choose a model");
    fireEvent.change(screen.getByLabelText("Search models"), { target: { value: "GPT-5.4" } });
    fireEvent.click(screen.getByRole("option", { name: /GPT-5\.4 Text \+ vision$/ }));
    await clickWhenReady("Continue");

    await waitFor(() => expect(api.approveAiKeyProposal).toHaveBeenCalledWith("proposal-2"));
    expect(await screen.findByText(
      "This connection is waiting for an administrator's approval.",
    )).toBeTruthy();
    expect(screen.getByText("Choose your AI provider")).toBeTruthy();

    // The next press re-checks the SAME request rather than resubmitting.
    await clickWhenReady("Continue");
    await waitFor(() => expect(api.approveAiKeyProposal).toHaveBeenCalledTimes(2));
    expect(api.setAiKey).toHaveBeenCalledTimes(1);
  });

  it("holds the provider step when the saved key does not reach its provider", async () => {
    // THE DEFECT THIS PINS. A key saved with base_url https://<host>:11434 was
    // accepted, sealed and stored, so intake answered `ok` and onboarding said
    // "Provider connected." and moved on. Ollama serves plain HTTP on that
    // port, so nothing ever reached it. `ok` is a fact about the write; only
    // gateway_ready is a fact about the provider, and the step now reads it.
    api.setAiKey.mockResolvedValueOnce({ status: "ok" });
    api.aiKeys
      .mockResolvedValueOnce({ allow_own_ai_keys: true, ai_keys: [] })
      .mockResolvedValue({
        allow_own_ai_keys: true,
        ai_keys: [{
          level: "user",
          scope_id: "owner",
          provider: "openai",
          model: "openai/gpt-5.4",
          modality: "text",
          has_key: true,
          gateway_ready: false,
        }],
      });
    render(
      <OnboardingGate initialAccount={{
        profile,
        settings: { "setup.onboarding_version": 0 },
      }}>
        <div>Private workspace</div>
      </OnboardingGate>,
    );

    fireEvent.change(screen.getByLabelText("Your name"), { target: { value: "Alex" } });
    await clickWhenReady("Continue");
    await clickWhenReady("Continue");
    fireEvent.change(await screen.findByLabelText("Provider API key"), {
      target: { value: "provider-secret" },
    });
    await clickWhenReady("Choose a model");
    fireEvent.change(screen.getByLabelText("Search models"), { target: { value: "GPT-5.4" } });
    fireEvent.click(screen.getByRole("option", { name: /GPT-5\.4 Text \+ vision$/ }));
    await clickWhenReady("Continue");

    await waitFor(() => expect(api.setAiKey).toHaveBeenCalled());
    expect(await screen.findByText(/did not answer/)).toBeTruthy();
    expect(screen.getByText(/usually http, not https/)).toBeTruthy();
    // Still on the provider step, and never claimed success.
    expect(screen.getByText("Choose your AI provider")).toBeTruthy();
    expect(screen.queryByText("Provider connected.")).toBeNull();
    expect(screen.queryByText("Add vision")).toBeNull();
  });

  it("reconciles an approved saved model before allowing onboarding to finish", async () => {
    api.aiKeys.mockResolvedValueOnce({
      allow_own_ai_keys: true,
      ai_keys: [{
        level: "user",
        scope_id: "owner",
        provider: "openai",
        model: "openai/gpt-5.4",
        modality: "text",
        has_key: true,
        gateway_ready: false,
      }],
    });
    render(
      <OnboardingGate initialAccount={{
        profile,
        settings: { "setup.onboarding_version": 0 },
      }}>
        <div>Private workspace</div>
      </OnboardingGate>,
    );

    fireEvent.change(screen.getByLabelText("Your name"), { target: { value: "Alex" } });
    await clickWhenReady("Continue");
    await clickWhenReady("Continue");
    expect(await screen.findByText("Choose your AI provider")).toBeTruthy();
    await clickWhenReady("Continue");

    await waitFor(() => expect(api.activateAiKey).toHaveBeenCalledWith({
      level: "user",
      scope_id: "owner",
      modality: "text",
    }));
    expect(await screen.findByText("Add vision")).toBeTruthy();
    await clickWhenReady("Skip for now");
    expect(await screen.findByText("Add voice")).toBeTruthy();
    await clickWhenReady("Skip for now");
    expect(await screen.findByText("You’re ready, Alex. Meet Familiar.")).toBeTruthy();
  });

  it("keeps onboarding copy focused on the user's choices", async () => {
    render(
      <OnboardingGate initialAccount={{
        profile,
        settings: { "setup.onboarding_version": 0 },
      }}>
        <div>Private workspace</div>
      </OnboardingGate>,
    );

    fireEvent.change(screen.getByLabelText("Your name"), { target: { value: "Alex" } });
    await clickWhenReady("Continue");
    await clickWhenReady("Continue");
    expect(await screen.findByText("Choose your AI provider")).toBeTruthy();
    await screen.findByLabelText("Provider API key");
    expect(screen.queryByText("Connect a provider")).toBeNull();
    expect(screen.queryByText("Add an AI provider")).toBeNull();
    expect(screen.queryByText("Model not listed?")).toBeNull();
    expect(document.body.textContent).not.toMatch(
      /Bifrost|models\.dev|sealed|write-only|model route|key policy|safe configuration/i,
    );

    await clickWhenReady("Continue");
    expect(await screen.findByText("Add vision")).toBeTruthy();
    await clickWhenReady("Skip for now");
    expect(await screen.findByText("Add voice")).toBeTruthy();
    await clickWhenReady("Skip for now");
    expect(await screen.findByText("You’re ready, Alex. Meet Familiar.")).toBeTruthy();
    expect(document.body.textContent).not.toMatch(
      /Bifrost|models\.dev|sealed|write-only|model route|key policy|safe configuration/i,
    );
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

    fireEvent.change(screen.getByLabelText("Your name"), {
      target: { value: "Alex" },
    });
    await clickWhenReady("Continue");
    expect(screen.getByText("Choose your companion")).toBeTruthy();
    await clickWhenReady("Continue");
    expect(await screen.findByText("Your organisation manages your AI.")).toBeTruthy();
    expect(screen.queryByLabelText("Provider API key")).toBeNull();
    await clickWhenReady("Continue");
    expect(await screen.findByText("Add vision")).toBeTruthy();
    await clickWhenReady("Continue");
    expect(await screen.findByText("Your organisation manages voice services.")).toBeTruthy();
    await clickWhenReady("Continue");
    await clickWhenReady("Continue in browser");
    expect(await screen.findByText("Member workspace")).toBeTruthy();
  });

  it("offers optional voice setup and clears the write-only key before awaiting", async () => {
    api.integrationCatalogue.mockResolvedValueOnce({
      integrations: [{
        id: "deepgram-audio",
        label: "Deepgram",
        category: "communications",
        transport: "rest",
        auth: ["manual_secret"],
        description: "Speech and transcription",
        certification: "certified",
        available: true,
        setup_supported: true,
        setup_contract: {
          kind: "manual_secret",
          version: "deepgram_audio_v1",
          fields: [{
            name: "api_key",
            label: "Deepgram API key",
            input_kind: "api_key",
            secret: true,
            required: true,
            min_length: 8,
            max_length: 4096,
          }],
        },
        enabled_tools: [],
      }],
    });
    render(
      <OnboardingGate initialAccount={{ profile, settings: { "setup.onboarding_version": 0 } }}>
        <div>Private workspace</div>
      </OnboardingGate>,
    );

    fireEvent.change(screen.getByLabelText("Your name"), { target: { value: "Alex" } });
    await clickWhenReady("Continue");
    await clickWhenReady("Continue");
    await screen.findByText("Choose your AI provider");
    await clickWhenReady("Continue");

    expect(await screen.findByText("Add vision")).toBeTruthy();
    await clickWhenReady("Continue");
    expect(await screen.findByText("Add voice")).toBeTruthy();
    expect(await screen.findByText("Spoken replies")).toBeTruthy();
    expect(screen.getByText("Transcription")).toBeTruthy();
    const voiceKey = screen.getByLabelText("Deepgram API key") as HTMLInputElement;
    fireEvent.change(voiceKey, { target: { value: "deepgram-secret-value" } });
    await clickWhenReady("Continue");

    await waitFor(() => expect(api.submitIntegrationSecret).toHaveBeenCalledWith(
      "deepgram-audio",
      { fields: { api_key: "deepgram-secret-value" }, label: "Deepgram" },
    ));
    expect(voiceKey.value).toBe("");
    expect(await screen.findByText("You’re ready, Alex. Meet Familiar.")).toBeTruthy();
  });

  it("skips voice without submitting any credential", async () => {
    render(
      <OnboardingGate initialAccount={{ profile, settings: { "setup.onboarding_version": 0 } }}>
        <div>Private workspace</div>
      </OnboardingGate>,
    );
    fireEvent.change(screen.getByLabelText("Your name"), { target: { value: "Alex" } });
    await clickWhenReady("Continue");
    await clickWhenReady("Continue");
    await screen.findByText("Choose your AI provider");
    await clickWhenReady("Continue");
    await clickWhenReady("Skip for now");
    await clickWhenReady("Skip for now");
    expect(await screen.findByText("You’re ready, Alex. Meet Familiar.")).toBeTruthy();
    expect(api.submitIntegrationSecret).not.toHaveBeenCalled();
  });
});
