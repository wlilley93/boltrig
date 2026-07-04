// The interpreter's step walk: a compact ordered checklist that mirrors the
// canvas nodes (each step lights as it runs). Distinct from ToolCards, which
// show the underlying verb dispatch a step makes.

import type { StepEntry } from "@/panels/chatTurnTypes";

export function StepsCard({ steps }: { steps: StepEntry[] }) {
  return (
    <div className="steps-card">
      <div className="steps-card__head">
        <span className="badge">workflow</span>
        <span className="muted">{steps.length} step(s)</span>
      </div>
      <ol className="steps-card__list">
        {steps.map((s) => (
          <li className="steps-card__item" key={s.stepId}>
            <span className={`badge badge--tool-${s.status === "failed" ? "error" : s.status}`}>
              {s.status}
            </span>
            <code className="badge badge--verb">{s.action}</code>
          </li>
        ))}
      </ol>
    </div>
  );
}
