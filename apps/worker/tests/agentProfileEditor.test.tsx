// @vitest-environment happy-dom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  agentCapabilities: vi.fn(),
  invoke: vi.fn(),
  invokeApprovalState: vi.fn(),
  modelEndpoints: vi.fn(),
}));

vi.mock("../src/client", () => ({ client: api }));

import { AgentProfileEditor } from "../src/components/AgentProfileEditor";

beforeEach(() => {
  api.agentCapabilities.mockResolvedValue({ agent_capabilities: [] });
  api.modelEndpoints.mockResolvedValue({ endpoints: [] });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

it("authors only the runtime's canonical expensive cost tier", async () => {
  api.invoke.mockResolvedValue({ status: "ok", result: {} });

  render(
    <AgentProfileEditor
      onSaved={vi.fn()}
      onCancel={vi.fn()}
    />,
  );

  expect(screen.queryByRole("option", { name: "Premium" })).toBeNull();
  expect(screen.getByRole("option", { name: "Expensive" })).toBeTruthy();
  fireEvent.change(screen.getByLabelText("Name"), {
    target: { value: "researcher" },
  });
  fireEvent.change(screen.getByLabelText("Cost tier"), {
    target: { value: "expensive" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Request profile change" }));

  await waitFor(() => expect(api.invoke).toHaveBeenCalledWith(
    expect.objectContaining({
      params: expect.objectContaining({ cost_tier: "expensive" }),
    }),
  ));
});

it("does not report a save when the kernel was unreachable", async () => {
  api.invoke.mockResolvedValue({
    status: "unavailable",
    reason: "the kernel was unreachable",
  });
  const onSaved = vi.fn();

  render(
    <AgentProfileEditor
      onSaved={onSaved}
      onCancel={vi.fn()}
    />,
  );
  fireEvent.change(screen.getByLabelText("Name"), {
    target: { value: "researcher" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Request profile change" }));

  expect(await screen.findByText("Not changed: the kernel was unreachable.")).toBeTruthy();
  expect(screen.queryByText("Agent profile saved.")).toBeNull();
  expect(onSaved).not.toHaveBeenCalled();
});

it("continues only the exact cloned profile request after approval", async () => {
  const onSaved = vi.fn();
  api.invoke
    .mockResolvedValueOnce({
      status: "pending_human",
      hitl_request_id: "approval-profile",
    })
    .mockResolvedValueOnce({ status: "ok", output: {} });
  api.invokeApprovalState.mockResolvedValue({ status: "approved" });

  render(
    <AgentProfileEditor
      onSaved={onSaved}
      onCancel={vi.fn()}
    />,
  );

  fireEvent.change(screen.getByLabelText("Name"), {
    target: { value: "researcher" },
  });
  fireEvent.change(screen.getByLabelText("Maximum delegation depth"), {
    target: { value: "4" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Request profile change" }));

  await screen.findByText("Agent profile change is waiting for approval");
  const firstRequest = api.invoke.mock.calls[0][0];
  fireEvent.click(screen.getByRole("button", {
    name: "Check approval and apply exact change",
  }));

  await waitFor(() => expect(api.invokeApprovalState).toHaveBeenCalledWith(
    "approval-profile",
  ));
  await waitFor(() => expect(api.invoke).toHaveBeenNthCalledWith(2, {
    ...firstRequest,
    approval_id: "approval-profile",
  }));
  expect(onSaved).toHaveBeenCalledTimes(1);
});

it("invalidates a held profile request on edit", async () => {
  api.invoke.mockResolvedValue({
    status: "pending_human",
    hitl_request_id: "approval-stale-profile",
  });

  render(
    <AgentProfileEditor
      onSaved={vi.fn()}
      onCancel={vi.fn()}
    />,
  );
  fireEvent.change(screen.getByLabelText("Name"), {
    target: { value: "researcher" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Request profile change" }));
  await screen.findByText("Agent profile change is waiting for approval");

  fireEvent.change(screen.getByLabelText("Cost tier"), {
    target: { value: "expensive" },
  });

  expect(await screen.findByText("Agent profile change changed")).toBeTruthy();
  expect(screen.queryByRole("button", {
    name: "Check approval and apply exact change",
  })).toBeNull();
  expect(api.invoke).toHaveBeenCalledTimes(1);
});

it("refreshes canonical profiles without inferring success for consumed approval", async () => {
  const onSaved = vi.fn();
  api.agentCapabilities.mockResolvedValueOnce({
    agent_capabilities: [{
      name: "researcher",
      runtime: "codex",
      supported_skills: ["canonical"],
      max_depth: 5,
      is_ephemeral: false,
      cost_tier: "cheap",
      model_endpoint: null,
    }],
  });
  api.invoke.mockResolvedValue({
    status: "pending_human",
    hitl_request_id: "approval-consumed-profile",
  });
  api.invokeApprovalState.mockResolvedValue({ status: "consumed" });

  render(
    <AgentProfileEditor
      onSaved={onSaved}
      onCancel={vi.fn()}
    />,
  );
  fireEvent.change(screen.getByLabelText("Name"), {
    target: { value: "researcher" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Request profile change" }));
  await screen.findByText("Agent profile change is waiting for approval");
  fireEvent.click(screen.getByRole("button", {
    name: "Check approval and apply exact change",
  }));

  expect(await screen.findByText(
    "Agent profile change approval was already consumed",
  )).toBeTruthy();
  expect(api.agentCapabilities).toHaveBeenCalledTimes(1);
  expect(
    (screen.getByLabelText("Maximum delegation depth") as HTMLInputElement).value,
  ).toBe("5");
  expect(
    (screen.getByLabelText("Supported skill patterns") as HTMLTextAreaElement).value,
  ).toBe("canonical");
  expect(onSaved).not.toHaveBeenCalled();
  expect(api.invoke).toHaveBeenCalledTimes(1);
});

it("authors separate text and vision model bindings through the governed profile", async () => {
  api.modelEndpoints.mockResolvedValue({
    endpoints: [
      {
        id: "bifrost-text",
        kind: "bifrost",
        model: "text-model",
        data_class: "standard",
        modalities: ["text"],
        is_active: true,
        status: "active",
      },
      {
        id: "bifrost-vision",
        kind: "bifrost",
        model: "vision-model",
        data_class: "standard",
        modalities: ["vision"],
        is_active: true,
        status: "active",
      },
    ],
  });
  api.invoke.mockResolvedValue({ status: "ok", result: {} });

  render(
    <AgentProfileEditor
      onSaved={vi.fn()}
      onCancel={vi.fn()}
    />,
  );
  fireEvent.change(screen.getByLabelText("Name"), {
    target: { value: "vision-worker" },
  });
  fireEvent.change(screen.getByLabelText("Model arrangement"), {
    target: { value: "separate" },
  });
  await screen.findByRole("option", { name: /bifrost-text/ });
  fireEvent.change(screen.getByLabelText("Text model"), {
    target: { value: "bifrost-text" },
  });
  fireEvent.change(screen.getByLabelText("Vision model"), {
    target: { value: "bifrost-vision" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Request profile change" }));

  await waitFor(() => expect(api.invoke).toHaveBeenCalledWith(
    expect.objectContaining({
      verb: "control.capability.upsert",
      params: expect.objectContaining({
        model_endpoint: "bifrost-text",
        vision_model_endpoint: "bifrost-vision",
      }),
    }),
  ));
});

it("preserves normalized text, vision, and directional voice routes when editing", async () => {
  api.modelEndpoints.mockResolvedValue({
    endpoints: [
      ["text-route", ["text"]],
      ["vision-route", ["vision"]],
      ["speech-route", ["stt"]],
      ["voice-route", ["tts"]],
      ["realtime-route", ["realtime"]],
    ].map(([id, modalities]) => ({
      id,
      kind: "bifrost",
      model: `${id}-model`,
      data_class: "standard",
      modalities,
      is_active: true,
      status: "active",
    })),
  });
  api.invoke.mockResolvedValue({ status: "ok", result: {} });

  render(
    <AgentProfileEditor
      initial={{
        name: "routed-worker",
        runtime: "codex",
        supported_skills: ["*"],
        max_depth: 2,
        is_ephemeral: true,
        cost_tier: "standard",
        model_endpoint: null,
        vision_model_endpoint: null,
        model_routes: {
          text: "text-route",
          vision: "vision-route",
          stt: "speech-route",
          tts: "voice-route",
          realtime: "realtime-route",
        },
        familiar_genotype: {},
      }}
      onSaved={vi.fn()}
      onCancel={vi.fn()}
    />,
  );

  await screen.findByRole("option", { name: /text-route/ });
  expect((screen.getByLabelText("Text model") as HTMLSelectElement).value).toBe("text-route");
  expect((screen.getByLabelText("Vision model") as HTMLSelectElement).value).toBe("vision-route");
  expect((screen.getByLabelText("Speech to text") as HTMLSelectElement).value).toBe("speech-route");
  expect((screen.getByLabelText("Text to speech") as HTMLSelectElement).value).toBe("voice-route");
  expect((screen.getByLabelText("Realtime voice") as HTMLSelectElement).value).toBe("realtime-route");

  fireEvent.click(screen.getByRole("button", { name: "Request profile change" }));
  await waitFor(() => expect(api.invoke).toHaveBeenCalledWith(
    expect.objectContaining({
      params: expect.objectContaining({
        model_routes: {
          text: "text-route",
          vision: "vision-route",
          stt: "speech-route",
          tts: "voice-route",
          realtime: "realtime-route",
        },
      }),
    }),
  ));
});
