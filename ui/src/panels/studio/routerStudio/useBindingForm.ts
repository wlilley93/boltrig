import { useState } from "react";

import { api } from "@/api/client";
import type { StatusAck, TargetTypeValue } from "@/api/types";
import { errText } from "@/panels/shared";
import { useFetch } from "@/useFetch";

export interface BindingFormState {
  verbId: string;
  setVerbId: (v: string) => void;
  targetType: TargetTypeValue;
  targetRef: string;
  setTargetRef: (v: string) => void;
  changeTargetType: (v: string) => void;
  busy: boolean;
  error: string | null;
  ack: StatusAck | null;
  verbOptions: { value: string; label: string }[];
  adapterOptions: { value: string; label: string }[];
  submit: () => Promise<void>;
}

export function useBindingForm(): BindingFormState {
  const caps = useFetch(() => api.capabilities(), []);
  const adapters = useFetch(() => api.adapters(), []);
  const [verbId, setVerbId] = useState("");
  const [targetType, setTargetType] = useState<TargetTypeValue>("adapter");
  const [targetRef, setTargetRef] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ack, setAck] = useState<StatusAck | null>(null);

  function changeTargetType(v: string) {
    setTargetType(v === "agent" ? "agent" : "adapter");
    setTargetRef("");
  }

  async function submit() {
    if (!verbId.trim() || !targetRef.trim()) {
      setError("Pick a verb and what should run it.");
      return;
    }
    setBusy(true);
    setError(null);
    setAck(null);
    try {
      setAck(
        await api.setBinding(verbId.trim(), {
          target_type: targetType,
          target_ref: targetRef.trim(),
        }),
      );
    } catch (err) {
      setError(errText(err));
    } finally {
      setBusy(false);
    }
  }

  const verbOptions = [
    { value: "", label: "Choose a verb..." },
    ...(caps.data?.verbs ?? []).map((v) => ({ value: v.id, label: v.id })),
  ];
  const adapterOptions = [
    { value: "", label: "Choose an adapter..." },
    ...(adapters.data?.adapters ?? []).map((a) => ({ value: a.id, label: a.id })),
  ];

  return {
    verbId, setVerbId, targetType, targetRef, setTargetRef, changeTargetType,
    busy, error, ack, verbOptions, adapterOptions, submit,
  };
}
