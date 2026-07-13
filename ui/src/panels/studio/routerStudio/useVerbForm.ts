import { useState } from "react";

import type { StatusAck } from "@/api/types";
import { errText, parseJson } from "@/panels/shared";
import {
  outputRecord,
  useControlMutation,
  type ControlMutationState,
} from "@/panels/uxFlow";

export interface VerbFormState {
  id: string;
  setId: (v: string) => void;
  nounId: string;
  setNounId: (v: string) => void;
  inputSchema: string;
  setInputSchema: (v: string) => void;
  outputSchema: string;
  setOutputSchema: (v: string) => void;
  consequence: "low" | "high";
  setConsequence: (v: "low" | "high") => void;
  busy: boolean;
  error: string | null;
  ack: StatusAck | null;
  mutation: ControlMutationState;
  submit: () => Promise<void>;
}

export function useVerbForm(): VerbFormState {
  const [id, setId] = useState("");
  const [nounId, setNounId] = useState("");
  const [inputSchema, setInputSchema] = useState("{}");
  const [outputSchema, setOutputSchema] = useState("{}");
  const [consequence, setConsequence] = useState<"low" | "high">("low");
  const [validationError, setValidationError] = useState<string | null>(null);
  const [ack, setAck] = useState<StatusAck | null>(null);
  const mutation = useControlMutation({
    verb: "control.verb.define",
    onApplied: (output) =>
      setAck({ ...outputRecord(output), status: "ok" }),
  });

  async function submit() {
    if (!id.trim() || !nounId.trim()) {
      setValidationError("Verb id and noun_id are required.");
      return;
    }
    let inSchema: Record<string, unknown>;
    let outSchema: Record<string, unknown>;
    try {
      inSchema = parseJson<Record<string, unknown>>(inputSchema, {});
      outSchema = parseJson<Record<string, unknown>>(outputSchema, {});
    } catch (err) {
      setValidationError(`schema: ${errText(err)}`);
      return;
    }
    setValidationError(null);
    setAck(null);
    await mutation.invoke({
      id: id.trim(),
      noun_id: nounId.trim(),
      input_schema: inSchema,
      output_schema: outSchema,
      consequence,
    });
  }

  return {
    id, setId, nounId, setNounId, inputSchema, setInputSchema, outputSchema,
    setOutputSchema, consequence, setConsequence, busy: mutation.busy,
    error: validationError ?? mutation.error, ack, mutation, submit,
  };
}
