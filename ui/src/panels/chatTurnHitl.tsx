// Inline HITL. The same request also surfaces in the Approvals panel (one
// shared store), so answering it here resolves it there too, and vice versa.

import { useState } from "react";
import { api } from "@/api/client";
import type { HitlEntry } from "@/panels/chatTurnTypes";
import { errText } from "@/panels/shared";

export interface HitlResponseState {
  value: string;
  setValue: (v: string) => void;
  notes: string;
  setNotes: (v: string) => void;
  busy: boolean;
  error: string | null;
  submit: (decision: string) => Promise<void>;
}

export function useHitlResponse(
  entry: HitlEntry,
  onResolve: (id: string, status: string) => void,
): HitlResponseState {
  const [value, setValue] = useState("");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(decision: string) {
    if (!decision) {
      setError("Provide a response.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const res = await api.respondHitl(entry.hitlRequestId, { decision, notes });
      onResolve(entry.hitlRequestId, `recorded (${res.status})`);
    } catch (err) {
      setError(errText(err));
    } finally {
      setBusy(false);
    }
  }

  return { value, setValue, notes, setNotes, busy, error, submit };
}

function HitlResponseForm({
  entry,
  busy,
  submit,
  value,
  setValue,
}: {
  entry: HitlEntry;
  busy: boolean;
  submit: (decision: string) => void;
  value: string;
  setValue: (v: string) => void;
}) {
  const options =
    entry.kind === "approval"
      ? entry.options.length > 0
        ? entry.options
        : ["approve", "reject"]
      : entry.options;

  if (entry.kind === "clarification") {
    return (
      <div className="chat-hitl__row">
        <input
          className="chat-hitl__text"
          placeholder="your answer"
          value={value}
          disabled={busy}
          onChange={(e) => setValue(e.target.value)}
        />
        <button
          className="btn btn--primary"
          disabled={busy}
          onClick={() => submit(value)}
        >
          {busy ? "..." : "Send"}
        </button>
      </div>
    );
  }

  return (
    <div className="chat-hitl__options">
      {options.map((opt) => (
        <button key={opt} className="btn" disabled={busy} onClick={() => submit(opt)}>
          {opt}
        </button>
      ))}
    </div>
  );
}

export function ChatHitlCard({
  entry,
  resolved,
  onResolve,
}: {
  entry: HitlEntry;
  resolved: string | undefined;
  onResolve: (id: string, status: string) => void;
}) {
  const { value, setValue, notes, setNotes, busy, error, submit } = useHitlResponse(entry, onResolve);

  return (
    <article className="chat-hitl">
      <div className="chat-hitl__head">
        <span className={`badge badge--type badge--type-${entry.kind}`}>{entry.kind}</span>
        <code className="muted">{entry.hitlRequestId}</code>
      </div>
      <p className="chat-hitl__question">{entry.question || "(no question)"}</p>

      {resolved ? (
        <p className="ok">Answered: {resolved}</p>
      ) : (
        <div className="chat-hitl__respond">
          <HitlResponseForm
            entry={entry}
            busy={busy}
            submit={submit}
            value={value}
            setValue={setValue}
          />
          <textarea
            className="chat-hitl__notes"
            placeholder="notes (optional)"
            value={notes}
            disabled={busy}
            rows={1}
            onChange={(e) => setNotes(e.target.value)}
          />
          {error && <p className="error">{error}</p>}
        </div>
      )}
    </article>
  );
}
