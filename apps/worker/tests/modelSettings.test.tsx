// @vitest-environment happy-dom

import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  bifrostModels: vi.fn(),
  chatModelChoices: vi.fn(),
  invoke: vi.fn(),
  invokeApprovalState: vi.fn(),
  modelEndpoint: vi.fn(),
  modelEndpoints: vi.fn(),
  restoreModelEndpoint: vi.fn(),
  retireModelEndpoint: vi.fn(),
}));

vi.mock("../src/client", () => ({ client: api }));

import { ModelSettingsSection } from "../src/components/settings/ModelSettingsSection";

const active = {
  id: "reasoning-route",
  kind: "bifrost",
  model: "anthropic/claude-sonnet-4-5",
  data_class: "standard",
  modalities: ["text", "vision"],
  revision: 1,
  is_active: true,
  status: "active" as const,
};
const absent = {
  ...active,
  id: "unprojected-route",
  model: "openai/gpt-5.4-mini",
  modalities: ["text"],
};
const retired = {
  ...active,
  id: "retired-route",
  model: "google/gemini-3-pro",
  modalities: ["text"],
  is_active: false,
  status: "retired" as const,
};
const legacy = {
  ...active,
  id: "legacy-openai-route",
  kind: "openai",
  model: "openai/gpt-4.1",
  modalities: ["text"],
};
const nonChat = {
  ...active,
  id: "sensitive-route",
  data_class: "sensitive",
  model: "sensitive-model",
};
const voice = {
  ...active,
  id: "voice-route",
  kind: "xai",
  model: "grok-voice-model",
  modalities: ["realtime"],
};
const visionOnlyModel = "google/gemini-vision-only";

beforeEach(() => {
  api.bifrostModels.mockResolvedValue({
    status: "ok",
    models: [
      active.model,
      absent.model,
      retired.model,
      "anthropic/claude-opus-4-1",
      "openai/gpt-5.4",
      legacy.model,
      visionOnlyModel,
    ].map((id) => ({
      id,
      name: id,
      input_modalities: id === active.model || id === "anthropic/claude-opus-4-1"
        ? ["text", "vision"]
        : id === visionOnlyModel
          ? ["vision"]
          : ["text"],
    })),
    reason: null,
  });
  api.modelEndpoints.mockResolvedValue({
    endpoints: [active, absent, retired, legacy, nonChat, voice],
  });
  api.chatModelChoices.mockResolvedValue({
    status: "ok",
    reason: null,
    choices: [{
      id: active.id,
      model_name: active.model,
      available: true,
      is_default: true,
      modalities: active.modalities,
    }],
    default_choice_id: active.id,
    default_model_name: active.model,
  });
  api.modelEndpoint.mockImplementation(async (id: string) => {
    const endpoint = [active, absent, retired, legacy, voice].find((item) => item.id === id)!;
    return {
      endpoint: {
        ...endpoint,
        base_url: "https://gateway.internal.test/v1",
        fallback: "fallback-route",
        references: { capabilities: [], fallbacks: [] },
      },
    };
  });
  api.invoke.mockResolvedValue({ status: "ok", output: {} });
  api.invokeApprovalState.mockResolvedValue({ status: "approved" });
  api.retireModelEndpoint.mockResolvedValue({
    status: "pending_human",
    hitl_request_id: "approval-retire",
  });
  api.restoreModelEndpoint.mockResolvedValue({
    status: "ok",
    id: retired.id,
    model_endpoint_status: "active",
  });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("Models settings", () => {
  it("shows every standard text-chat route and reports projection truthfully", async () => {
    render(<ModelSettingsSection />);

    expect(await screen.findByText(active.model)).toBeTruthy();
    expect(screen.getByText(retired.model)).toBeTruthy();
    expect(screen.queryByText(nonChat.model)).toBeNull();
    expect(screen.getByText("In switcher")).toBeTruthy();
    expect(screen.getAllByText("Not in switcher")).toHaveLength(2);
    expect(screen.getByText("Removed")).toBeTruthy();
    expect(screen.getByLabelText("Exact Bifrost model name")).toBeTruthy();
    expect(screen.getByText("6 text models")).toBeTruthy();
    expect(screen.getByLabelText("Exact Bifrost model name").getAttribute("list"))
      .toBe("bifrost-chat-models");
    const legacyRow = screen.getByText(legacy.model).closest<HTMLElement>(".settings-row")!;
    const legacyChange = within(legacyRow).getByRole("button", { name: "Change" });
    expect(legacyChange).toHaveProperty("disabled", true);
    expect(legacyChange.getAttribute("title")).toContain("cannot be rewritten");
  });

  it("keeps vision and voice as working modality views without exposing credentials", async () => {
    render(<ModelSettingsSection />);
    await screen.findByText(active.model);

    fireEvent.click(screen.getByRole("tab", { name: "Vision" }));
    expect(await screen.findByText(active.model)).toBeTruthy();
    expect(screen.getByRole("tab", { name: "Vision" }).getAttribute("aria-selected")).toBe("true");

    fireEvent.click(screen.getByRole("tab", { name: "Voice" }));
    expect(await screen.findByText(voice.model)).toBeTruthy();
    expect(screen.getByText("XAI realtime")).toBeTruthy();
    expect(screen.getByLabelText("Exact realtime voice model name")).toBeTruthy();
    expect(screen.queryByText("Omnivoice / local")).toBeNull();
    expect(screen.queryByText("ElevenLabs")).toBeNull();
    expect(screen.queryByLabelText("Exact Bifrost model name")).toBeNull();
    expect(screen.queryByLabelText(/API key/i)).toBeNull();
  });

  it("authors an XAI realtime route even when the Bifrost catalogue is unavailable", async () => {
    api.bifrostModels.mockResolvedValue({
      status: "unavailable",
      models: [],
      reason: "gateway_unavailable",
    });
    render(<ModelSettingsSection />);
    await screen.findByText(active.model);
    fireEvent.click(screen.getByRole("tab", { name: "Voice" }));

    fireEvent.change(await screen.findByLabelText("Internal choice ID"), {
      target: { value: "primary-voice" },
    });
    fireEvent.change(screen.getByLabelText("Exact realtime voice model name"), {
      target: { value: "grok-voice-v1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Request model addition" }));

    await waitFor(() => expect(api.invoke).toHaveBeenCalledWith(expect.objectContaining({
      noun: "control",
      verb: "control.model_endpoint.upsert",
      params: expect.objectContaining({
        id: "primary-voice",
        kind: "xai",
        model: "grok-voice-v1",
        modalities: ["realtime"],
      }),
    })));
  });

  it("changes through the governed Bifrost upsert and preserves topology", async () => {
    api.invoke
      .mockResolvedValueOnce({
        status: "pending_human",
        hitl_request_id: "approval-upsert",
      })
      .mockResolvedValueOnce({ status: "ok", output: {} });

    render(<ModelSettingsSection />);
    const row = (await screen.findByText(active.model)).closest<HTMLElement>(".settings-row")!;
    fireEvent.click(within(row).getByRole("button", { name: "Change" }));

    const exactName = await screen.findByLabelText("Exact Bifrost model name");
    fireEvent.change(exactName, { target: { value: "anthropic/claude-opus-4-1" } });
    fireEvent.click(screen.getByRole("button", { name: "Request model change" }));

    expect(await screen.findByText(
      "This model change is waiting for approval in the originating chat.",
    )).toBeTruthy();
    const firstRequest = api.invoke.mock.calls[0]![0];
    expect(firstRequest).toMatchObject({
      noun: "control",
      verb: "control.model_endpoint.upsert",
      params: {
        id: active.id,
        kind: "bifrost",
        model: "anthropic/claude-opus-4-1",
        base_url: "https://gateway.internal.test/v1",
        fallback: "fallback-route",
        data_class: "standard",
        modalities: ["text", "vision"],
      },
    });

    fireEvent.click(screen.getByRole("button", {
      name: "Check approval and apply exact change",
    }));
    await waitFor(() => expect(api.invoke).toHaveBeenNthCalledWith(2, {
      ...firstRequest,
      approval_id: "approval-upsert",
    }));
  });

  it("will not replace a multimodal route with a model missing one selected modality", async () => {
    render(<ModelSettingsSection />);
    await screen.findByText(active.model);
    fireEvent.click(screen.getByRole("tab", { name: "Vision" }));
    const row = (await screen.findByText(active.model)).closest<HTMLElement>(".settings-row")!;
    fireEvent.click(within(row).getByRole("button", { name: "Change" }));

    const exactName = await screen.findByLabelText("Exact Bifrost model name");
    const options = [...document.querySelectorAll<HTMLOptionElement>(
      "#bifrost-chat-models option",
    )].map((option) => option.getAttribute("value"));
    expect(options).not.toContain(visionOnlyModel);
    fireEvent.change(exactName, { target: { value: visionOnlyModel } });
    fireEvent.click(screen.getByRole("button", { name: "Request model change" }));

    expect(await screen.findByText(
      "Choose an exact Bifrost model that advertises every selected modality (text + vision).",
    )).toBeTruthy();
    expect(api.invoke).not.toHaveBeenCalled();
  });

  it("refuses exact replay when the hydrated endpoint reference snapshot changes", async () => {
    api.invoke.mockResolvedValueOnce({
      status: "pending_human",
      hitl_request_id: "approval-reference-drift",
    });

    render(<ModelSettingsSection />);
    const row = (await screen.findByText(active.model)).closest<HTMLElement>(".settings-row")!;
    fireEvent.click(within(row).getByRole("button", { name: "Change" }));
    fireEvent.change(await screen.findByLabelText("Exact Bifrost model name"), {
      target: { value: "anthropic/claude-opus-4-1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Request model change" }));
    expect(await screen.findByText(
      "This model change is waiting for approval in the originating chat.",
    )).toBeTruthy();

    api.modelEndpoint.mockResolvedValue({
      endpoint: {
        ...active,
        revision: 2,
        base_url: "https://gateway.internal.test/v1",
        fallback: "fallback-route",
        references: { capabilities: ["new-agent-reference"], fallbacks: [] },
      },
    });
    fireEvent.click(screen.getByRole("button", {
      name: "Check approval and apply exact change",
    }));

    expect(await screen.findByText("model_endpoint_snapshot_changed")).toBeTruthy();
    expect(api.invoke).toHaveBeenCalledTimes(1);
  });

  it("adds a new exact model through the same governed route", async () => {
    render(<ModelSettingsSection />);
    await screen.findByText(active.model);

    fireEvent.change(screen.getByLabelText("Internal choice ID"), {
      target: { value: "new-chat-route" },
    });
    fireEvent.change(screen.getByLabelText("Exact Bifrost model name"), {
      target: { value: "openai/gpt-5.4" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Request model addition" }));

    await waitFor(() => expect(api.invoke).toHaveBeenCalledOnce());
    expect(api.invoke.mock.calls[0]![0]).toMatchObject({
      verb: "control.model_endpoint.upsert",
      params: {
        id: "new-chat-route",
        kind: "bifrost",
        model: "openai/gpt-5.4",
        data_class: "standard",
        modalities: ["text"],
      },
    });
  });

  it("will not replace an endpoint hidden from the chat-model list", async () => {
    render(<ModelSettingsSection />);
    await screen.findByText(active.model);

    fireEvent.change(screen.getByLabelText("Internal choice ID"), {
      target: { value: nonChat.id },
    });
    fireEvent.change(screen.getByLabelText("Exact Bifrost model name"), {
      target: { value: "openai/gpt-5.4" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Request model addition" }));

    expect(await screen.findByText(
      "That ID already belongs to another model endpoint and cannot be replaced here.",
    )).toBeTruthy();
    expect(api.invoke).not.toHaveBeenCalled();
  });

  it("fails closed when Bifrost cannot verify a proposed model", async () => {
    api.bifrostModels.mockResolvedValue({
      status: "unavailable",
      models: [],
      reason: "gateway_timeout",
    });
    render(<ModelSettingsSection />);

    expect(await screen.findByText("Unavailable")).toBeTruthy();
    expect(screen.getByText(/gateway_timeout/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Request model addition" }))
      .toHaveProperty("disabled", true);
    expect(api.invoke).not.toHaveBeenCalled();
  });

  it("does not infer text support when Bifrost omits architecture metadata", async () => {
    api.bifrostModels.mockResolvedValue({
      status: "ok",
      models: [{ id: "custom/model-without-architecture", name: "Custom model" }],
      reason: null,
    });
    render(<ModelSettingsSection />);

    expect(await screen.findByText("0 text models")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Internal choice ID"), {
      target: { value: "custom-route" },
    });
    fireEvent.change(screen.getByLabelText("Exact Bifrost model name"), {
      target: { value: "custom/model-without-architecture" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Request model addition" }));

    expect(await screen.findByText(
      "Choose an exact Bifrost model that advertises every selected modality (text).",
    )).toBeTruthy();
    expect(api.invoke).not.toHaveBeenCalled();
  });

  it("shows global reference impact before recoverable removal and offers Restore", async () => {
    api.retireModelEndpoint
      .mockResolvedValueOnce({
        status: "pending_human",
        hitl_request_id: "approval-retire",
      })
      .mockResolvedValueOnce({
        status: "ok",
        id: active.id,
        model_endpoint_status: "retired",
      });

    render(<ModelSettingsSection />);
    const activeRow = (await screen.findByText(active.model)).closest<HTMLElement>(".settings-row")!;
    fireEvent.click(within(activeRow).getByRole("button", { name: "Remove model" }));
    const confirmation = await screen.findByRole("alertdialog", {
      name: "Confirm model removal",
    });
    expect(confirmation.textContent).toContain("everywhere, not only in");
    expect(confirmation.textContent).toContain("Agent references: none");
    expect(api.retireModelEndpoint).not.toHaveBeenCalled();
    fireEvent.click(within(confirmation).getByRole("button", {
      name: "Confirm removal",
    }));
    expect(await screen.findByText(/Removal is waiting for approval/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", {
      name: "Check approval and apply exact change",
    }));

    await waitFor(() => expect(api.retireModelEndpoint).toHaveBeenNthCalledWith(
      2,
      active.id,
      "approval-retire",
    ));

    const retiredRow = screen.getByText(retired.model).closest<HTMLElement>(".settings-row")!;
    fireEvent.click(within(retiredRow).getByRole("button", { name: "Restore" }));
    await waitFor(() => expect(api.restoreModelEndpoint).toHaveBeenCalledWith(retired.id));
    expect(screen.getByText(`${retired.model} was restored to model routing.`)).toBeTruthy();
  });

  it("does not call a degraded response saved before canonical refresh", async () => {
    api.invoke.mockResolvedValueOnce({
      status: "degraded",
      reason: "control_plane_uncertain",
      output: {},
    });
    render(<ModelSettingsSection />);
    await screen.findByText(active.model);

    fireEvent.change(screen.getByLabelText("Internal choice ID"), {
      target: { value: "degraded-route" },
    });
    fireEvent.change(screen.getByLabelText("Exact Bifrost model name"), {
      target: { value: "openai/gpt-5.4" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Request model addition" }));

    expect(await screen.findByText(
      "Canonical model state was refreshed after a degraded response; no save is inferred.",
    )).toBeTruthy();
    expect(screen.queryByText("Model saved.")).toBeNull();
  });
});
