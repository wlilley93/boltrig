import { useId } from "react";

import { Field } from "@/panels/ux";
import { HitlConfirmStep } from "./HitlConfirmStep";
import { HitlOptionButtons } from "./HitlOptionButtons";
import { HitlCustomAnswer } from "./HitlCustomAnswer";
import type { HitlCardState } from "./useHitlCard";

// The action surface of a HITL card: once answered it shows the outcome,
// otherwise it offers the confirm/options/answer branch (flattened from the old
// 3-deep ternary) plus the shared notes field and any error.
export function HitlRespond({
  options,
  h,
  showNotes = true,
}: {
  options: string[];
  h: HitlCardState;
  showNotes?: boolean;
}) {
  const notesId = useId();
  if (h.done) return <p className="ok">{h.done}</p>;

  return (
    <div className="hitl-card__respond">
      {options.length > 0 ? (
        h.arming ? (
          <HitlConfirmStep
            arming={h.arming}
            busy={h.busy}
            onConfirm={h.confirmArmed}
            onCancel={() => h.setArming(null)}
          />
        ) : (
          <HitlOptionButtons options={options} busy={h.busy} onArm={h.setArming} />
        )
      ) : (
        <HitlCustomAnswer
          decision={h.decision}
          setDecision={h.setDecision}
          busy={h.busy}
          onSubmit={() => h.submit(h.decision)}
        />
      )}

      {showNotes && (
        <Field label="Notes (optional)" htmlFor={notesId} hint="Your reasoning is recorded in the audit trail.">
          <textarea
            id={notesId}
            className="hitl-card__notes"
            value={h.notes}
            disabled={h.busy}
            onChange={(e) => h.setNotes(e.target.value)}
            rows={2}
          />
        </Field>
      )}

      {h.error && <p className="error">{h.error}</p>}
    </div>
  );
}
