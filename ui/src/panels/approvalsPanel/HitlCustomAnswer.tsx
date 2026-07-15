import { useId } from "react";

import { Field } from "@/panels/ux";

// A free-text answer for a request with no fixed options (a clarification or an
// escalation): the typed text is sent back to the agent that asked.
export function HitlCustomAnswer({
  decision,
  setDecision,
  busy,
  onSubmit,
}: {
  decision: string;
  setDecision: (v: string) => void;
  busy: boolean;
  onSubmit: () => void;
}) {
  const inputId = useId();
  return (
    <Field
      label="Your answer"
      htmlFor={inputId}
      hint="This text is sent back to the agent that asked."
      example="Use the staging account, not production"
    >
      <div className="hitl-card__custom">
        <input
          id={inputId}
          className="hitl-card__decision"
          value={decision}
          disabled={busy}
          onChange={(e) => setDecision(e.target.value)}
        />
        <button className="btn btn--primary" disabled={busy} onClick={onSubmit}>
          {busy ? "Sending..." : "Send answer"}
        </button>
      </div>
    </Field>
  );
}
