import { useState } from "react";

import { api } from "@/api/client";
import type { HITLRequest } from "@/api/types";
import { reasonOf } from "./hitlUtils";

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

export function useHitlCard(req: HITLRequest, onAnswered: () => void): HitlCardState {
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
      const res = await api.respondHitl(req.id, { decision: value, notes });
      const approved = ["approve", "yes", "allow"].includes(value.toLowerCase());
      setDone(
        res.status
          ? approved
            ? "Recorded - this action is now approved and will continue."
            : "Recorded - this action was declined and will not run."
          : "Recorded.",
      );
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
