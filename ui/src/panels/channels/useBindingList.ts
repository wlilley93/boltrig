import { useState } from "react";

import { api } from "@/api/client";
import type { ChannelBindingSummary, ChannelBindingsResponse } from "@/api/types";
import { useFetch, type FetchState } from "@/useFetch";
import { errText } from "@/panels/shared";

export function useBindingList(channelId: string) {
  const bindings = useFetch(() => api.channelBindings(channelId), [channelId]);

  const [ext, setExt] = useState("");
  const [subject, setSubject] = useState("");
  const [role, setRole] = useState("member");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function addBinding() {
    if (!ext.trim() || !subject.trim()) {
      setError("An external user id and a subject are required.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const res = await api.bindChannel(channelId, {
        external_user_id: ext.trim(),
        subject: subject.trim(),
        role,
      });
      if (res.status === "ok") {
        setExt("");
        setSubject("");
        bindings.reload();
      } else {
        setError(res.reason ?? "bind rejected");
      }
    } catch (err) {
      setError(errText(err));
    } finally {
      setBusy(false);
    }
  }

  async function removeBinding(bindingId: string) {
    const res = await api.deleteChannelBinding(channelId, bindingId);
    if (res.status !== "ok") {
      throw new Error(res.reason ?? "remove rejected");
    }
    bindings.reload();
  }

  const denied =
    bindings.data && bindings.data.bindings === undefined
      ? bindings.data.reason ?? "not permitted"
      : null;
  const list: ChannelBindingSummary[] = bindings.data?.bindings ?? [];

  return {
    bindings,
    ext,
    setExt,
    subject,
    setSubject,
    role,
    setRole,
    busy,
    error,
    addBinding,
    removeBinding,
    denied,
    list,
  };
}

export type BindingListState = {
  bindings: FetchState<ChannelBindingsResponse>;
  ext: string;
  setExt: (v: string) => void;
  subject: string;
  setSubject: (v: string) => void;
  role: string;
  setRole: (v: string) => void;
  busy: boolean;
  error: string | null;
  addBinding: () => Promise<void>;
  removeBinding: (id: string) => Promise<void>;
  denied: string | null;
  list: ChannelBindingSummary[];
};
