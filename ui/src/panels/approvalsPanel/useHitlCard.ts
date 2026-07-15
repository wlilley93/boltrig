import { useState } from "react";

import { api } from "@/api/client";
import type { HITLKind } from "@/api/types";
import { reasonOf } from "./hitlUtils";

export interface HitlResponseRequest {
  id: string;
  type: HITLKind;
}

export interface HitlCardState {
  decision: string;
  setDecision: (v: string) => void;
  notes: string;
  setNotes: (v: string) => void;
  busy: boolean;
  error: string | null;
  done: string | null;
  arming: string | null;
  setArming: (v: string | null) => void;
  submit: (value: string) => Promise<void>;
  confirmArmed: () => Promise<void>;
}

export function useHitlCard(
  req: HitlResponseRequest,
  onAnswered: () => void,
): HitlCardState {
  const [decision, setDecision] = useState("");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const [arming, setArming] = useState<string | null>(null);

  async function submit(value: string) {
    if (!value) {
      setError("Type your answer first.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      if (req.type === "question") {
        const res = await api.answerQuestion(req.id, value);
        if (res.status !== "ok") {
          setError(res.reason ?? `Answer failed: ${res.status}`);
          return;
        }
      } else {
        await api.respondHitl(req.id, { decision: value, notes });
      }
      setDone("Response recorded. Runtime state will update according to server policy.");
      onAnswered();
    } catch (err) {
      setError(reasonOf(err));
    } finally {
      setBusy(false);
    }
  }

  async function confirmArmed() {
    if (arming) await submit(arming);
  }

  return {
    decision, setDecision, notes, setNotes, busy, error, done, arming, setArming,
    submit, confirmArmed,
  };
}
