import { useState } from "react";

import type { StatusAck, TargetTypeValue } from "@/api/types";
import { api } from "@/api/client";
import {
  outputRecord,
  useControlMutation,
  type ControlMutationState,
} from "@/panels/uxFlow";
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
  mutation: ControlMutationState;
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
  const [validationError, setValidationError] = useState<string | null>(null);
  const [ack, setAck] = useState<StatusAck | null>(null);
  const mutation = useControlMutation({
    verb: "control.binding.set",
    onApplied: (output) =>
      setAck({ ...outputRecord(output), status: "ok" }),
  });

  function changeTargetType(v: string) {
    setTargetType(v === "agent" ? "agent" : "adapter");
    setTargetRef("");
  }

  async function submit() {
    if (!verbId.trim() || !targetRef.trim()) {
      setValidationError("Pick a verb and what should run it.");
      return;
    }
    setValidationError(null);
    setAck(null);
    await mutation.invoke({
      verb_id: verbId.trim(),
      target_type: targetType,
      target_ref: targetRef.trim(),
    });
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
    busy: mutation.busy, error: validationError ?? mutation.error, ack, mutation,
    verbOptions, adapterOptions, submit,
  };
}
