import { useState } from "react";

import { api } from "@/api/client";
import type { StatusAck } from "@/api/types";
import { errText, parseJson } from "@/panels/shared";

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
  submit: () => Promise<void>;
}

export function useVerbForm(): VerbFormState {
  const [id, setId] = useState("");
  const [nounId, setNounId] = useState("");
  const [inputSchema, setInputSchema] = useState("{}");
  const [outputSchema, setOutputSchema] = useState("{}");
  const [consequence, setConsequence] = useState<"low" | "high">("low");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ack, setAck] = useState<StatusAck | null>(null);

  async function submit() {
    if (!id.trim() || !nounId.trim()) {
      setError("Verb id and noun_id are required.");
      return;
    }
    let inSchema: Record<string, unknown>;
    let outSchema: Record<string, unknown>;
    try {
      inSchema = parseJson<Record<string, unknown>>(inputSchema, {});
      outSchema = parseJson<Record<string, unknown>>(outputSchema, {});
    } catch (err) {
      setError(`schema: ${errText(err)}`);
      return;
    }
    setBusy(true);
    setError(null);
    setAck(null);
    try {
      setAck(
        await api.upsertVerb({
          id: id.trim(),
          noun_id: nounId.trim(),
          input_schema: inSchema,
          output_schema: outSchema,
          consequence,
        }),
      );
    } catch (err) {
      setError(errText(err));
    } finally {
      setBusy(false);
    }
  }

  return {
    id, setId, nounId, setNounId, inputSchema, setInputSchema, outputSchema,
    setOutputSchema, consequence, setConsequence, busy, error, ack, submit,
  };
}
