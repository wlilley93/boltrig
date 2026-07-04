import { Hint } from "@/panels/ux";
import { optionClass } from "./hitlUtils";

// The first step for a fixed-option request: pick an option (which then arms
// the confirm step). Shown when the request offers a fixed set of options.
export function HitlOptionButtons({
  options,
  busy,
  onArm,
}: {
  options: string[];
  busy: boolean;
  onArm: (opt: string) => void;
}) {
  return (
    <>
      <Hint>This decision is deliberate - you will be asked to confirm.</Hint>
      <div className="hitl-card__options">
        {options.map((opt) => (
          <button key={opt} className={optionClass(opt)} disabled={busy} onClick={() => onArm(opt)}>
            {opt}
          </button>
        ))}
      </div>
    </>
  );
}
