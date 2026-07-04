import { useEffect, useState } from "react";
import type { ReactNode } from "react";

import { StepperButtons } from "./StepperButtons";

// --- N6 Stepper: bounded number with a unit (P8). ---------------------------
// input[type=number] flanked by minus/plus, clamped on blur, buttons disabled
// at the bounds. State the range in the owning Field's hint; meta carries a
// caller-computed derived fact (e.g. the expiry date a TTL resolves to).
export function Stepper({
  value,
  onChange,
  min,
  max,
  step = 1,
  unit,
  meta,
  id,
  disabled = false,
  ariaLabel,
}: {
  value: number;
  onChange: (v: number) => void;
  min?: number;
  max?: number;
  step?: number;
  unit?: string;
  meta?: ReactNode;
  id?: string;
  disabled?: boolean;
  ariaLabel?: string;
}) {
  const [draft, setDraft] = useState(String(value));
  useEffect(() => {
    setDraft(String(value));
  }, [value]);

  function clamp(n: number): number {
    let v = n;
    if (typeof min === "number") v = Math.max(min, v);
    if (typeof max === "number") v = Math.min(max, v);
    return v;
  }

  function commit(n: number) {
    const v = clamp(n);
    onChange(v);
    setDraft(String(v));
  }

  const atMin = typeof min === "number" && value <= min;
  const atMax = typeof max === "number" && value >= max;

  return (
    <div className="ux-stepper">
      <StepperButtons value={value} step={step} disabled={disabled} atMin={atMin} atMax={atMax} commit={commit} />
      <span className="ux-stepper__box">
        <input
          id={id}
          type="number"
          inputMode="numeric"
          aria-label={ariaLabel}
          min={min}
          max={max}
          step={step}
          value={draft}
          disabled={disabled}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={() => {
            const n = Number(draft);
            if (draft.trim() === "" || !Number.isFinite(n)) {
              setDraft(String(value));
              return;
            }
            commit(n);
          }}
        />
        {unit && <span className="ux-stepper__unit">{unit}</span>}
      </span>
      {meta != null && <span className="ux-stepper__meta">{meta}</span>}
    </div>
  );
}
