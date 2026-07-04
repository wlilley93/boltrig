import { useState } from "react";

import { api } from "@/api/client";
import type { ChannelSummary } from "@/api/types";
import { apiReason } from "@/panels/shared";

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
