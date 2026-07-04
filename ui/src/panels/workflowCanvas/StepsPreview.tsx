import { CodeBlock } from "@/panels/shared";
import type { WorkflowStep } from "./types";

interface StepsPreviewProps {
  steps: WorkflowStep[];
}

export function StepsPreview({ steps }: StepsPreviewProps) {
  return (
    <div className="form">
      <div className="form__title">Serialised steps (preview)</div>
      <p className="muted">
        The exact definition.steps Save will send. Parents are derived from the
        incoming edges of each step.
      </p>
      <CodeBlock value={steps} />
    </div>
  );
}
