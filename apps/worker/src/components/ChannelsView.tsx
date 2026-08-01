import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type {
  BindChannelRequest,
  ChannelAck,
  ChannelAddressingCatalogue,
  ChannelAddressingTarget,
  ChannelBindingSummary,
  ChannelDeliveryReceipt,
  ChannelPairFinalization,
  ChannelSummary,
  ConfigureChannelRequest,
  ConnectChannelRequest,
  ConnectChannelResponse,
  InvokeResult,
  PairChannelRequest,
} from "@wlilley93/boltrig-web-sdk";

import { client } from "../client";
import { copySensitiveText } from "../clipboard";
import {
  ExactApprovalFinalizer,
  governedResultReason,
  type GovernedResult,
  useExactApprovalFinalizer,
} from "./ExactApprovalFinalizer";
import { Topbar, Unavailable } from "./Shell";

type SurfaceState = "loading" | "ready" | "denied" | "unavailable";
type BindingMode = "pair" | "bind";
type Notice = { text: string; error?: boolean };
type DeliveryFinalizationState =
  | "waiting"
  | "checking"
  | "invalidated"
  | "rejected"
  | "expired"
  | "consumed"
  | "unavailable"
  | null;

interface PendingDeliveryRetry {
  channelId: string;
  messageId: string;
  expectedUpdatedAt: string;
  approvalId: string;
  invalidated: boolean;
}

type PairFinalizationState =
  | "waiting"
  | "ready"
  | "checking"
  | "invalidated"
  | "rejected"
  | "expired"
  | "consumed"
  | "unavailable"
  | null;

interface PendingPairingFinalization {
  channelId: string;
  approvalId: string;
  body: PairChannelRequest;
  state: "waiting" | "ready";
  invalidated: boolean;
}

type ExactChannelMutation =
  | { kind: "connect"; body: ConnectChannelRequest }
  | {
      kind: "configure";
      channelId: string;
      body: ConfigureChannelRequest;
    }
  | { kind: "disconnect"; channelId: string }
  | {
      kind: "bind";
      channelId: string;
      body: BindChannelRequest;
    }
  | {
      kind: "unbind";
      channelId: string;
      bindingId: string;
    };

interface ExactChannelResult extends GovernedResult {
  value?: ConnectChannelResponse | ChannelAck;
}

interface ChannelSendInput {
  channelId: string;
  text: string;
  target: string;
  idempotencyKey: string;
}

interface ChannelSendFinalResult extends GovernedResult {
  value?: InvokeResult;
}

const channelProviders = {
  webhook: { label: "Signed webhook", credentials: ["signing"], activation: "automatic" },
  msteams: { label: "Teams-labelled signed webhook", credentials: ["signing"], activation: "automatic" },
  slack: { label: "Slack Socket Mode", credentials: ["signing", "app_token", "bot_token"], activation: "automatic" },
  telegram: { label: "Telegram bot", credentials: ["signing", "bot_token"], activation: "automatic" },
  discord: { label: "Discord bot", credentials: ["signing", "bot_token"], activation: "automatic" },
  signal: { label: "Signal", credentials: ["signing"], activation: "external_pairing" },
  whatsapp: { label: "WhatsApp", credentials: ["signing"], activation: "external_pairing" },
  generic: { label: "Generic socket surface", credentials: ["signing"], activation: "deployment_managed" },
  voice: { label: "Realtime voice", credentials: ["signing", "api_key"], activation: "automatic" },
} as const;

interface BindingDraft {
  externalUserId: string;
  subject: string;
  role: string;
  ttl: string;
}

const blankBinding: BindingDraft = {
  externalUserId: "",
  subject: "",
  role: "member",
  ttl: "15",
};

const fallbackAddressingCatalogue: ChannelAddressingCatalogue = {
  targets: [{
    id: "cos",
    kind: "chief",
    label: "Chief of staff",
    state: "available",
    runtime_liveness: "unknown_not_probed_by_catalogue",
  }],
  supports_arbitrary_agent_pinning: false,
  scope: { workspace_id: null, departments: [] },
};

export function ChannelsView() {
  const [channels, setChannels] = useState<ChannelSummary[]>([]);
  const [addressingCatalogue, setAddressingCatalogue] =
    useState<ChannelAddressingCatalogue>(fallbackAddressingCatalogue);
  const [surfaceState, setSurfaceState] = useState<SurfaceState>("loading");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [bindings, setBindings] = useState<ChannelBindingSummary[]>([]);
  const [bindingState, setBindingState] = useState<SurfaceState>("loading");
  const [deliveries, setDeliveries] = useState<ChannelDeliveryReceipt[]>([]);
  const [deliveryState, setDeliveryState] = useState<SurfaceState>("loading");
  const [pendingDeliveryRetry, setPendingDeliveryRetry] =
    useState<PendingDeliveryRetry | null>(null);
  const [deliveryFinalization, setDeliveryFinalization] =
    useState<DeliveryFinalizationState>(null);
  const [pendingPairing, setPendingPairing] =
    useState<PendingPairingFinalization | null>(null);
  const [pairFinalization, setPairFinalization] =
    useState<PairFinalizationState>(null);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [busy, setBusy] = useState("");
  const [creating, setCreating] = useState(false);
  const [disconnectArmed, setDisconnectArmed] = useState(false);
  const [deleteArmed, setDeleteArmed] = useState<string | null>(null);
  const [bindingMode, setBindingMode] = useState<BindingMode>("pair");
  const [bindingDraft, setBindingDraft] = useState<BindingDraft>(blankBinding);
  const [pairingSecret, setPairingSecret] = useState<{
    code: string;
    externalUserId: string;
    pairingId?: string;
  } | null>(null);
  const exactApprovalInvalidator = useRef<() => void>(() => undefined);
  const channelDetailSequence = useRef(0);

  const selected = useMemo(
    () => channels.find((channel) => channel.id === selectedId) ?? null,
    [channels, selectedId],
  );

  const invalidateExactApproval = useCallback(() => {
    exactApprovalInvalidator.current();
  }, []);

  const exactApproval = useExactApprovalFinalizer<
    ExactChannelMutation,
    ExactChannelResult
  >({
    isCurrent: (mutation) => {
      if (mutation.kind === "connect") return creating;
      if (selected?.id !== mutation.channelId) return false;
      if (mutation.kind === "disconnect") return disconnectArmed;
      if (mutation.kind === "bind") {
        return bindingMode === "bind"
          && routeInputEquals(mutation.body, bindingRequest(bindingDraft));
      }
      if (mutation.kind === "unbind") {
        return deleteArmed === mutation.bindingId
          && bindings.some((binding) => binding.id === mutation.bindingId);
      }
      return true;
    },
    replay: async (mutation, approvalId) => {
      if (mutation.kind === "connect") {
        return normalizeChannelResult(
          await client.connectChannel(mutation.body, approvalId),
        );
      }
      if (mutation.kind === "configure") {
        return normalizeChannelResult(
          await client.configureChannel(
            mutation.channelId, mutation.body, approvalId,
          ),
        );
      }
      if (mutation.kind === "disconnect") {
        return normalizeChannelResult(
          await client.disconnectChannel(mutation.channelId, approvalId),
        );
      }
      if (mutation.kind === "bind") {
        return normalizeChannelResult(
          await client.bindChannel(
            mutation.channelId, mutation.body, approvalId,
          ),
        );
      }
      return normalizeChannelResult(
        await client.deleteChannelBinding(
          mutation.channelId, mutation.bindingId, approvalId,
        ),
      );
    },
    onApplied: async (result, mutation) => {
      if (mutation.kind === "connect") {
        const value = result.value as ConnectChannelResponse | undefined;
        setCreating(false);
        await refreshChannels(value?.channel ?? null);
        setNotice({
          text: value?.inbound_url
            ? `Channel connected. Inbound path: ${value.inbound_url}`
            : "Channel connected.",
        });
        return;
      }
      if (mutation.kind === "configure") {
        await refreshChannels(mutation.channelId);
        setNotice({ text: "Channel settings saved." });
        return;
      }
      if (mutation.kind === "disconnect") {
        setBindings([]);
        setDeliveries([]);
        setSelectedId(null);
        setDisconnectArmed(false);
        await refreshChannels(null);
        setNotice({ text: "Channel disconnected." });
        return;
      }
      if (mutation.kind === "bind") {
        setBindingDraft(blankBinding);
        if (selected) await openChannel(selected);
        setNotice({ text: "Sender bound directly." });
        return;
      }
      setDeleteArmed(null);
      if (selected) await openChannel(selected);
      setNotice({ text: "Binding removed." });
    },
    onRefused: (result) => {
      setNotice({
        text: governedResultReason(
          result, "The exact approved channel change was refused.",
        ),
        error: true,
      });
    },
  });
  exactApprovalInvalidator.current = exactApproval.invalidate;

  function invalidatePendingPairing() {
    setPendingPairing((current) => (
      current === null ? null : { ...current, invalidated: true }
    ));
    setPairFinalization((current) => (
      current === "waiting"
      || current === "ready"
      || current === "checking"
      || current === "unavailable"
        ? "invalidated"
        : current
    ));
  }

  function invalidatePendingDeliveryRetry() {
    setPendingDeliveryRetry((current) => (
      current === null ? null : { ...current, invalidated: true }
    ));
    setDeliveryFinalization((current) => (
      current === "waiting" || current === "checking" ? "invalidated" : current
    ));
  }

  async function refreshChannels(preferredId = selectedId) {
    invalidateExactApproval();
    invalidatePendingPairing();
    invalidatePendingDeliveryRetry();
    setSurfaceState("loading");
    try {
      const result = await client.channels();
      if (result.status === "denied") {
        setChannels([]);
        setAddressingCatalogue(fallbackAddressingCatalogue);
        setSelectedId(null);
        setSurfaceState("denied");
        setNotice({ text: result.reason ?? "Channel administration is restricted.", error: true });
        return;
      }
      const next = result.channels ?? [];
      setChannels(next);
      setAddressingCatalogue(
        result.addressing_catalogue ?? fallbackAddressingCatalogue,
      );
      setSelectedId(next.some((item) => item.id === preferredId) ? preferredId : null);
      setSurfaceState("ready");
    } catch {
      setSurfaceState("unavailable");
    }
  }

  async function openChannel(channel: ChannelSummary) {
    invalidateExactApproval();
    invalidatePendingPairing();
    invalidatePendingDeliveryRetry();
    const sequence = ++channelDetailSequence.current;
    setSelectedId(channel.id);
    setDisconnectArmed(false);
    setDeleteArmed(null);
    setPairingSecret(null);
    setNotice(null);
    setBindingState("loading");
    setDeliveryState("loading");
    try {
      const [result, pairResult] = await Promise.all([
        client.channelBindings(channel.id),
        client.channelPairFinalizations(channel.id).catch(() => ({
          channel_id: channel.id,
          finalizations: [] as ChannelPairFinalization[],
        })),
      ]);
      if (channelDetailSequence.current !== sequence) return;
      if (result.status === "denied") {
        setBindings([]);
        setBindingState("denied");
        setNotice({ text: result.reason ?? "Binding administration is restricted.", error: true });
      } else {
        setBindings(result.bindings ?? []);
        setBindingState("ready");
      }
      const pairing = [...pairResult.finalizations].sort(
        (left, right) => Number(right.state === "ready")
          - Number(left.state === "ready"),
      )[0];
      if (pairing) {
        setPendingPairing({
          channelId: channel.id,
          approvalId: pairing.request_id,
          body: {
            external_user_id: pairing.external_user_id,
            subject: pairing.subject,
            role: pairing.role,
            ttl_minutes: pairing.ttl_minutes,
          },
          state: pairing.state,
          invalidated: false,
        });
        setPairFinalization(pairing.state);
      } else {
        setPendingPairing(null);
        setPairFinalization(null);
      }
    } catch {
      if (channelDetailSequence.current !== sequence) return;
      setBindings([]);
      setBindingState("unavailable");
    }
    if (channelDetailSequence.current !== sequence) return;
    await loadDeliveries(channel.id);
  }

  async function loadDeliveries(channelId: string, invalidatePending = true) {
    if (invalidatePending) invalidatePendingDeliveryRetry();
    const sequence = channelDetailSequence.current;
    setDeliveryState("loading");
    try {
      const result = await client.channelDeliveries(channelId);
      if (channelDetailSequence.current !== sequence) return;
      if (result.status === "denied") {
        setDeliveries([]);
        setDeliveryState("denied");
      } else {
        setDeliveries(result.deliveries ?? []);
        setDeliveryState("ready");
      }
    } catch {
      if (channelDetailSequence.current !== sequence) return;
      setDeliveries([]);
      setDeliveryState("unavailable");
    }
  }

  async function retryDelivery(delivery: ChannelDeliveryReceipt) {
    if (!selected || !delivery.updated_at) return;
    setBusy(`retry:${delivery.id}`);
    setNotice(null);
    try {
      const result = await client.retryChannelDelivery(
        selected.id,
        delivery.id,
        delivery.updated_at,
      );
      if (result.status === "pending_human") {
        setPendingDeliveryRetry({
          channelId: selected.id,
          messageId: delivery.id,
          expectedUpdatedAt: delivery.updated_at,
          approvalId: result.hitl_request_id ?? "",
          invalidated: !result.hitl_request_id,
        });
        setDeliveryFinalization(result.hitl_request_id ? "waiting" : "unavailable");
        setNotice({ text: "Delivery retry is waiting for human approval in Inbox." });
      } else if (result.status === "ok") {
        setPendingDeliveryRetry(null);
        setDeliveryFinalization(null);
        await loadDeliveries(selected.id, false);
        setNotice({ text: "The exact failed delivery was queued for a fresh delivery cycle." });
      } else {
        setNotice({
          text: result.reason ?? "The failed delivery was not retried.",
          error: true,
        });
      }
    } catch {
      setNotice({
        text: "The failed delivery was not retried; its terminal receipt remains unchanged.",
        error: true,
      });
    } finally {
      setBusy("");
    }
  }

  async function finalizeDeliveryRetry() {
    const pending = pendingDeliveryRetry;
    const current = deliveries.find((item) => item.id === pending?.messageId);
    if (
      pending === null
      || pending.invalidated
      || selected?.id !== pending.channelId
      || current?.status !== "terminal_failed"
      || current.updated_at !== pending.expectedUpdatedAt
    ) {
      setDeliveryFinalization("invalidated");
      return;
    }
    setBusy(`retry:${pending.messageId}`);
    setDeliveryFinalization("checking");
    setNotice(null);
    try {
      const approval = await client.invokeApprovalState(pending.approvalId);
      if (approval.status === "pending") {
        setDeliveryFinalization("waiting");
        return;
      }
      if (
        approval.status === "rejected"
        || approval.status === "expired"
        || approval.status === "consumed"
      ) {
        setDeliveryFinalization(approval.status);
        return;
      }
      const result = await client.retryChannelDelivery(
        pending.channelId,
        pending.messageId,
        pending.expectedUpdatedAt,
        pending.approvalId,
      );
      if (result.status === "ok") {
        await loadDeliveries(pending.channelId, false);
        setPendingDeliveryRetry(null);
        setDeliveryFinalization(null);
        setNotice({
          text: "The exact approved failed delivery was queued for a fresh delivery cycle.",
        });
      } else {
        setDeliveryFinalization("invalidated");
        setNotice({
          text: result.reason ?? "The approved delivery snapshot could not be retried.",
          error: true,
        });
      }
    } catch {
      setDeliveryFinalization("unavailable");
    } finally {
      setBusy("");
    }
  }

  function closeChannel() {
    invalidateExactApproval();
    invalidatePendingPairing();
    invalidatePendingDeliveryRetry();
    setSelectedId(null);
  }

  useEffect(() => {
    void refreshChannels(null);
  }, []);

  async function connectChannel(body: ConnectChannelRequest) {
    invalidateExactApproval();
    invalidatePendingPairing();
    const mutation: ExactChannelMutation = { kind: "connect", body };
    setBusy("connect");
    setNotice(null);
    try {
      const result = await client.connectChannel(mutation.body);
      if (exactApproval.begin(
        mutation, result, "Channel connection",
      )) {
        setNotice({
          text: "Channel connection is waiting for human approval in Inbox.",
        });
      } else if (result.status === "ok") {
        setCreating(false);
        await refreshChannels(result.channel ?? null);
        setNotice({ text: result.inbound_url
          ? `Channel connected. Inbound path: ${result.inbound_url}`
          : "Channel connected." });
      } else {
        setNotice({
          text: result.reason ?? "Channel connection failed.",
          error: true,
        });
      }
    } catch {
      setNotice({
        text: "Channel connection failed. No secret was retained by Worker.",
        error: true,
      });
    } finally {
      setBusy("");
    }
  }

  async function configureChannel(body: ConfigureChannelRequest) {
    if (!selected) return;
    invalidateExactApproval();
    invalidatePendingPairing();
    invalidatePendingDeliveryRetry();
    const mutation: ExactChannelMutation = {
      kind: "configure",
      channelId: selected.id,
      body,
    };
    setBusy("configure");
    setNotice(null);
    try {
      const result = await client.configureChannel(
        mutation.channelId, mutation.body,
      );
      if (exactApproval.begin(
        mutation, result, "Channel configuration",
      )) {
        setNotice({
          text: "Channel configuration is waiting for human approval in Inbox.",
        });
      } else if (result.status === "ok") {
        await refreshChannels(selected.id);
        setNotice({ text: "Channel settings saved." });
      } else {
        setNotice({
          text: result.reason ?? "Channel settings could not be saved.",
          error: true,
        });
      }
    } catch {
      setNotice({ text: "Channel settings could not be saved.", error: true });
    } finally {
      setBusy("");
    }
  }

  async function disconnectChannel() {
    if (!selected) return;
    if (!disconnectArmed) {
      invalidateExactApproval();
      invalidatePendingPairing();
      invalidatePendingDeliveryRetry();
      setDisconnectArmed(true);
      setNotice({ text: "Disconnecting removes the channel and its bindings. Confirm to continue." });
      return;
    }
    setBusy("disconnect");
    try {
      const mutation: ExactChannelMutation = {
        kind: "disconnect",
        channelId: selected.id,
      };
      const result = await client.disconnectChannel(mutation.channelId);
      if (exactApproval.begin(
        mutation, result, "Channel disconnect",
      )) {
        setNotice({
          text: "Channel disconnect is waiting for human approval in Inbox.",
        });
      } else if (result.status === "ok") {
        setBindings([]);
        setDeliveries([]);
        setSelectedId(null);
        setDisconnectArmed(false);
        await refreshChannels(null);
        setNotice({ text: "Channel disconnected." });
      } else {
        setNotice({
          text: result.reason ?? "Channel disconnect failed.",
          error: true,
        });
      }
    } catch {
      setNotice({ text: "Channel disconnect failed; no local state was changed.", error: true });
    } finally {
      setBusy("");
    }
  }

  async function submitBinding() {
    if (!selected) return;
    invalidateExactApproval();
    invalidatePendingPairing();
    const externalUserId = bindingDraft.externalUserId.trim();
    const subject = bindingDraft.subject.trim();
    if (!externalUserId || !subject) {
      setNotice({ text: "External user ID and Boltrig subject are required.", error: true });
      return;
    }
    setBusy(bindingMode);
    setNotice(null);
    const body: BindChannelRequest = {
      external_user_id: externalUserId,
      subject,
      role: bindingDraft.role,
    };
    try {
      if (bindingMode === "pair") {
        const result = await client.pairChannel(selected.id, {
          ...body,
          ttl_minutes: Math.max(1, Math.min(60, Number(bindingDraft.ttl) || 15)),
        });
        if (result.status === "ok" && result.code) {
          setPairingSecret({
            code: result.code,
            externalUserId,
            pairingId: result.pairing_id,
          });
          setBindingDraft(blankBinding);
          setNotice({ text: "Pairing issued. The code below is the only copy Boltrig returns." });
        } else if (result.status === "ok") {
          setNotice({
            text: "The pairing was acknowledged without a one-time code. Nothing can be displayed or recovered in Worker.",
            error: true,
          });
        } else if (result.status === "pending_human") {
          const pairBody: PairChannelRequest = {
            ...body,
            ttl_minutes: Math.max(
              1, Math.min(60, Number(bindingDraft.ttl) || 15),
            ),
          };
          setPendingPairing({
            channelId: selected.id,
            approvalId: result.hitl_request_id ?? "",
            body: pairBody,
            state: "waiting",
            invalidated: !result.hitl_request_id,
          });
          setPairFinalization(
            result.hitl_request_id ? "waiting" : "unavailable",
          );
          setNotice({
            text: "Pairing is waiting for approval. Finalize it here to receive the one-time code.",
          });
        } else {
          setNotice({
            text: result.reason ?? "The pairing was not issued.",
            error: true,
          });
        }
      } else {
        const mutation: ExactChannelMutation = {
          kind: "bind",
          channelId: selected.id,
          body,
        };
        const result = await client.bindChannel(
          mutation.channelId, mutation.body,
        );
        if (exactApproval.begin(
          mutation, result, "Sender binding",
        )) {
          setNotice({
            text: "Sender binding is waiting for human approval in Inbox.",
          });
        } else if (result.status === "ok") {
          setBindingDraft(blankBinding);
          await openChannel(selected);
          setNotice({ text: "Sender bound directly." });
        } else {
          setNotice({
            text: result.reason ?? "The sender was not bound.",
            error: true,
          });
        }
      }
    } catch {
      setNotice({ text: "The sender mapping was not changed.", error: true });
    } finally {
      setBusy("");
    }
  }

  async function copyPairingCode() {
    if (!pairingSecret) return;
    try {
      if (!navigator.clipboard) throw new Error("clipboard unavailable");
      await navigator.clipboard.writeText(pairingSecret.code);
      setNotice({ text: "Pairing code copied. Keep it in an approved secure channel." });
    } catch {
      setNotice({ text: "Clipboard access is unavailable. Select and copy the visible code manually.", error: true });
    }
  }

  async function finalizePairing() {
    const pending = pendingPairing;
    if (
      pending === null
      || pending.invalidated
      || selected?.id !== pending.channelId
    ) {
      setPairFinalization("invalidated");
      return;
    }
    setBusy("pair-finalize");
    setPairFinalization("checking");
    setNotice(null);
    try {
      const approval = await client.invokeApprovalState(pending.approvalId);
      if (approval.status === "pending") {
        setPairFinalization("waiting");
        return;
      }
      if (
        approval.status === "rejected"
        || approval.status === "expired"
        || approval.status === "consumed"
      ) {
        setPairFinalization(approval.status);
        return;
      }
      const result = await client.pairChannel(
        pending.channelId,
        pending.body,
        pending.approvalId,
      );
      if (result.status === "ok" && result.code) {
        setPairingSecret({
          code: result.code,
          externalUserId: pending.body.external_user_id,
          pairingId: result.pairing_id,
        });
        setBindingDraft(blankBinding);
        setPendingPairing(null);
        setPairFinalization(null);
        setNotice({
          text: "Approved pairing issued. This is the only copy of the code.",
        });
      } else if (result.status === "ok") {
        setPairFinalization("unavailable");
        setNotice({
          text: "The approved pairing completed without a one-time code. Nothing can be displayed or recovered.",
          error: true,
        });
      } else {
        setPairFinalization("invalidated");
        setNotice({
          text: result.reason ?? "The exact approved pairing was refused.",
          error: true,
        });
      }
    } catch {
      setPairFinalization("unavailable");
    } finally {
      setBusy("");
    }
  }

  async function deleteBinding(binding: ChannelBindingSummary) {
    if (!selected) return;
    if (deleteArmed !== binding.id) {
      invalidateExactApproval();
      invalidatePendingPairing();
      setDeleteArmed(binding.id);
      return;
    }
    setBusy(`delete:${binding.id}`);
    try {
      const mutation: ExactChannelMutation = {
        kind: "unbind",
        channelId: selected.id,
        bindingId: binding.id,
      };
      const result = await client.deleteChannelBinding(
        mutation.channelId, mutation.bindingId,
      );
      if (exactApproval.begin(
        mutation, result, "Sender unbind",
      )) {
        setNotice({
          text: "Sender unbind is waiting for human approval in Inbox.",
        });
      } else if (result.status === "ok") {
        setDeleteArmed(null);
        await openChannel(selected);
        setNotice({ text: "Binding removed." });
      } else {
        setNotice({
          text: result.reason ?? "Binding removal failed.",
          error: true,
        });
      }
    } catch {
      setNotice({ text: "Binding removal failed.", error: true });
    } finally {
      setBusy("");
    }
  }

  return (
    <div className="page">
      <Topbar
        title="Channels"
        status={surfaceState === "ready" ? `${channels.length} connected` : stateLabel(surfaceState)}
      />
      <div className="page-content">
        <div className="page-intro">
          <div>
            <h2>Administer intake channels</h2>
            <p>Connections, sender identity and one-time pairing stay behind Boltrig’s admin boundary. Worker never retrieves a stored signing secret.</p>
          </div>
          {surfaceState === "ready" && (
            <button className="primary-button" onClick={() => {
              invalidateExactApproval();
              invalidatePendingPairing();
              setCreating((value) => !value);
            }}>
              {creating ? "Close form" : "Connect channel"}
            </button>
          )}
        </div>
        {notice && <p className="notice channel-notice" role={notice.error ? "alert" : "status"}>{notice.text}</p>}
        <ExactApprovalFinalizer controller={exactApproval} />
        {surfaceState === "loading" && <Unavailable title="Loading channels">Checking your channel administration scope.</Unavailable>}
        {surfaceState === "denied" && <Unavailable title="Channel administration denied">Your current role cannot view or change channel configuration.</Unavailable>}
        {surfaceState === "unavailable" && <Unavailable title="Channels unavailable">The governed channel service could not be reached.</Unavailable>}
        {surfaceState === "ready" && creating && (
          <ConnectChannelForm
            addressingCatalogue={addressingCatalogue}
            busy={busy === "connect"}
            onCancel={() => {
              invalidateExactApproval();
              setCreating(false);
            }}
            onDraftChange={invalidateExactApproval}
            onSubmit={connectChannel}
          />
        )}
        {surfaceState === "ready" && (
          <div className={selected ? "split-view detail-open" : "split-view"}>
            <section className="data-list" aria-label="Connected channels">
              {channels.length === 0
                ? <Unavailable title="No channels connected">Connect a signed webhook, Teams-labelled webhook, or voice channel to begin.</Unavailable>
                : channels.map((channel) => (
                  <button
                    className={selectedId === channel.id ? "data-row selected" : "data-row"}
                    key={channel.id}
                    onClick={() => void openChannel(channel)}
                  >
                    <span className={`activity-dot ${channel.enabled ? "ok" : "paused"}`} />
                    <span className="data-row-copy">
                      <strong>{channel.name}</strong>
                      <small>{channel.provider?.label ?? channel.platform} · {channel.transport}</small>
                    </span>
                    <span className="row-meta">
                      {!channel.enabled ? "disabled" : channel.gateway?.status ?? "enabled"}
                    </span>
                  </button>
                ))}
            </section>
            {selected && (
              <ChannelDetail
                channel={selected}
                addressingCatalogue={addressingCatalogue}
                bindings={bindings}
                bindingState={bindingState}
                deliveries={deliveries}
                deliveryState={deliveryState}
                deliveryFinalization={deliveryFinalization}
                pairFinalization={pairFinalization}
                pendingPairing={pendingPairing}
                bindingMode={bindingMode}
                bindingDraft={bindingDraft}
                pairingSecret={pairingSecret}
                busy={busy}
                disconnectArmed={disconnectArmed}
                deleteArmed={deleteArmed}
                onClose={closeChannel}
                onConfigure={(body) => void configureChannel(body)}
                onDisconnect={() => void disconnectChannel()}
                onMode={(mode) => {
                  invalidateExactApproval();
                  invalidatePendingPairing();
                  setBindingMode(mode);
                }}
                onBindingDraft={(value) => {
                  invalidateExactApproval();
                  invalidatePendingPairing();
                  setBindingDraft(value);
                }}
                onSubmitBinding={() => void submitBinding()}
                onCopySecret={() => void copyPairingCode()}
                onDismissSecret={() => setPairingSecret(null)}
                onDeleteBinding={(binding) => void deleteBinding(binding)}
                onRetryDelivery={(delivery) => void retryDelivery(delivery)}
                onFinalizeDeliveryRetry={() => void finalizeDeliveryRetry()}
                onFinalizePairing={() => void finalizePairing()}
                onDraftChange={() => {
                  invalidateExactApproval();
                  invalidatePendingPairing();
                  invalidatePendingDeliveryRetry();
                }}
              />
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function normalizeChannelResult<T extends GovernedResult>(
  result: T,
): ExactChannelResult {
  return {
    status: result.status,
    hitl_request_id: result.hitl_request_id,
    reason: result.reason,
    value: result as ExactChannelResult["value"],
  };
}

function normalizeSendResult(result: InvokeResult): ChannelSendFinalResult {
  return {
    status: result.status,
    hitl_request_id: result.status === "pending_human"
      ? result.hitl_request_id
      : undefined,
    reason: "reason" in result ? result.reason : undefined,
    value: result,
  };
}

function routeInputEquals(left: unknown, right: unknown): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}

function bindingRequest(draft: BindingDraft): BindChannelRequest {
  return {
    external_user_id: draft.externalUserId.trim(),
    subject: draft.subject.trim(),
    role: draft.role,
  };
}

function stateLabel(state: SurfaceState) {
  if (state === "loading") return "Checking access";
  if (state === "denied") return "Admin only";
  if (state === "unavailable") return "Unavailable";
  return "";
}

function configuredDefaultTarget(
  config: Record<string, unknown>,
): string | null {
  const addressing = config.addressing;
  if (!addressing || typeof addressing !== "object" || Array.isArray(addressing)) {
    return null;
  }
  const target = (addressing as Record<string, unknown>).default_target;
  return typeof target === "string" && target ? target : null;
}

function objectValue(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function policyFromText(config: string): Record<string, unknown> | null {
  try {
    return objectValue(JSON.parse(config));
  } catch {
    return null;
  }
}

function configuredDefaultTargetText(config: string): string | null {
  const parsed = policyFromText(config);
  return parsed ? configuredDefaultTarget(parsed) : null;
}

function targetLabel(target: ChannelAddressingTarget): string {
  const kind = target.kind === "chief"
    ? "Chief"
    : target.kind === "department"
      ? "Department"
      : "Workflow";
  const state = target.state === "restart_required"
    ? " · restart required"
    : target.state === "startup_constructed_liveness_unknown"
      ? " · liveness unknown"
      : "";
  return `${kind} · ${target.label}${state}`;
}

interface ConnectChannelFormProps {
  addressingCatalogue: ChannelAddressingCatalogue;
  busy: boolean;
  onCancel(): void;
  onDraftChange(): void;
  onSubmit(body: ConnectChannelRequest): Promise<void>;
}

function ConnectChannelForm({
  addressingCatalogue,
  busy,
  onCancel,
  onDraftChange,
  onSubmit,
}: ConnectChannelFormProps) {
  const [platform, setPlatform] = useState("webhook");
  const [name, setName] = useState("");
  const [secretRef, setSecretRef] = useState("");
  const [credentialRefs, setCredentialRefs] = useState<Record<string, string>>({});
  const [account, setAccount] = useState("");
  const [unpairedBehavior, setUnpairedBehavior] = useState("reject");
  const [defaultTarget, setDefaultTarget] = useState("cos");
  const provider = channelProviders[platform as keyof typeof channelProviders];
  return (
    <form
      className="admin-form"
      aria-label="Connect channel"
      onSubmit={(event) => {
        event.preventDefault();
        const refs = Object.fromEntries(
          provider.credentials.map((key) => [
            key,
            key === "signing" ? secretRef.trim() : (credentialRefs[key] ?? "").trim(),
          ]).filter(([, value]) => value),
        );
        if (
          !name.trim()
          || provider.credentials.some((key) => !refs[key])
          || (platform === "signal" && !account.trim())
        ) return;
        void onSubmit({
          platform,
          name: name.trim(),
          ...(platform === "webhook" || platform === "msteams"
            ? { signing_secret_ref: refs.signing }
            : { credential_refs: refs }),
          ...(platform === "signal"
            ? { provider_config: { account: account.trim() } }
            : {}),
          unpaired_behavior: unpairedBehavior,
          enabled: true,
          ...(defaultTarget === "cos"
            ? {}
            : {
              config: {
                addressing: { default_target: defaultTarget },
              },
            }),
        });
      }}
    >
      <div className="admin-form-heading">
        <div><p className="eyebrow">New connection</p><h3>Connect a channel</h3></div>
        <button className="icon-button" type="button" aria-label="Close channel form" onClick={onCancel}>×</button>
      </div>
      <div className="admin-fields three">
        <label><span>Platform</span><select className="field-control" value={platform} onChange={(event) => { onDraftChange(); setPlatform(event.target.value); }}>{Object.entries(channelProviders).map(([id, definition]) => <option key={id} value={id}>{definition.label}</option>)}</select></label>
        <label><span>Channel name</span><input className="field-control" required value={name} onChange={(event) => { onDraftChange(); setName(event.target.value); }} /></label>
        <label><span>Unknown senders</span><select className="field-control" value={unpairedBehavior} onChange={(event) => { onDraftChange(); setUnpairedBehavior(event.target.value); }}><option value="reject">Reject</option><option value="pair">Allow pairing code</option></select></label>
        <label>
          <span>Initial default target</span>
          <select
            className="field-control"
            value={defaultTarget}
            onChange={(event) => {
              onDraftChange();
              setDefaultTarget(event.target.value);
            }}
          >
            {addressingCatalogue.targets.map((target) => (
              <option key={target.id} value={target.id}>
                {targetLabel(target)}
              </option>
            ))}
          </select>
        </label>
      </div>
      {platform === "msteams" && (
        <p className="notice">
          This uses Boltrig&apos;s generic HMAC-signed webhook contract. It is not
          a Microsoft Graph, Teams app, bot, or OAuth connection.
        </p>
      )}
      {(platform === "signal" || platform === "whatsapp") && (
        <p className="notice">
          Boltrig can author and reconcile this channel, but device/account
          pairing remains an external operator action. Worker will show
          <strong> needs action</strong> until the gateway reports evidence.
        </p>
      )}
      {platform === "generic" && (
        <p className="notice">
          The generic adapter is shipped but its listener topology is
          deployment-managed, not tenant-authored in Worker.
        </p>
      )}
      <label className="admin-secret-field"><span>Signing-secret reference</span><input className="field-control" required value={secretRef} onChange={(event) => { onDraftChange(); setSecretRef(event.target.value); }} placeholder="BOLTRIG_CHANNEL_SIGNING_SECRET" /><small>Name a secret in the configured store. Worker never receives the secret material.</small></label>
      {provider.credentials.filter((key) => key !== "signing").map((key) => (
        <label className="admin-secret-field" key={key}>
          <span>{key.replaceAll("_", " ")} reference</span>
          <input
            className="field-control"
            required
            value={credentialRefs[key] ?? ""}
            onChange={(event) => {
              onDraftChange();
              setCredentialRefs({ ...credentialRefs, [key]: event.target.value });
            }}
            placeholder={`BOLTRIG_${platform.toUpperCase()}_${key.toUpperCase()}`}
          />
          <small>Write-only secret-store name; material never enters Worker.</small>
        </label>
      ))}
      {platform === "signal" && (
        <label><span>Signal account (E.164)</span><input className="field-control" required value={account} onChange={(event) => { onDraftChange(); setAccount(event.target.value); }} placeholder="+15551234567" /></label>
      )}
      <div className="inline-actions">
        <button className="primary-button" type="submit" disabled={busy || !name.trim()}>{busy ? "Connecting…" : "Connect"}</button>
        <button className="secondary-button" type="button" disabled={busy} onClick={onCancel}>Cancel</button>
      </div>
    </form>
  );
}

interface ChannelDetailProps {
  channel: ChannelSummary;
  addressingCatalogue: ChannelAddressingCatalogue;
  bindings: ChannelBindingSummary[];
  bindingState: SurfaceState;
  deliveries: ChannelDeliveryReceipt[];
  deliveryState: SurfaceState;
  deliveryFinalization: DeliveryFinalizationState;
  pairFinalization: PairFinalizationState;
  pendingPairing: PendingPairingFinalization | null;
  bindingMode: BindingMode;
  bindingDraft: BindingDraft;
  pairingSecret: { code: string; externalUserId: string; pairingId?: string } | null;
  busy: string;
  disconnectArmed: boolean;
  deleteArmed: string | null;
  onClose(): void;
  onConfigure(body: { name: string; enabled: boolean; unpaired_behavior: string; config: Record<string, unknown>; credential_refs?: Record<string, string> }): void;
  onDisconnect(): void;
  onMode(mode: BindingMode): void;
  onBindingDraft(draft: BindingDraft): void;
  onSubmitBinding(): void;
  onCopySecret(): void;
  onDismissSecret(): void;
  onDeleteBinding(binding: ChannelBindingSummary): void;
  onRetryDelivery(delivery: ChannelDeliveryReceipt): void;
  onFinalizeDeliveryRetry(): void;
  onFinalizePairing(): void;
  onDraftChange(): void;
}

function ChannelDetail(props: ChannelDetailProps) {
  const [name, setName] = useState(props.channel.name);
  const [enabled, setEnabled] = useState(props.channel.enabled);
  const [unpairedBehavior, setUnpairedBehavior] = useState(props.channel.unpaired_behavior);
  const [config, setConfig] = useState(JSON.stringify(props.channel.config, null, 2));
  const [configError, setConfigError] = useState("");
  const [credentialRefs, setCredentialRefs] = useState<Record<string, string>>({});
  const policyDraft = policyFromText(config);
  const addressingDraft = objectValue(policyDraft?.addressing);
  const routeDrafts = Object.entries(objectValue(addressingDraft?.routes) ?? {})
    .map(([thread, target]) => ({
      thread,
      target: typeof target === "string" ? target : "",
    }));
  const onboardingDraft = objectValue(policyDraft?.self_onboard);
  const onboardingScope = objectValue(onboardingDraft?.scope);
  const onboardingDepartments = Array.isArray(onboardingScope?.departments)
    ? onboardingScope.departments.filter(
      (department): department is string => typeof department === "string",
    )
    : [];
  const departmentTargets = props.addressingCatalogue.targets.filter(
    (target) => target.kind === "department",
  );
  const knownDepartmentIds = new Set(
    departmentTargets.map((target) => target.id),
  );
  const staleOnboardingDepartments = onboardingDepartments.filter(
    (department) => !knownDepartmentIds.has(department),
  );
  const onboardingScopeUnsupported = Boolean(
    onboardingScope
    && Object.keys(onboardingScope).some((key) => key !== "departments")
  );
  const savedEffectiveTarget = (
    props.channel.addressing?.effective_default_target
    ?? configuredDefaultTarget(props.channel.config)
    ?? "cos"
  );
  const effectiveTarget =
    configuredDefaultTargetText(config) ?? savedEffectiveTarget;
  const targetKnown = props.addressingCatalogue.targets.some(
    (target) => target.id === effectiveTarget,
  );
  const selectedTarget = props.addressingCatalogue.targets.find(
    (target) => target.id === effectiveTarget,
  );
  const routeWarnings = routeDrafts.filter(
    (route) => (
      !route.thread.trim()
      || !props.addressingCatalogue.targets.some(
        (target) => target.id === route.target,
      )
    ),
  ).length;

  function updatePolicy(mutator: (policy: Record<string, unknown>) => void) {
    props.onDraftChange();
    try {
      const parsed: unknown = JSON.parse(config);
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        throw new Error("object required");
      }
      const next = parsed as Record<string, unknown>;
      mutator(next);
      setConfig(JSON.stringify(next, null, 2));
      setConfigError("");
    } catch {
      setConfigError(
        "Repair the channel policy JSON before changing its default target.",
      );
    }
  }

  function setDefaultTarget(target: string) {
    updatePolicy((policy) => {
      policy.addressing = {
        ...(objectValue(policy.addressing) ?? {}),
        default_target: target,
      };
    });
  }

  function setRoute(
    index: number,
    field: "thread" | "target",
    value: string,
  ) {
    if (
      field === "thread"
      && routeDrafts.some(
        (route, routeIndex) => routeIndex !== index && route.thread === value,
      )
    ) {
      setConfigError("Thread or chat keys must be unique.");
      return;
    }
    updatePolicy((policy) => {
      const addressing = objectValue(policy.addressing) ?? {};
      const routes = Object.entries(objectValue(addressing.routes) ?? {})
        .map(([thread, target]) => ({
          thread,
          target: typeof target === "string" ? target : "",
        }));
      routes[index] = { ...routes[index], [field]: value };
      policy.addressing = {
        ...addressing,
        routes: Object.fromEntries(
          routes.map((route) => [route.thread, route.target]),
        ),
      };
    });
  }

  function addRoute() {
    updatePolicy((policy) => {
      const addressing = objectValue(policy.addressing) ?? {};
      const routes = objectValue(addressing.routes) ?? {};
      if ("" in routes) return;
      policy.addressing = {
        ...addressing,
        routes: { ...routes, "": "cos" },
      };
    });
  }

  function removeRoute(index: number) {
    updatePolicy((policy) => {
      const addressing = objectValue(policy.addressing) ?? {};
      const routes = Object.entries(objectValue(addressing.routes) ?? {});
      routes.splice(index, 1);
      policy.addressing = {
        ...addressing,
        routes: Object.fromEntries(routes),
      };
    });
  }

  function setOnboardingEnabled(enabled: boolean) {
    updatePolicy((policy) => {
      if (!enabled) {
        delete policy.self_onboard;
        return;
      }
      const existing = objectValue(policy.self_onboard) ?? {};
      const scope = objectValue(existing.scope);
      policy.self_onboard = {
        ...existing,
        role: "member",
        scope: {
          departments: Array.isArray(scope?.departments)
            ? scope.departments.filter(
              (department): department is string => (
                typeof department === "string"
                && knownDepartmentIds.has(department)
              ),
            )
            : [],
        },
        welcome: typeof existing.welcome === "string"
          ? existing.welcome
          : "",
      };
    });
  }

  function setOnboardingRole(role: string) {
    updatePolicy((policy) => {
      const existing = objectValue(policy.self_onboard) ?? {};
      policy.self_onboard = { ...existing, role };
    });
  }

  function setOnboardingWelcome(welcome: string) {
    updatePolicy((policy) => {
      const existing = objectValue(policy.self_onboard) ?? {};
      policy.self_onboard = { ...existing, welcome };
    });
  }

  function setOnboardingDepartment(department: string, enabled: boolean) {
    updatePolicy((policy) => {
      const existing = objectValue(policy.self_onboard) ?? {};
      const scope = objectValue(existing.scope) ?? {};
      const current = new Set(
        Array.isArray(scope.departments)
          ? scope.departments.filter(
            (item): item is string => typeof item === "string",
          )
          : [],
      );
      if (enabled) current.add(department);
      else current.delete(department);
      policy.self_onboard = {
        ...existing,
        role: "member",
        scope: { departments: [...current].sort() },
      };
    });
  }
  useEffect(() => {
    setName(props.channel.name);
    setEnabled(props.channel.enabled);
    setUnpairedBehavior(props.channel.unpaired_behavior);
    setConfig(JSON.stringify(props.channel.config, null, 2));
    setConfigError("");
    setCredentialRefs({});
  }, [props.channel]);

  return (
    <aside className="detail-panel channel-detail" aria-label={`${props.channel.name} administration`}>
      <div className="detail-heading">
        <div><p className="eyebrow">Channel</p><h3>{props.channel.name}</h3></div>
        <button className="icon-button" aria-label="Close channel details" onClick={props.onClose}>×</button>
      </div>
      <dl className="fact-grid">
        <div><dt>Platform</dt><dd>{props.channel.platform}</dd></div>
        <div><dt>Transport</dt><dd>{props.channel.transport}</dd></div>
        <div><dt>Channel ID</dt><dd>{props.channel.id}</dd></div>
        <div><dt>Bindings</dt><dd>{props.bindingState === "ready" ? props.bindings.length : stateLabel(props.bindingState)}</dd></div>
        <div><dt>Desired credentials</dt><dd>{props.channel.credential_configured ? "references complete" : "incomplete"}</dd></div>
        <div><dt>Gateway evidence</dt><dd>{props.channel.gateway?.status ?? "not observed"}</dd></div>
      </dl>
      {props.channel.gateway?.reason_code && (
        <p className="notice">
          Gateway state: {props.channel.gateway.reason_code.replaceAll("_", " ")}.
          A shipped adapter is not proof of live delivery.
        </p>
      )}
      {props.channel.transport === "socket" && (
        <GatewaySessionRecovery
          key={props.channel.id}
          channel={props.channel}
        />
      )}
      <form className="detail-section admin-form compact" aria-label="Configure channel" onSubmit={(event) => {
        event.preventDefault();
        try {
          const parsed: unknown = JSON.parse(config);
          if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
            throw new Error("object required");
          }
          setConfigError("");
          props.onConfigure({
            name: name.trim(),
            enabled,
            unpaired_behavior: unpairedBehavior,
            config: parsed as Record<string, unknown>,
            ...(Object.values(credentialRefs).some((value) => value.trim())
              ? {
                credential_refs: Object.fromEntries(
                  Object.entries(credentialRefs)
                    .filter(([, value]) => value.trim())
                    .map(([key, value]) => [key, value.trim()]),
                ),
              }
              : {}),
          });
        } catch {
          setConfigError("Channel policy must be a JSON object.");
        }
      }}>
        <p className="eyebrow">Configuration</p>
        <label><span>Name</span><input className="field-control" required value={name} onChange={(event) => { props.onDraftChange(); setName(event.target.value); }} /></label>
        <label><span>Unknown senders</span><select className="field-control" value={unpairedBehavior} onChange={(event) => { props.onDraftChange(); setUnpairedBehavior(event.target.value); }}><option value="reject">Reject</option><option value="pair">Allow pairing code</option></select></label>
        <label>
          <span>Default target</span>
          <select
            className="field-control"
            value={effectiveTarget}
            onChange={(event) => setDefaultTarget(event.target.value)}
          >
            {!targetKnown && (
              <option value={effectiveTarget}>
                Unsupported or stale · {effectiveTarget}
              </option>
            )}
            {props.addressingCatalogue.targets.map((target) => (
              <option key={target.id} value={target.id}>
                {targetLabel(target)}
              </option>
            ))}
          </select>
          <small>
            Backend-scoped permanent departments and active workflows only.
            Arbitrary agent or capability pinning is not supported.
          </small>
        </label>
        {!targetKnown && (
          <p className="notice" role="alert">
            The configured default target is stale or unsupported. Choose a
            listed target before saving.
          </p>
        )}
        {selectedTarget?.state === "restart_required" && (
          <p className="notice">
            This permanent department is desired but awaits a worker restart;
            runtime liveness is not claimed.
          </p>
        )}
        {routeWarnings > 0 && (
          <p className="notice" role="alert">
            {routeWarnings} thread route{routeWarnings === 1 ? "" : "s"} need
            {routeWarnings === 1 ? "s" : ""} repair: each key must be non-empty
            and each target must be supported.
          </p>
        )}
        <fieldset className="detail-section route-editor">
          <legend>Thread routes</legend>
          <p className="muted small">
            Pin an exact external chat or thread key to one supported target.
          </p>
          {routeDrafts.map((route, index) => {
            const known = props.addressingCatalogue.targets.some(
              (target) => target.id === route.target,
            );
            return (
              <div className="admin-fields three" key={index}>
                <label>
                  <span>{`Thread or chat key ${index + 1}`}</span>
                  <input
                    className="field-control"
                    value={route.thread}
                    onChange={(event) => setRoute(
                      index, "thread", event.target.value,
                    )}
                  />
                </label>
                <label>
                  <span>{`Route target ${index + 1}`}</span>
                  <select
                    className="field-control"
                    value={route.target}
                    onChange={(event) => setRoute(
                      index, "target", event.target.value,
                    )}
                  >
                    {!known && (
                      <option value={route.target}>
                        Unsupported or stale · {route.target || "empty"}
                      </option>
                    )}
                    {props.addressingCatalogue.targets.map((target) => (
                      <option key={target.id} value={target.id}>
                        {targetLabel(target)}
                      </option>
                    ))}
                  </select>
                </label>
                <button
                  className="secondary-button"
                  type="button"
                  onClick={() => removeRoute(index)}
                >
                  {`Remove route ${index + 1}`}
                </button>
              </div>
            );
          })}
          {routeDrafts.length === 0 && (
            <p className="muted small">No thread-specific routes.</p>
          )}
          <button
            className="secondary-button"
            type="button"
            onClick={addRoute}
          >
            Add thread route
          </button>
        </fieldset>
        <fieldset className="detail-section onboarding-editor">
          <legend>Constrained self-onboarding</legend>
          <label className="check-field">
            <input
              type="checkbox"
              checked={onboardingDraft !== null}
              onChange={(event) => setOnboardingEnabled(event.target.checked)}
            />
            <span>Enable constrained self-onboarding</span>
          </label>
          {onboardingDraft && (
            <>
              <label>
                <span>Onboarded role</span>
                <select
                  className="field-control"
                  value={typeof onboardingDraft.role === "string"
                    ? onboardingDraft.role
                    : "member"}
                  onChange={(event) => setOnboardingRole(event.target.value)}
                >
                  {onboardingDraft.role !== "member" && (
                    <option value={String(onboardingDraft.role ?? "")}>
                      Unsupported role · {String(onboardingDraft.role ?? "empty")}
                    </option>
                  )}
                  <option value="member">Member (maximum)</option>
                </select>
              </label>
              {onboardingDraft.role !== "member" && (
                <p className="notice" role="alert">
                  Self-onboarding is fail-closed until its role is Member.
                </p>
              )}
              <fieldset>
                <legend>Visible departments</legend>
                {departmentTargets.length === 0 && (
                  <p className="muted small">
                    No departments are available in your current scope.
                  </p>
                )}
                {departmentTargets.map((target) => (
                  <label className="check-field" key={target.id}>
                    <input
                      type="checkbox"
                      checked={onboardingDepartments.includes(target.id)}
                      onChange={(event) => setOnboardingDepartment(
                        target.id, event.target.checked,
                      )}
                    />
                    <span>{target.label}</span>
                  </label>
                ))}
                {staleOnboardingDepartments.map((department) => (
                  <label className="check-field" key={department}>
                    <input
                      type="checkbox"
                      checked
                      onChange={() => setOnboardingDepartment(
                        department, false,
                      )}
                    />
                    <span>Unavailable department · {department}</span>
                  </label>
                ))}
              </fieldset>
              {onboardingScopeUnsupported && (
                <p className="notice" role="alert">
                  The saved onboarding scope contains unsupported fields.
                  Selecting a department repairs it to the bounded department
                  scope.
                </p>
              )}
              <label>
                <span>Welcome message</span>
                <textarea
                  className="field-control"
                  rows={3}
                  maxLength={2000}
                  value={typeof onboardingDraft.welcome === "string"
                    ? onboardingDraft.welcome
                    : ""}
                  onChange={(event) => setOnboardingWelcome(event.target.value)}
                />
              </label>
              <small>
                Unknown verified senders receive only the Member ceiling;
                selected departments narrow visibility and never add grants.
              </small>
            </>
          )}
        </fieldset>
        <label><span>Routing and onboarding policy (complete JSON)</span><textarea className="field-control code-field" rows={8} value={config} onChange={(event) => { props.onDraftChange(); setConfig(event.target.value); }} /></label>
        <p className="muted small">The advanced JSON stays synchronized with the typed controls and preserves unrelated legacy policy fields. Saving replaces this complete non-secret policy; the backend validates every consumed target and onboarding authority field.</p>
        {(props.channel.provider?.credential_keys ?? []).map((key) => (
          <label className="admin-secret-field" key={key}>
            <span>Rotate {key.replaceAll("_", " ")} reference</span>
            <input className="field-control" value={credentialRefs[key] ?? ""} onChange={(event) => { props.onDraftChange(); setCredentialRefs({ ...credentialRefs, [key]: event.target.value }); }} placeholder="Leave blank to keep the current reference" />
          </label>
        ))}
        {configError && <p className="notice" role="alert">{configError}</p>}
        <label className="check-field"><input type="checkbox" checked={enabled} onChange={(event) => { props.onDraftChange(); setEnabled(event.target.checked); }} /><span>Channel enabled</span></label>
        <button className="secondary-button" disabled={props.busy !== "" || !name.trim()}>Save settings</button>
      </form>
      <ChannelSendTest channel={props.channel} />
      <section className="detail-section" aria-label="Outbound delivery receipts">
        <div className="section-heading">
          <p className="eyebrow">Outbound deliveries</p>
          <span className="row-meta">
            {props.deliveryState === "ready"
              ? `${props.deliveries.length} recent`
              : stateLabel(props.deliveryState)}
          </span>
        </div>
        <p className="muted small">
          Bounded delivery receipts contain no message body, destination,
          credential, gateway token or lease owner. Retry is available only for
          an exact terminal failure after channel configuration has been repaired.
        </p>
        {props.deliveryFinalization && (
          <div
            className={`notice delivery-finalization ${props.deliveryFinalization}`}
            role="status"
          >
            <strong>{deliveryFinalizationCopy(props.deliveryFinalization)[0]}</strong>
            <p>{deliveryFinalizationCopy(props.deliveryFinalization)[1]}</p>
            {(props.deliveryFinalization === "waiting"
              || props.deliveryFinalization === "unavailable") && (
              <button
                className="secondary-button"
                disabled={props.busy !== ""}
                onClick={props.onFinalizeDeliveryRetry}
              >
                Check approval and continue exact retry
              </button>
            )}
          </div>
        )}
        {props.deliveryState === "loading" && <p className="muted small" role="status">Loading delivery receipts…</p>}
        {props.deliveryState === "denied" && <p className="muted small">Delivery receipt access denied.</p>}
        {props.deliveryState === "unavailable" && <p className="muted small">Delivery receipts could not be loaded.</p>}
        {props.deliveryState === "ready" && props.deliveries.length === 0 && (
          <p className="muted small">No outbound delivery receipts for this channel.</p>
        )}
        {props.deliveries.map((delivery) => (
          <div className="binding-row" key={delivery.id}>
            <span>
              <strong>{deliveryStatusLabel(delivery.status)}</strong>
              <small>
                {delivery.id} · {delivery.attempts} attempt{delivery.attempts === 1 ? "" : "s"}
                {delivery.updated_at ? ` · updated ${formatDeliveryTime(delivery.updated_at)}` : ""}
              </small>
              {delivery.status === "retryable" && delivery.next_attempt_at && (
                <small>Automatic retry after {formatDeliveryTime(delivery.next_attempt_at)}</small>
              )}
              {delivery.safe_reason && <small>Reason: delivery failed</small>}
            </span>
            {delivery.status === "terminal_failed" && delivery.updated_at && (
              <button
                className="secondary-button"
                disabled={props.busy !== ""}
                onClick={() => props.onRetryDelivery(delivery)}
              >
                {props.busy === `retry:${delivery.id}` ? "Requesting…" : "Request retry"}
              </button>
            )}
          </div>
        ))}
      </section>
      <section className="detail-section">
        <div className="section-heading"><p className="eyebrow">Sender bindings</p><span className="row-meta">{props.bindings.length}</span></div>
        {props.bindingState === "loading" && <p className="muted small" role="status">Loading bindings…</p>}
        {props.bindingState === "denied" && <p className="muted small">Binding administration denied.</p>}
        {props.bindingState === "unavailable" && <p className="muted small">Bindings could not be loaded.</p>}
        {props.bindings.map((binding) => (
          <div className="binding-row" key={binding.id}>
            <span><strong>{binding.external_user_id}</strong><small>{binding.subject} · {binding.role}</small></span>
            <button
              className={props.deleteArmed === binding.id ? "danger-button armed" : "danger-button"}
              disabled={props.busy !== ""}
              onClick={() => props.onDeleteBinding(binding)}
            >
              {props.deleteArmed === binding.id ? "Confirm remove" : "Remove"}
            </button>
          </div>
        ))}
        {props.bindingState === "ready" && props.bindings.length === 0 && <p className="muted small">No sender identities are bound.</p>}
      </section>
      {props.pairFinalization && props.pendingPairing && (
        <section
          className={`notice pair-finalization ${props.pairFinalization}`}
          role="status"
        >
          <strong>
            {pairFinalizationCopy(props.pairFinalization)[0]}
          </strong>
          <p>{pairFinalizationCopy(props.pairFinalization)[1]}</p>
          <small>
            {props.pendingPairing.body.external_user_id}
            {" → "}
            {props.pendingPairing.body.subject}
            {` · ${props.pendingPairing.body.role}`}
          </small>
          {(props.pairFinalization === "waiting"
            || props.pairFinalization === "ready"
            || props.pairFinalization === "unavailable") && (
            <button
              className="secondary-button"
              disabled={props.busy !== ""}
              onClick={props.onFinalizePairing}
            >
              Check approval and issue one-time code
            </button>
          )}
        </section>
      )}
      {props.pairingSecret ? (
        <section className="secret-once" aria-label="One-time pairing code">
          <p className="eyebrow">Shown once</p>
          <strong>Copy this pairing code now</strong>
          <code>{props.pairingSecret.code}</code>
          <p>For external sender {props.pairingSecret.externalUserId}. Boltrig will not show this code again after you close it.</p>
          <div className="inline-actions">
            <button className="secondary-button" onClick={props.onCopySecret}>Copy code</button>
            <button className="primary-button" onClick={props.onDismissSecret}>I have saved it</button>
          </div>
        </section>
      ) : (
        <form className="detail-section admin-form compact" aria-label="Add sender mapping" onSubmit={(event) => { event.preventDefault(); props.onSubmitBinding(); }}>
          <div className="tabs compact" role="group" aria-label="Sender mapping method">
            <button type="button" className={props.bindingMode === "pair" ? "active" : ""} aria-pressed={props.bindingMode === "pair"} onClick={() => props.onMode("pair")}>Pairing code</button>
            <button type="button" className={props.bindingMode === "bind" ? "active" : ""} aria-pressed={props.bindingMode === "bind"} onClick={() => props.onMode("bind")}>Direct bind</button>
          </div>
          <label><span>External user ID</span><input className="field-control" required value={props.bindingDraft.externalUserId} onChange={(event) => props.onBindingDraft({ ...props.bindingDraft, externalUserId: event.target.value })} /></label>
          <label><span>Boltrig subject</span><input className="field-control" required value={props.bindingDraft.subject} onChange={(event) => props.onBindingDraft({ ...props.bindingDraft, subject: event.target.value })} /></label>
          <div className="admin-fields">
            <label><span>Role</span><select className="field-control" value={props.bindingDraft.role} onChange={(event) => props.onBindingDraft({ ...props.bindingDraft, role: event.target.value })}><option value="member">Member</option><option value="admin">Admin</option><option value="superadmin">Superadmin</option></select></label>
            {props.bindingMode === "pair" && <label><span>Expires in minutes</span><input className="field-control" type="number" min="1" max="60" value={props.bindingDraft.ttl} onChange={(event) => props.onBindingDraft({ ...props.bindingDraft, ttl: event.target.value })} /></label>}
          </div>
          <button className="secondary-button" disabled={props.busy !== ""}>{props.bindingMode === "pair" ? "Issue one-time code" : "Bind sender"}</button>
        </form>
      )}
      <button className={props.disconnectArmed ? "danger-button armed" : "danger-button"} disabled={props.busy !== ""} onClick={props.onDisconnect}>
        {props.disconnectArmed ? "Confirm disconnect" : "Disconnect channel"}
      </button>
    </aside>
  );
}

function GatewaySessionRecovery({
  channel,
}: {
  channel: ChannelSummary;
}) {
  const [token, setToken] = useState("");
  const [expiresIn, setExpiresIn] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  async function issue() {
    setBusy(true);
    setToken("");
    setExpiresIn(null);
    setMessage("");
    try {
      const result = await client.channelGatewaySession({
        channels: [channel.id],
        gateway_id: "channel-gateway",
      });
      if (result.status !== "ok" || !result.token) {
        setMessage(
          result.reason ?? "A gateway session token could not be issued.",
        );
        return;
      }
      setToken(result.token);
      setExpiresIn(result.expires_in ?? null);
      setMessage(
        "Copy this token now. Boltrig stores only its in-memory digest and will not show it again.",
      );
    } catch {
      setMessage("Gateway session recovery is unavailable.");
    } finally {
      setBusy(false);
    }
  }

  async function copyToken() {
    setMessage(await copySensitiveText(token)
      ? "Gateway token copied to the clipboard. Replace the mounted secret before dismissing it."
      : "The gateway token could not be copied. Select and copy it manually before dismissing it.");
  }

  return (
    <section className="detail-section" aria-label="Gateway token recovery">
      <p className="eyebrow">Gateway recovery</p>
      <h4>Single-owner session</h4>
      <p className="muted small">
        Issue a no-verb, channel-scoped token for the severed gateway. A durable
        per-channel lease elects one owner before provider credentials,
        heartbeat or outbox work cross the kernel link. Lease evidence is not
        process liveness.
      </p>
      <p className="muted small">
        Ownership: {channel.gateway?.ownership?.status.replaceAll("_", " ")
          ?? "unclaimed"}
        {channel.gateway?.ownership?.lease_expires_at
          ? ` · lease until ${formatDeliveryTime(
            channel.gateway.ownership.lease_expires_at,
          )}`
          : ""}
      </p>
      <button
        className="secondary-button"
        disabled={busy || !channel.enabled}
        onClick={() => void issue()}
      >
        {busy ? "Issuing…" : "Issue replacement gateway token"}
      </button>
      {token && (
        <div className="approval-item" role="status">
          <strong>One-time gateway token</strong>
          <code>{token}</code>
          <p className="muted small">
            {expiresIn ? `Expires in ${expiresIn} seconds. ` : ""}
            Replace the mounted token file for hot recovery, or replace the
            environment token and restart the gateway. Stop the old owner and
            allow its bounded lease to expire before takeover.
          </p>
          <div className="button-row">
            <button
              className="secondary-button"
              onClick={() => void copyToken()}
            >
              Copy token
            </button>
            <button
              className="secondary-button"
              onClick={() => setToken("")}
            >
              I have saved it
            </button>
          </div>
        </div>
      )}
      {message && <p className="notice" role="status">{message}</p>}
    </section>
  );
}

function deliveryStatusLabel(status: ChannelDeliveryReceipt["status"]) {
  if (status === "queued") return "Queued";
  if (status === "in_flight") return "In flight";
  if (status === "retryable") return "Retry scheduled";
  if (status === "delivered") return "Delivered";
  return "Terminal failure";
}

function pairFinalizationCopy(
  state: Exclude<PairFinalizationState, null>,
): [string, string] {
  if (state === "waiting") {
    return [
      "Pairing is waiting for approval",
      "The pairing code does not exist yet. After an independent decision, finalize only this requester-owned intent.",
    ];
  }
  if (state === "ready") {
    return [
      "Approved pairing is ready",
      "Finalization creates and returns the one-time code exactly once.",
    ];
  }
  if (state === "checking") {
    return [
      "Checking pairing approval…",
      "No pairing code is generated until the kernel confirms approval.",
    ];
  }
  if (state === "rejected") {
    return ["Pairing rejected", "No pairing code was generated."];
  }
  if (state === "expired") {
    return [
      "Pairing approval expired",
      "The expired decision cannot generate a pairing code.",
    ];
  }
  if (state === "consumed") {
    return [
      "Pairing approval already consumed",
      "No code can be recovered. Refresh the channel before requesting another pairing.",
    ];
  }
  if (state === "invalidated") {
    return [
      "Pending pairing changed",
      "The channel selection or pairing draft changed. The old approval will not be finalized here.",
    ];
  }
  return [
    "Pairing approval is unavailable",
    "No code is inferred or generated. Check again when caller-owned approval state is available.",
  ];
}

function deliveryFinalizationCopy(
  state: Exclude<DeliveryFinalizationState, null>,
): [string, string] {
  if (state === "waiting") {
    return [
      "Waiting for an Inbox decision",
      "After an independent decision, check again to continue only this exact failed delivery snapshot.",
    ];
  }
  if (state === "checking") {
    return ["Checking approval…", "No delivery state is inferred until the kernel responds."];
  }
  if (state === "rejected") {
    return ["Retry rejected", "Nothing was requeued."];
  }
  if (state === "expired") {
    return ["Retry approval expired", "The expired decision cannot authorize a requeue."];
  }
  if (state === "consumed") {
    return [
      "Retry approval already consumed",
      "Refresh the receipt before deciding whether any further recovery is needed.",
    ];
  }
  if (state === "invalidated") {
    return [
      "Pending delivery retry changed",
      "The channel selection, receipt or configuration changed. The old approval will not be applied.",
    ];
  }
  return [
    "Approval status unavailable",
    "No retry is inferred. Check again after approval status is available.",
  ];
}

function formatDeliveryTime(value: string) {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? "recorded time unavailable" : parsed.toLocaleString();
}

function ChannelSendTest({ channel }: { channel: ChannelSummary }) {
  const [text, setText] = useState("");
  const [target, setTarget] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  const exactApproval = useExactApprovalFinalizer<
    ChannelSendInput,
    ChannelSendFinalResult
  >({
    isCurrent: (input) => (
      input.channelId === channel.id
      && input.text === text.trim()
      && input.target === target.trim()
    ),
    replay: async (input, approvalId) => normalizeSendResult(
      await client.invoke({
        noun: "channel",
        verb: "channel.send",
        params: {
          channel_id: input.channelId,
          text: input.text,
          ...(input.target ? { target: input.target } : {}),
        },
        idempotency_key: input.idempotencyKey,
        approval_id: approvalId,
      }),
    ),
    onApplied: (result) => {
      applyResult(result.value);
    },
    onRefused: (result) => {
      setMessage(governedResultReason(
        result, "The exact approved test message was not accepted.",
      ));
    },
  });

  useEffect(() => {
    exactApproval.invalidate();
  }, [channel.id]);

  function applyResult(result: InvokeResult | undefined) {
    if (!result) {
      setMessage("The test message outcome is unavailable.");
      return;
    }
    if (
      result.status === "denied"
      || result.status === "error"
      || result.status === "unavailable"
    ) {
      setMessage(`Not sent: ${result.reason}.`);
      return;
    }
    if (result.status === "degraded") {
      setMessage("The channel adapter returned a degraded best-effort result; delivery is not confirmed.");
      return;
    }
    if (result.status !== "ok") return;
    const output = result.output && typeof result.output === "object"
      ? result.output as Record<string, unknown>
      : {};
    setMessage(output.status === "queued"
      ? "Queued for sidecar delivery; delivery is not yet confirmed."
      : "The governed channel adapter accepted the test message.");
    setText("");
  }

  async function send(event: React.FormEvent) {
    event.preventDefault();
    if (!text.trim() || busy) return;
    setBusy(true);
    setMessage("");
    try {
      const input: ChannelSendInput = {
        channelId: channel.id,
        text: text.trim(),
        target: target.trim(),
        idempotencyKey: crypto.randomUUID(),
      };
      const result = await client.invoke({
        noun: "channel",
        verb: "channel.send",
        params: {
          channel_id: input.channelId,
          text: input.text,
          ...(input.target ? { target: input.target } : {}),
        },
        idempotency_key: input.idempotencyKey,
      });
      if (result.status === "pending_human") {
        exactApproval.begin(input, result, "Channel test message");
        setMessage("Waiting for approval in Inbox.");
      } else {
        applyResult(result);
      }
    } catch {
      setMessage("The test message was not accepted. No local delivery is assumed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="detail-section admin-form compact" aria-label="Send channel test" onSubmit={(event) => void send(event)}>
      <p className="eyebrow">Governed test message</p>
      <p className="muted small">This uses the high-consequence <code>channel.send</code> verb and may pause for approval.</p>
      <ExactApprovalFinalizer controller={exactApproval} />
      <label><span>Message</span><textarea className="field-control" rows={3} required value={text} onChange={(event) => { exactApproval.invalidate(); setText(event.target.value); }} /></label>
      <label><span>Optional target</span><input className="field-control" value={target} onChange={(event) => { exactApproval.invalidate(); setTarget(event.target.value); }} /></label>
      <button className="secondary-button" disabled={busy || !channel.enabled || !text.trim()}>{busy ? "Requesting…" : "Send test"}</button>
      {!channel.enabled && <p className="muted small">Enable the channel before requesting a test send.</p>}
      {message && <p className="notice" role="status">{message}</p>}
    </form>
  );
}
