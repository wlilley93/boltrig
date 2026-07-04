import { useState } from "react";

import { api } from "@/api/client";
import type { ChannelSummary } from "@/api/types";
import { apiReason } from "@/panels/shared";
import { Field } from "@/panels/ux";
import { SegmentedV2 } from "@/panels/uxForm";
import { ArmConfirm } from "@/panels/uxFlow";
import { ENABLED_OPTIONS, UNPAIRED_OPTIONS } from "./options";
import { BindingList } from "./BindingList";
import { PairForm } from "./PairForm";

export function useChannelRow(channel: ChannelSummary, onChanged: () => void) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState(channel.name);
  const [unpaired, setUnpaired] = useState(channel.unpaired_behavior);
  const [enabled, setEnabled] = useState(channel.enabled ? "true" : "false");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  async function configure() {
    setBusy(true);
    setError(null);
    setMsg(null);
    try {
      const res = await api.configureChannel(channel.id, {
        name: name.trim() || channel.name,
        unpaired_behavior: unpaired,
        enabled: enabled === "true",
      });
      if (res.status === "ok") {
        setMsg("Saved.");
        onChanged();
      } else {
        setError(res.reason ?? "update rejected");
      }
    } catch (err) {
      setError(apiReason(err));
    } finally {
      setBusy(false);
    }
  }

  async function disconnect() {
    const res = await api.disconnectChannel(channel.id);
    if (res.status !== "ok") {
      throw new Error(res.reason ?? "disconnect rejected");
    }
    onChanged();
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
    busy,
    error,
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
    busy,
    error,
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
          busy={busy}
          error={error}
          msg={msg}
          configure={configure}
        />
      )}
    </div>
  );
}
