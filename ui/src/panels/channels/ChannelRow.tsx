import { useState } from "react";

import type { ChannelSummary } from "@/api/types";
import { Field } from "@/panels/ux";
import { SegmentedV2 } from "@/panels/uxForm";
import { ArmConfirm } from "@/panels/uxFlow";
import { PendingHumanCard } from "@/panels/uxFlow/pendingHumanCard";
import { useControlMutation } from "@/panels/uxFlow/useControlMutation";
import { ENABLED_OPTIONS, UNPAIRED_OPTIONS } from "./options";
import { BindingList } from "./BindingList";
import { PairForm } from "./PairForm";

export function useChannelRow(channel: ChannelSummary, onChanged: () => void) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState(channel.name);
  const [unpaired, setUnpaired] = useState(channel.unpaired_behavior);
  const [enabled, setEnabled] = useState(channel.enabled ? "true" : "false");
  const [msg, setMsg] = useState<string | null>(null);
  const configureMutation = useControlMutation({
    verb: "control.channel.configure",
    onApplied() {
      setMsg("Saved.");
      onChanged();
    },
  });
  const disconnectMutation = useControlMutation({
    verb: "control.channel.disconnect",
    onApplied() {
      onChanged();
    },
  });

  async function configure() {
    setMsg(null);
    await configureMutation.invoke({
      channel_id: channel.id,
      name: name.trim() || channel.name,
      unpaired_behavior: unpaired,
      enabled: enabled === "true",
    });
  }

  async function disconnect() {
    await disconnectMutation.invoke({ channel_id: channel.id });
  }

  return {
    open,
    setOpen,
    name,
    setName,
    unpaired,
    setUnpaired,
    enabled,
    setEnabled,
    configureMutation,
    disconnectMutation,
    msg,
    configure,
    disconnect,
  };
}

interface ChannelManageProps {
  channel: ChannelSummary;
  name: string;
  setName: (v: string) => void;
  unpaired: string;
  setUnpaired: (v: string) => void;
  enabled: string;
  setEnabled: (v: string) => void;
  busy: boolean;
  error: string | null;
  msg: string | null;
  configure: () => Promise<void>;
}

function ChannelManage(props: ChannelManageProps) {
  const { channel, name, setName, unpaired, setUnpaired, enabled, setEnabled, busy, error, msg, configure } =
    props;

  return (
    <div className="stack">
      <div className="form">
        <div className="form__title">Configure</div>
        <div className="form__grid">
          <Field label="Name">
            <input value={name} onChange={(e) => setName(e.target.value)} />
          </Field>
          <Field label="Unpaired sender behaviour">
            <SegmentedV2
              value={unpaired}
              ariaLabel="Unpaired sender behaviour"
              onChange={setUnpaired}
              options={UNPAIRED_OPTIONS}
            />
          </Field>
          <Field label="Status">
            <SegmentedV2
              value={enabled}
              ariaLabel="Status"
              onChange={setEnabled}
              options={ENABLED_OPTIONS}
            />
          </Field>
        </div>
        <div className="form__actions">
          <button
            className="btn btn--primary"
            disabled={busy}
            onClick={() => void configure()}
          >
            {busy ? "Saving..." : "Save"}
          </button>
          {msg && <span className="ok">{msg}</span>}
          {error && <span className="error">{error}</span>}
        </div>
      </div>

      <PairForm channelId={channel.id} />
      <BindingList channelId={channel.id} />
    </div>
  );
}

export function ChannelRow({
  channel,
  onChanged,
}: {
  channel: ChannelSummary;
  onChanged: () => void;
}) {
  const {
    open,
    setOpen,
    name,
    setName,
    unpaired,
    setUnpaired,
    enabled,
    setEnabled,
    configureMutation,
    disconnectMutation,
    msg,
    configure,
    disconnect,
  } = useChannelRow(channel, onChanged);

  return (
    <div className="dir-row">
      <div className="row-line dir-row__top">
        <div>
          <code>{channel.name}</code>{" "}
          <span className="badge">{channel.platform}</span>{" "}
          <span className="badge">{channel.transport}</span>
          <div className="muted">
            unpaired: {channel.unpaired_behavior} - id <code>{channel.id}</code>
          </div>
        </div>
        <div className="kv">
          <span className={`badge ${channel.enabled ? "badge--ok" : "badge--down"}`}>
            {channel.enabled ? "enabled" : "disabled"}
          </span>
          <button className="btn" onClick={() => setOpen((o) => !o)}>
            {open ? "Close" : "Manage"}
          </button>
          <ArmConfirm
            label="Disconnect"
            armLabel={
              <>
                Disconnect <code>{channel.name}</code>? Its inbound webhook stops
                accepting messages immediately.
              </>
            }
            confirmLabel="Confirm disconnect"
            tone="danger"
            busyLabel="Disconnecting..."
            onConfirm={() => disconnect()}
          />
        </div>
      </div>

      {open && (
        <ChannelManage
          channel={channel}
          name={name}
          setName={setName}
          unpaired={unpaired}
          setUnpaired={setUnpaired}
          enabled={enabled}
          setEnabled={setEnabled}
          busy={configureMutation.busy || configureMutation.pending !== null}
          error={configureMutation.error}
          msg={msg}
          configure={configure}
        />
      )}
      {configureMutation.pending && (
        <PendingHumanCard
          hitlRequestId={configureMutation.pending.id}
          noun="control"
          verb="control.channel.configure"
          sentParams={configureMutation.pending.params}
          onApplied={configureMutation.onPendingApplied}
          onDenied={configureMutation.onPendingDenied}
          onReset={configureMutation.resetPending}
        />
      )}
      {disconnectMutation.error && <p className="error">{disconnectMutation.error}</p>}
      {disconnectMutation.pending && (
        <PendingHumanCard
          hitlRequestId={disconnectMutation.pending.id}
          noun="control"
          verb="control.channel.disconnect"
          sentParams={disconnectMutation.pending.params}
          onApplied={disconnectMutation.onPendingApplied}
          onDenied={disconnectMutation.onPendingDenied}
          onReset={disconnectMutation.resetPending}
        />
      )}
    </div>
  );
}
