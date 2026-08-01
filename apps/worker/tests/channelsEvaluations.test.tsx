// @vitest-environment happy-dom

import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { BoltrigApiError } from "@wlilley93/boltrig-web-sdk";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  archiveEvalCase: vi.fn(),
  bindChannel: vi.fn(),
  channelBindings: vi.fn(),
  channelDeliveries: vi.fn(),
  channelGatewaySession: vi.fn(),
  channelPairFinalizations: vi.fn(),
  channels: vi.fn(),
  configureChannel: vi.fn(),
  connectChannel: vi.fn(),
  createEvalCase: vi.fn(),
  deleteChannelBinding: vi.fn(),
  disconnectChannel: vi.fn(),
  evalCases: vi.fn(),
  evalRuns: vi.fn(),
  invokeApprovalState: vi.fn(),
  invoke: vi.fn(),
  pairChannel: vi.fn(),
  runEval: vi.fn(),
  restoreEvalCase: vi.fn(),
  retryChannelDelivery: vi.fn(),
}));

vi.mock("../src/client", () => ({ client: api }));

import { ChannelsView } from "../src/components/ChannelsView";
import { EvaluationsView } from "../src/components/EvaluationsView";

const channel = {
  id: "ch_1",
  platform: "webhook",
  name: "Support intake",
  transport: "webhook",
  enabled: true,
  unpaired_behavior: "pair",
  config: {},
  credential_configured: true,
};

const binding = {
  id: "cb_1",
  external_user_id: "external-1",
  subject: "user:alice",
  role: "member",
};

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

beforeEach(() => {
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: { writeText: vi.fn().mockResolvedValue(undefined) },
  });
  api.channelBindings.mockResolvedValue({ bindings: [] });
  api.channelDeliveries.mockResolvedValue({ deliveries: [] });
  api.channelPairFinalizations.mockImplementation(async (id: string) => ({
    channel_id: id,
    finalizations: [],
  }));
});

describe("Worker channel administration", () => {
  it("renders an honest admin denial without exposing channel controls", async () => {
    api.channels.mockResolvedValue({ status: "denied", reason: "admin only" });

    render(<ChannelsView />);

    await screen.findByText("Channel administration denied");
    expect(screen.queryByRole("button", { name: "Connect channel" })).toBeNull();
    expect(api.channelBindings).not.toHaveBeenCalled();
  });

  it("connects through the canonical client using a secret-store reference", async () => {
    api.channels
      .mockResolvedValueOnce({ channels: [] })
      .mockResolvedValueOnce({ channels: [channel] });
    api.connectChannel.mockResolvedValue({
      status: "ok",
      channel: channel.id,
      inbound_url: `/v1/channels/${channel.id}/inbound`,
    });

    render(<ChannelsView />);
    await screen.findByText("No channels connected");
    fireEvent.click(screen.getByRole("button", { name: "Connect channel" }));
    fireEvent.change(screen.getByLabelText("Channel name"), {
      target: { value: "Support intake" },
    });
    fireEvent.change(screen.getByLabelText(/^Signing-secret reference/), {
      target: { value: "SUPPORT_WEBHOOK_SECRET" },
    });
    fireEvent.change(screen.getByLabelText("Unknown senders"), {
      target: { value: "pair" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));

    await waitFor(() => expect(api.connectChannel).toHaveBeenCalledWith({
      platform: "webhook",
      name: "Support intake",
      signing_secret_ref: "SUPPORT_WEBHOOK_SECRET",
      unpaired_behavior: "pair",
      enabled: true,
    }));
    await screen.findByText(/Inbound path: \/v1\/channels\/ch_1\/inbound/);
  });

  it("sets a catalogue-backed default target during initial connection", async () => {
    api.channels.mockResolvedValue({
      channels: [],
      addressing_catalogue: {
        targets: [
          {
            id: "cos",
            kind: "chief",
            label: "Chief of staff",
            state: "available",
            runtime_liveness: "unknown_not_probed_by_catalogue",
          },
          {
            id: "workflow:intake",
            kind: "workflow",
            label: "intake",
            state: "available",
            runtime_liveness: "not_applicable",
          },
        ],
        supports_arbitrary_agent_pinning: false,
        scope: { workspace_id: null, departments: "all" },
      },
    });
    api.connectChannel.mockResolvedValue({
      status: "ok",
      channel: channel.id,
    });

    render(<ChannelsView />);
    await screen.findByText("No channels connected");
    fireEvent.click(screen.getByRole("button", { name: "Connect channel" }));
    fireEvent.change(screen.getByLabelText("Channel name"), {
      target: { value: "Workflow intake" },
    });
    fireEvent.change(screen.getByLabelText(/^Signing-secret reference/), {
      target: { value: "INTAKE_WEBHOOK_SECRET" },
    });
    fireEvent.change(screen.getByRole("combobox", {
      name: "Initial default target",
    }), {
      target: { value: "workflow:intake" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));

    await waitFor(() => expect(api.connectChannel).toHaveBeenCalledWith({
      platform: "webhook",
      name: "Workflow intake",
      signing_secret_ref: "INTAKE_WEBHOOK_SECRET",
      unpaired_behavior: "reject",
      enabled: true,
      config: {
        addressing: { default_target: "workflow:intake" },
      },
    }));
  });

  it("invalidates an edited connection approval and replays only the new exact request", async () => {
    api.channels
      .mockResolvedValueOnce({ channels: [] })
      .mockResolvedValueOnce({ channels: [channel] });
    api.connectChannel
      .mockResolvedValueOnce({
        status: "pending_human",
        hitl_request_id: "hitl-connect-old",
      })
      .mockResolvedValueOnce({
        status: "pending_human",
        hitl_request_id: "hitl-connect-exact",
      })
      .mockResolvedValueOnce({ status: "ok", channel: channel.id });
    api.invokeApprovalState.mockResolvedValue({ status: "approved" });

    render(<ChannelsView />);
    await screen.findByText("No channels connected");
    fireEvent.click(screen.getByRole("button", { name: "Connect channel" }));
    fireEvent.change(screen.getByLabelText("Channel name"), {
      target: { value: "Old support" },
    });
    fireEvent.change(screen.getByLabelText(/^Signing-secret reference/), {
      target: { value: "SUPPORT_WEBHOOK_SECRET" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));
    await screen.findByText("Channel connection is waiting for approval");

    fireEvent.change(screen.getByLabelText("Channel name"), {
      target: { value: "Support intake" },
    });
    await screen.findByText("Channel connection changed");
    expect(screen.queryByRole("button", {
      name: "Check approval and apply exact change",
    })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Connect" }));
    await screen.findByText("Channel connection is waiting for approval");
    fireEvent.click(screen.getByRole("button", {
      name: "Check approval and apply exact change",
    }));

    await waitFor(() => expect(api.connectChannel).toHaveBeenNthCalledWith(
      3,
      {
        platform: "webhook",
        name: "Support intake",
        signing_secret_ref: "SUPPORT_WEBHOOK_SECRET",
        unpaired_behavior: "reject",
        enabled: true,
      },
      "hitl-connect-exact",
    ));
    expect(api.invokeApprovalState).toHaveBeenCalledWith("hitl-connect-exact");
    expect(api.invokeApprovalState).not.toHaveBeenCalledWith("hitl-connect-old");
  });

  it("does not misrepresent the generic signed webhook as Teams-native", async () => {
    api.channels.mockResolvedValue({ channels: [] });

    render(<ChannelsView />);
    await screen.findByText("No channels connected");
    fireEvent.click(screen.getByRole("button", { name: "Connect channel" }));
    fireEvent.change(screen.getByLabelText("Platform"), {
      target: { value: "msteams" },
    });

    expect(screen.getByRole("option", {
      name: "Teams-labelled signed webhook",
    })).toBeTruthy();
    expect(screen.getByText(/not a Microsoft Graph, Teams app, bot, or OAuth connection/))
      .toBeTruthy();
    expect(screen.queryByRole("option", { name: "Microsoft Teams" })).toBeNull();
  });

  it("issues a show-once recovery token and labels owner leases as non-liveness evidence", async () => {
    const socketChannel = {
      ...channel,
      id: "ch_socket",
      platform: "slack",
      transport: "socket",
      gateway: {
        status: "awaiting_gateway",
        reason_code: "gateway_token_scope_or_heartbeat_required",
        ownership: {
          status: "unclaimed",
          gateway_id: null,
          lease_expires_at: null,
          single_owner_enforced: true,
          owner_lease_id_disclosed: false,
          proves_process_liveness: false,
        },
      },
    };
    api.channels.mockResolvedValue({ channels: [socketChannel] });
    api.channelGatewaySession.mockResolvedValue({
      status: "ok",
      token: "gateway-show-once-token-value",
      channels: [socketChannel.id],
      gateway_id: "channel-gateway",
      expires_in: 3600,
      bootstrap: {
        token_delivery: "show_once",
        recovery: "replace_token_file_or_restart",
        owner_election: "durable_per_channel_lease",
        provider_credentials_included: false,
      },
    });

    render(<ChannelsView />);
    fireEvent.click(await screen.findByRole("button", { name: /Support intake/ }));
    expect(screen.getByText(/Lease evidence is not process liveness/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", {
      name: "Issue replacement gateway token",
    }));

    await waitFor(() => expect(api.channelGatewaySession).toHaveBeenCalledWith({
      channels: [socketChannel.id],
      gateway_id: "channel-gateway",
    }));
    expect(await screen.findByText("gateway-show-once-token-value")).toBeTruthy();
    expect(screen.getByText(/Replace the mounted token file for hot recovery/))
      .toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Copy token" }));
    expect(await screen.findByText(/Gateway token copied to the clipboard/))
      .toBeTruthy();
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      "gateway-show-once-token-value",
    );
    vi.mocked(navigator.clipboard.writeText).mockRejectedValueOnce(
      new Error("clipboard denied"),
    );
    fireEvent.click(screen.getByRole("button", { name: "Copy token" }));
    expect(await screen.findByText(/gateway token could not be copied/i))
      .toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "I have saved it" }));
    expect(screen.queryByText("gateway-show-once-token-value")).toBeNull();
  });

  it("uses the scoped target catalogue and labels stale addressing honestly", async () => {
    const routedChannel = {
      ...channel,
      config: {
        addressing: {
          default_target: "old-agent",
          routes: { legacy: "workflow:deleted" },
        },
      },
      addressing: {
        configured_default_target: "old-agent",
        effective_default_target: "old-agent",
        default_target_state: "stale_or_unsupported",
        routes: [{
          thread: "legacy",
          target: "workflow:deleted",
          state: "stale_or_unsupported",
        }],
        valid: false,
      },
    };
    api.channels.mockResolvedValue({
      channels: [routedChannel],
      addressing_catalogue: {
        targets: [
          {
            id: "cos",
            kind: "chief",
            label: "Chief of staff",
            state: "available",
            runtime_liveness: "unknown_not_probed_by_catalogue",
          },
          {
            id: "research",
            kind: "department",
            label: "Research",
            state: "restart_required",
            runtime_liveness: "unknown_not_probed_by_catalogue",
          },
          {
            id: "workflow:report",
            kind: "workflow",
            label: "report",
            state: "available",
            runtime_liveness: "not_applicable",
          },
        ],
        supports_arbitrary_agent_pinning: false,
        scope: { workspace_id: null, departments: "all" },
      },
    });
    api.configureChannel.mockResolvedValue({ status: "ok" });

    render(<ChannelsView />);
    fireEvent.click(await screen.findByRole("button", { name: /Support intake/ }));

    expect(screen.getByText(/configured default target is stale or unsupported/i))
      .toBeTruthy();
    expect(screen.getByText(/1 thread route needs repair/i))
      .toBeTruthy();
    expect(screen.getByText(/Arbitrary agent or capability pinning is not supported/))
      .toBeTruthy();
    expect(screen.getAllByRole("option", {
      name: "Department · Research · restart required",
    })).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", {
      name: "Add thread route",
    }));
    const secondRoute = screen.getByLabelText("Thread or chat key 2");
    fireEvent.change(secondRoute, { target: { value: "new-thread" } });
    expect(screen.getByLabelText("Thread or chat key 2")).toBe(secondRoute);
    expect(secondRoute).toHaveProperty("value", "new-thread");
    fireEvent.click(screen.getByRole("button", { name: "Remove route 2" }));
    expect(screen.queryByLabelText("Thread or chat key 2")).toBeNull();

    fireEvent.change(screen.getByRole("combobox", {
      name: /^Default target/,
    }), {
      target: { value: "workflow:report" },
    });
    fireEvent.change(screen.getByRole("combobox", {
      name: "Route target 1",
    }), {
      target: { value: "workflow:report" },
    });
    fireEvent.click(screen.getByRole("checkbox", {
      name: "Enable constrained self-onboarding",
    }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Research" }));
    fireEvent.change(screen.getByLabelText("Welcome message"), {
      target: { value: "Welcome to support." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save settings" }));

    await waitFor(() => expect(api.configureChannel).toHaveBeenCalledWith(
      routedChannel.id,
      expect.objectContaining({
        config: {
          addressing: {
            default_target: "workflow:report",
            routes: { legacy: "workflow:report" },
          },
          self_onboard: {
            role: "member",
            scope: { departments: ["research"] },
            welcome: "Welcome to support.",
          },
        },
      }),
    ));
  });

  it("discards a slow channel's detail responses after another channel is opened", async () => {
    const other = { ...channel, id: "ch_2", name: "Sales intake" };
    api.channels.mockResolvedValue({ channels: [channel, other] });
    let releaseSlowBindings: (result: unknown) => void = () => undefined;
    api.channelBindings.mockImplementation((id: string) => (
      id === channel.id
        ? new Promise((resolve) => { releaseSlowBindings = resolve; })
        : Promise.resolve({ bindings: [] })
    ));

    render(<ChannelsView />);
    fireEvent.click(await screen.findByRole("button", { name: /Support intake/ }));
    fireEvent.click(screen.getByRole("button", { name: /Sales intake/ }));
    await screen.findByText("No sender identities are bound.");

    await act(async () => {
      releaseSlowBindings({ bindings: [binding] });
    });

    expect(screen.queryByText("external-1")).toBeNull();
    expect(api.channelDeliveries).not.toHaveBeenCalledWith(channel.id);
  });

  it("issues a one-time pairing code, supports direct binding, and reports pending configuration", async () => {
    api.channels.mockResolvedValue({ channels: [channel] });
    api.channelBindings.mockResolvedValue({ bindings: [binding] });
    api.pairChannel.mockResolvedValue({
      status: "ok",
      pairing_id: "pair_1",
      code: "PAIR-ONLY-1",
    });
    api.bindChannel.mockResolvedValue({ status: "ok", binding: "cb_2" });
    api.configureChannel
      .mockResolvedValueOnce({
        status: "pending_human",
        hitl_request_id: "hitl-configure",
        reason: "approval required",
      })
      .mockResolvedValueOnce({ status: "ok" });
    api.invokeApprovalState.mockResolvedValue({ status: "approved" });

    render(<ChannelsView />);
    fireEvent.click(await screen.findByRole("button", { name: /Support intake/ }));
    await screen.findByText("external-1");

    fireEvent.change(screen.getByLabelText("External user ID"), {
      target: { value: "sender-42" },
    });
    fireEvent.change(screen.getByLabelText("Boltrig subject"), {
      target: { value: "user:bob" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Issue one-time code" }));

    await waitFor(() => expect(api.pairChannel).toHaveBeenCalledWith(channel.id, {
      external_user_id: "sender-42",
      subject: "user:bob",
      role: "member",
      ttl_minutes: 15,
    }));
    expect(await screen.findByText("PAIR-ONLY-1")).toBeTruthy();
    expect(screen.getByText(/will not show this code again/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "I have saved it" }));
    expect(screen.queryByText("PAIR-ONLY-1")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Direct bind" }));
    fireEvent.change(screen.getByLabelText("External user ID"), {
      target: { value: "sender-43" },
    });
    fireEvent.change(screen.getByLabelText("Boltrig subject"), {
      target: { value: "user:carol" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Bind sender" }));
    await waitFor(() => expect(api.bindChannel).toHaveBeenCalledWith(channel.id, {
      external_user_id: "sender-43",
      subject: "user:carol",
      role: "member",
    }));

    fireEvent.change(screen.getByLabelText("Name"), {
      target: { value: "Priority support" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save settings" }));
    await screen.findByText(
      "Channel configuration is waiting for human approval in Inbox.",
    );
    expect(api.configureChannel).toHaveBeenNthCalledWith(1, channel.id, {
      name: "Priority support",
      enabled: true,
      unpaired_behavior: "pair",
      config: {},
    });
    fireEvent.click(screen.getByRole("button", {
      name: "Check approval and apply exact change",
    }));
    await waitFor(() => expect(api.configureChannel).toHaveBeenNthCalledWith(
      2,
      channel.id,
      {
        name: "Priority support",
        enabled: true,
        unpaired_behavior: "pair",
        config: {},
      },
      "hitl-configure",
    ));
  });

  it("creates a pairing code only after requester-owned approval is finalized", async () => {
    api.channels.mockResolvedValue({ channels: [channel] });
    api.pairChannel
      .mockResolvedValueOnce({
        status: "pending_human",
        hitl_request_id: "hitl-pair",
      })
      .mockResolvedValueOnce({
        status: "ok",
        pairing_id: "pair-approved",
        code: "PAIR-AFTER-APPROVAL",
      });
    api.invokeApprovalState.mockResolvedValue({ status: "approved" });

    render(<ChannelsView />);
    fireEvent.click(await screen.findByRole("button", { name: /Support intake/ }));
    await screen.findByText("No sender identities are bound.");
    fireEvent.change(screen.getByLabelText("External user ID"), {
      target: { value: "sender-approved" },
    });
    fireEvent.change(screen.getByLabelText("Boltrig subject"), {
      target: { value: "user:approved" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Issue one-time code" }));

    await screen.findByText("Pairing is waiting for approval");
    expect(screen.queryByText("PAIR-AFTER-APPROVAL")).toBeNull();
    fireEvent.click(screen.getByRole("button", {
      name: "Check approval and issue one-time code",
    }));

    await waitFor(() => expect(api.pairChannel).toHaveBeenNthCalledWith(
      2,
      channel.id,
      {
        external_user_id: "sender-approved",
        subject: "user:approved",
        role: "member",
        ttl_minutes: 15,
      },
      "hitl-pair",
    ));
    expect(await screen.findByText("PAIR-AFTER-APPROVAL")).toBeTruthy();
  });

  it("recovers only safe approved pairing intent after navigation", async () => {
    api.channels.mockResolvedValue({ channels: [channel] });
    api.channelPairFinalizations.mockResolvedValue({
      channel_id: channel.id,
      finalizations: [{
        request_id: "hitl-recovered-pair",
        state: "ready",
        external_user_id: "sender-recovered",
        subject: "user:recovered",
        role: "member",
        ttl_minutes: 20,
      }],
    });
    api.pairChannel.mockResolvedValue({
      status: "ok",
      pairing_id: "pair-recovered",
      code: "RECOVERED-ONCE",
    });
    api.invokeApprovalState.mockResolvedValue({ status: "approved" });

    render(<ChannelsView />);
    fireEvent.click(await screen.findByRole("button", { name: /Support intake/ }));

    await screen.findByText("Approved pairing is ready");
    expect(screen.getByText(/sender-recovered/)).toBeTruthy();
    expect(screen.queryByText("RECOVERED-ONCE")).toBeNull();
    fireEvent.click(screen.getByRole("button", {
      name: "Check approval and issue one-time code",
    }));

    await waitFor(() => expect(api.pairChannel).toHaveBeenCalledWith(
      channel.id,
      {
        external_user_id: "sender-recovered",
        subject: "user:recovered",
        role: "member",
        ttl_minutes: 20,
      },
      "hitl-recovered-pair",
    ));
    expect(await screen.findByText("RECOVERED-ONCE")).toBeTruthy();
  });

  it("replays a pending channel test with the same body and idempotency key", async () => {
    api.channels.mockResolvedValue({ channels: [channel] });
    api.invoke
      .mockResolvedValueOnce({
        status: "pending_human",
        hitl_request_id: "hitl-channel-send",
      })
      .mockResolvedValueOnce({
        status: "ok",
        output: { status: "queued" },
      });
    api.invokeApprovalState.mockResolvedValue({ status: "approved" });

    render(<ChannelsView />);
    fireEvent.click(await screen.findByRole("button", { name: /Support intake/ }));
    fireEvent.change(screen.getByLabelText("Message"), {
      target: { value: "Hello exact channel" },
    });
    fireEvent.change(screen.getByLabelText("Optional target"), {
      target: { value: "sender-55" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send test" }));

    await screen.findByText("Channel test message is waiting for approval");
    const initial = api.invoke.mock.calls[0]?.[0];
    fireEvent.click(screen.getByRole("button", {
      name: "Check approval and apply exact change",
    }));

    await waitFor(() => expect(api.invoke).toHaveBeenCalledTimes(2));
    expect(api.invoke.mock.calls[1]?.[0]).toEqual({
      ...initial,
      approval_id: "hitl-channel-send",
    });
    await screen.findByText(
      "Queued for sidecar delivery; delivery is not yet confirmed.",
    );
  });

  it("requires confirmation before removing a binding or disconnecting", async () => {
    api.channels
      .mockResolvedValueOnce({ channels: [channel] })
      .mockResolvedValue({ channels: [] });
    api.channelBindings.mockResolvedValue({ bindings: [binding] });
    api.deleteChannelBinding.mockResolvedValue({ status: "ok" });
    api.disconnectChannel.mockResolvedValue({ status: "ok" });

    render(<ChannelsView />);
    fireEvent.click(await screen.findByRole("button", { name: /Support intake/ }));
    await screen.findByText("external-1");

    fireEvent.click(screen.getByRole("button", { name: "Remove" }));
    expect(api.deleteChannelBinding).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Confirm remove" }));
    await waitFor(() => expect(api.deleteChannelBinding).toHaveBeenCalledWith(channel.id, binding.id));

    fireEvent.click(screen.getByRole("button", { name: "Disconnect channel" }));
    expect(api.disconnectChannel).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Confirm disconnect" }));
    await waitFor(() => expect(api.disconnectChannel).toHaveBeenCalledWith(channel.id));
  });

  it("finalizes exact approved unbind and disconnect mutations", async () => {
    api.channels
      .mockResolvedValueOnce({ channels: [channel] })
      .mockResolvedValueOnce({ channels: [] });
    api.channelBindings
      .mockResolvedValueOnce({ bindings: [binding] })
      .mockResolvedValue({ bindings: [] });
    api.deleteChannelBinding
      .mockResolvedValueOnce({
        status: "pending_human",
        hitl_request_id: "hitl-unbind",
      })
      .mockResolvedValueOnce({ status: "ok" });
    api.disconnectChannel
      .mockResolvedValueOnce({
        status: "pending_human",
        hitl_request_id: "hitl-disconnect",
      })
      .mockResolvedValueOnce({ status: "ok" });
    api.invokeApprovalState.mockResolvedValue({ status: "approved" });

    render(<ChannelsView />);
    fireEvent.click(await screen.findByRole("button", { name: /Support intake/ }));
    await screen.findByText("external-1");
    fireEvent.click(screen.getByRole("button", { name: "Remove" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm remove" }));
    await screen.findByText("Sender unbind is waiting for approval");
    fireEvent.click(screen.getByRole("button", {
      name: "Check approval and apply exact change",
    }));

    await waitFor(() => expect(api.deleteChannelBinding).toHaveBeenNthCalledWith(
      2,
      channel.id,
      binding.id,
      "hitl-unbind",
    ));
    await screen.findByText("No sender identities are bound.");

    fireEvent.click(screen.getByRole("button", { name: "Disconnect channel" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm disconnect" }));
    await screen.findByText("Channel disconnect is waiting for approval");
    fireEvent.click(screen.getByRole("button", {
      name: "Check approval and apply exact change",
    }));

    await waitFor(() => expect(api.disconnectChannel).toHaveBeenNthCalledWith(
      2,
      channel.id,
      "hitl-disconnect",
    ));
    await screen.findByText("No channels connected");
  });

  it("shows safe outbound receipts and retries only the exact terminal snapshot", async () => {
    const socketChannel = {
      ...channel,
      platform: "slack",
      transport: "socket",
      provider: { label: "Slack", credential_keys: [] },
    };
    api.channels.mockResolvedValue({ channels: [socketChannel] });
    api.channelDeliveries.mockResolvedValue({
      deliveries: [
        {
          id: "delivery-queued",
          channel_id: channel.id,
          status: "queued",
          attempts: 0,
          safe_reason: null,
          created_at: "2026-07-30T10:00:00+00:00",
          updated_at: "2026-07-30T10:00:00+00:00",
          next_attempt_at: null,
        },
        {
          id: "delivery-retry",
          channel_id: channel.id,
          status: "retryable",
          attempts: 2,
          safe_reason: "delivery_failed",
          created_at: "2026-07-30T09:00:00+00:00",
          updated_at: "2026-07-30T09:05:00+00:00",
          next_attempt_at: "2026-07-30T09:10:00+00:00",
        },
        {
          id: "delivery-terminal",
          channel_id: channel.id,
          status: "terminal_failed",
          attempts: 3,
          safe_reason: "delivery_failed",
          created_at: "2026-07-30T08:00:00+00:00",
          updated_at: "2026-07-30T08:05:00+00:00",
          next_attempt_at: null,
        },
      ],
    });
    api.retryChannelDelivery
      .mockResolvedValueOnce({
        status: "pending_human",
        hitl_request_id: "hitl-delivery",
      })
      .mockResolvedValueOnce({
        status: "ok",
        delivery: {
          id: "delivery-terminal",
          channel_id: channel.id,
          status: "queued",
          attempts: 0,
          safe_reason: null,
          created_at: "2026-07-30T08:00:00+00:00",
          updated_at: "2026-07-30T08:06:00+00:00",
          next_attempt_at: null,
        },
      });
    api.invokeApprovalState.mockResolvedValue({ status: "approved" });

    render(<ChannelsView />);
    fireEvent.click(await screen.findByRole("button", { name: /Support intake/ }));

    await screen.findByText("Terminal failure");
    expect(screen.getByText("Queued")).toBeTruthy();
    expect(screen.getByText("Retry scheduled")).toBeTruthy();
    expect(screen.queryByText(/private message body/i)).toBeNull();
    expect(screen.queryByText(/private-gateway-lease-owner/i)).toBeNull();
    expect(screen.getAllByRole("button", { name: "Request retry" })).toHaveLength(1);

    fireEvent.click(screen.getByRole("button", { name: "Request retry" }));
    await waitFor(() => expect(api.retryChannelDelivery).toHaveBeenNthCalledWith(
      1,
      channel.id,
      "delivery-terminal",
      "2026-07-30T08:05:00+00:00",
    ));
    await screen.findByText("Delivery retry is waiting for human approval in Inbox.");
    fireEvent.click(screen.getByRole("button", {
      name: "Check approval and continue exact retry",
    }));
    await waitFor(() => expect(api.invokeApprovalState).toHaveBeenCalledWith(
      "hitl-delivery",
    ));
    await waitFor(() => expect(api.retryChannelDelivery).toHaveBeenNthCalledWith(
      2,
      channel.id,
      "delivery-terminal",
      "2026-07-30T08:05:00+00:00",
      "hitl-delivery",
    ));
    await screen.findByText(
      "The exact approved failed delivery was queued for a fresh delivery cycle.",
    );
  });

  it("invalidates a pending retry when the channel receipt is refreshed", async () => {
    const terminal = {
      id: "delivery-terminal",
      channel_id: channel.id,
      status: "terminal_failed",
      attempts: 3,
      safe_reason: "delivery_failed",
      created_at: "2026-07-30T08:00:00+00:00",
      updated_at: "2026-07-30T08:05:00+00:00",
      next_attempt_at: null,
    };
    api.channels.mockResolvedValue({ channels: [channel] });
    api.channelDeliveries.mockResolvedValue({ deliveries: [terminal] });
    api.retryChannelDelivery.mockResolvedValue({
      status: "pending_human",
      hitl_request_id: "hitl-stale-delivery",
    });
    api.invokeApprovalState.mockResolvedValue({ status: "approved" });

    render(<ChannelsView />);
    const channelButton = await screen.findByRole("button", { name: /Support intake/ });
    fireEvent.click(channelButton);
    fireEvent.click(await screen.findByRole("button", { name: "Request retry" }));
    await screen.findByText("Waiting for an Inbox decision");

    fireEvent.click(channelButton);
    await screen.findByText("Pending delivery retry changed");
    expect(screen.queryByRole("button", {
      name: "Check approval and continue exact retry",
    })).toBeNull();
    expect(api.invokeApprovalState).not.toHaveBeenCalled();
    expect(api.retryChannelDelivery).toHaveBeenCalledTimes(1);
  });

  it.each([
    ["rejected", "Retry rejected"],
    ["expired", "Retry approval expired"],
  ])("keeps a %s retry decision terminal without requeue", async (status, label) => {
    api.channels.mockResolvedValue({ channels: [channel] });
    api.channelDeliveries.mockResolvedValue({
      deliveries: [{
        id: "delivery-terminal",
        channel_id: channel.id,
        status: "terminal_failed",
        attempts: 3,
        safe_reason: "delivery_failed",
        created_at: "2026-07-30T08:00:00+00:00",
        updated_at: "2026-07-30T08:05:00+00:00",
        next_attempt_at: null,
      }],
    });
    api.retryChannelDelivery.mockResolvedValue({
      status: "pending_human",
      hitl_request_id: `hitl-${status}`,
    });
    api.invokeApprovalState.mockResolvedValue({ status });

    render(<ChannelsView />);
    fireEvent.click(await screen.findByRole("button", { name: /Support intake/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Request retry" }));
    fireEvent.click(await screen.findByRole("button", {
      name: "Check approval and continue exact retry",
    }));

    await screen.findByText(label);
    expect(api.retryChannelDelivery).toHaveBeenCalledTimes(1);
  });
});

const evalCase = {
  id: "safe-triage",
  target_kind: "skill",
  target_ref: "triage",
  input: { task: "classify ticket" },
  assertions: { must_not_call: ["ticket.delete"] },
  labels: ["security"],
  is_active: true,
  status: "active" as const,
};

describe("Worker evaluations", () => {
  it("keeps sensitive fixtures hidden when the author boundary denies access", async () => {
    api.evalCases.mockRejectedValue(
      new BoltrigApiError(403, { detail: "author role required" }),
    );

    render(<EvaluationsView />);

    await screen.findByText("Evaluation access denied");
    expect(screen.queryByRole("button", { name: "New evaluation" })).toBeNull();
    expect(api.evalRuns).not.toHaveBeenCalled();
  });

  it("invalidates edited fixture approval and replays only the exact approved save", async () => {
    api.evalCases
      .mockResolvedValueOnce({ cases: [] })
      .mockResolvedValueOnce({ cases: [evalCase] });
    api.evalRuns.mockResolvedValue({ runs: [] });
    api.createEvalCase
      .mockResolvedValueOnce({
        status: "pending_human",
        hitl_request_id: "hitl_old",
      })
      .mockResolvedValueOnce({
        status: "pending_human",
        hitl_request_id: "hitl_exact",
      })
      .mockResolvedValueOnce({
        status: "ok",
        id: "safe-triage",
      });
    api.invokeApprovalState.mockResolvedValue({ status: "approved" });

    render(<EvaluationsView />);
    fireEvent.click(await screen.findByRole("button", { name: "New evaluation" }));
    expect(
      Array.from(
        (screen.getByLabelText("Target kind") as HTMLSelectElement).options,
      ).map((option) => option.value),
    ).toEqual(["skill", "workflow"]);
    fireEvent.change(screen.getByLabelText("Case ID (optional)"), {
      target: { value: "safe-triage" },
    });
    fireEvent.change(screen.getByLabelText("Target reference"), {
      target: { value: "triage" },
    });
    fireEvent.change(screen.getByLabelText("Input (JSON object)"), {
      target: { value: "{\"task\":\"classify ticket\"}" },
    });
    fireEvent.change(screen.getByLabelText("Assertions (JSON object)"), {
      target: { value: "{\"must_not_call\":[\"ticket.delete\"]}" },
    });
    fireEvent.change(screen.getByLabelText("Labels (comma separated)"), {
      target: { value: "security, regression" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save case" }));

    await waitFor(() => expect(api.createEvalCase).toHaveBeenCalledWith({
      id: "safe-triage",
      target_kind: "skill",
      target_ref: "triage",
      input: { task: "classify ticket" },
      assertions: { must_not_call: ["ticket.delete"] },
      labels: ["security", "regression"],
    }));
    expect(await screen.findByText("This evaluation case is waiting for human approval in Inbox.")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Labels (comma separated)"), {
      target: { value: "security, regression, approved" },
    });
    expect(
      await screen.findByText("Evaluation fixture save changed"),
    ).toBeTruthy();
    expect(api.invokeApprovalState).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Save case" }));
    expect(
      await screen.findByText("Evaluation fixture save is waiting for approval"),
    ).toBeTruthy();
    fireEvent.click(screen.getByRole("button", {
      name: "Check approval and apply exact change",
    }));

    await waitFor(() => expect(api.invokeApprovalState).toHaveBeenCalledWith(
      "hitl_exact",
    ));
    await waitFor(() => expect(api.createEvalCase).toHaveBeenLastCalledWith({
      id: "safe-triage",
      target_kind: "skill",
      target_ref: "triage",
      input: { task: "classify ticket" },
      assertions: { must_not_call: ["ticket.delete"] },
      labels: ["security", "regression", "approved"],
    }, "hitl_exact"));
    expect(await screen.findByText(
      "Evaluation case saved through the exact approved authoring route.",
    )).toBeTruthy();
  });

  it("runs a case and refreshes durable history with the actual verdict", async () => {
    api.evalCases.mockResolvedValue({ cases: [evalCase] });
    api.evalRuns
      .mockResolvedValueOnce({ runs: [] })
      .mockResolvedValueOnce({
        runs: [{
          id: "evalrun_1",
          case_id: evalCase.id,
          passed: true,
          score: 1,
          run_id: "run_1",
          target_kind: "skill",
          target_ref: "triage",
          detail: {
            target: { kind: "skill", ref: "triage" },
            checks: { "must_not_call:ticket.delete": true },
          },
        }],
      });
    api.runEval.mockResolvedValue({
      id: "evalrun_1",
      passed: true,
      score: 1,
      run_id: "run_1",
      detail: {
        checks: { "must_not_call:ticket.delete": true },
        effective_grants: ["ticket.read"],
      },
    });

    render(<EvaluationsView />);
    fireEvent.click(await screen.findByRole("button", { name: /safe-triage/ }));
    fireEvent.click(screen.getByRole("button", { name: "Run evaluation" }));

    await waitFor(() => expect(api.runEval).toHaveBeenCalledWith({ case_id: "safe-triage" }));
    expect(await screen.findByText("Passed · 100%")).toBeTruthy();
    expect(screen.getByText("✓ must_not_call:ticket.delete")).toBeTruthy();
    expect(await screen.findByText(/evalrun_1 · run run_1/)).toBeTruthy();
    expect(screen.getAllByText("skill · triage")).toHaveLength(2);
    fireEvent.click(screen.getByText("Run details"));
    expect(screen.getByText(/"must_not_call:ticket.delete": true/)).toBeTruthy();
  });

  it("keeps archived cases visible, disables runs, and restores through governance", async () => {
    const archivedCase = {
      ...evalCase,
      is_active: false,
      status: "archived" as const,
    };
    api.evalCases
      .mockResolvedValueOnce({ cases: [archivedCase] })
      .mockResolvedValueOnce({ cases: [evalCase] });
    api.evalRuns.mockResolvedValue({
      runs: [{
        id: "evalrun_old",
        case_id: archivedCase.id,
        passed: true,
        score: 1,
        run_id: "run_old",
      }],
    });
    api.restoreEvalCase
      .mockResolvedValueOnce({
        status: "pending_human",
        hitl_request_id: "hitl_restore",
      })
      .mockResolvedValueOnce({
        status: "ok",
        id: archivedCase.id,
        eval_case_status: "active",
      });
    api.invokeApprovalState.mockResolvedValue({ status: "approved" });

    render(<EvaluationsView />);
    fireEvent.click(await screen.findByRole("button", { name: /safe-triage/ }));

    expect(
      (screen.getByRole("button", { name: "Run evaluation" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    expect(screen.getByText("evalrun_old · run run_old")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Restore case" }));

    await waitFor(() => expect(api.restoreEvalCase).toHaveBeenCalledWith("safe-triage"));
    expect(await screen.findByText(
      "This evaluation restore is waiting for human approval in Inbox.",
    )).toBeTruthy();
    fireEvent.click(screen.getByRole("button", {
      name: "Check approval and apply exact change",
    }));
    await waitFor(() => expect(api.restoreEvalCase).toHaveBeenLastCalledWith(
      "safe-triage", "hitl_restore",
    ));
    expect(await screen.findByText(
      "Evaluation case restored and available to run.",
    )).toBeTruthy();
    expect(api.runEval).not.toHaveBeenCalled();
  });
});
