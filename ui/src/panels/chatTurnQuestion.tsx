// Inline answer card for an agent's clarifying QUESTION (US-CHAT-12). Choices
// (when present) render as one-click options; otherwise a free-text input. A
// submit POSTs to /v1/hitl/{question_id}/answer; on success the answer is shown
// as recorded and the card is disabled, and the backend requeues the paused run
// so the stream resumes. Owner-only is enforced server-side; a 400/403/404/409
// returns {status, reason} which is surfaced in place (never a raw HTTP code).

import { useState } from "react";
import { api } from "@/api/client";
import type { QuestionEntry } from "@/panels/chatTurnTypes";
import { apiReason } from "@/panels/shared";

export interface QuestionResponseState {
  value: string;
  setValue: (v: string) => void;
  busy: boolean;
  error: string | null;
  submit: (answer: string) => Promise<void>;
}

export function useQuestionResponse(
  entry: QuestionEntry,
  onResolve: (id: string, answer: string) => void,
): QuestionResponseState {
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(answer: string) {
    const a = answer.trim();
    if (!a) {
      setError("Provide an answer.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const res = await api.answerQuestion(entry.questionId, a);
      if (res.status !== "ok") {
        setError(res.reason ?? `Answer failed: ${res.status}`);
        return;
      }
      onResolve(entry.questionId, a);
    } catch (err) {
      setError(apiReason(err));
    } finally {
      setBusy(false);
    }
  }

  return { value, setValue, busy, error, submit };
}

function QuestionResponseForm({
  entry,
  busy,
  submit,
  value,
  setValue,
}: {
  entry: QuestionEntry;
  busy: boolean;
  submit: (answer: string) => void;
  value: string;
  setValue: (v: string) => void;
}) {
  const hasChoices = entry.choices.length > 0;

  if (hasChoices) {
    return (
      <div className="chat-hitl__options">
        {entry.choices.map((opt) => (
          <button key={opt} className="btn" disabled={busy} onClick={() => void submit(opt)}>
            {opt}
          </button>
        ))}
      </div>
    );
  }

  return (
    <div className="chat-hitl__row">
      <input
        className="chat-hitl__text"
        placeholder="your answer"
        value={value}
        disabled={busy}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            void submit(value);
          }
        }}
      />
      <button
        className="btn btn--primary"
        disabled={busy}
        onClick={() => void submit(value)}
      >
        {busy ? "..." : "Send"}
      </button>
    </div>
  );
}

export function ChatQuestionCard({
  entry,
  resolved,
  onResolve,
}: {
  entry: QuestionEntry;
  resolved: string | undefined;
  onResolve: (id: string, answer: string) => void;
}) {
  const { value, setValue, busy, error, submit } = useQuestionResponse(entry, onResolve);

  return (
    <article className="chat-hitl chat-question">
      <div className="chat-hitl__head">
        <span className="badge badge--type badge--type-clarification">question</span>
        <code className="muted">{entry.questionId}</code>
      </div>
      <p className="chat-hitl__question">{entry.prompt || "(no question)"}</p>

      {resolved !== undefined ? (
        <p className="ok">Answered: {resolved}</p>
      ) : (
        <div className="chat-hitl__respond">
          <QuestionResponseForm
            entry={entry}
            busy={busy}
            submit={submit}
            value={value}
            setValue={setValue}
          />
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
        </div>
      )}
    </article>
  );
}
