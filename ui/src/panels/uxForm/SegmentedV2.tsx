import { useRef } from "react";
import type { KeyboardEvent } from "react";

import { nextEnabled } from "./nextEnabled";
import type { Option } from "../ux";

// --- P3 SegmentedV2: 2-4 mutually exclusive values, radio semantics. --------
// Upgrade of ux.tsx Segmented: role="radiogroup" + roving tabindex + arrow
// keys (select on move, per native radio behaviour). Reuses the .seg CSS.
export function SegmentedV2({
  value,
  onChange,
  options,
  ariaLabel,
  disabled = false,
}: {
  value: string;
  onChange: (v: string) => void;
  options: Option[];
  ariaLabel?: string;
  disabled?: boolean;
}) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const selIdx = options.findIndex((o) => o.value === value);

  function onKey(e: KeyboardEvent<HTMLDivElement>) {
    if (disabled) return;
    const delta =
      e.key === "ArrowRight" || e.key === "ArrowDown"
        ? 1
        : e.key === "ArrowLeft" || e.key === "ArrowUp"
          ? -1
          : 0;
    if (delta === 0) return;
    e.preventDefault();
    const next = nextEnabled(
      options.length,
      () => false,
      selIdx < 0 ? (delta > 0 ? -1 : 0) : selIdx,
      delta,
    );
    if (next < 0) return;
    onChange(options[next].value);
    refs.current[next]?.focus();
  }

  return (
    <div className="seg" role="radiogroup" aria-label={ariaLabel} onKeyDown={onKey}>
      {options.map((o, i) => (
        <button
          key={o.value}
          type="button"
          role="radio"
          aria-checked={o.value === value}
          tabIndex={o.value === value || (selIdx < 0 && i === 0) ? 0 : -1}
          ref={(el) => {
            refs.current[i] = el;
          }}
          className={`btn btn--seg ${o.value === value ? "btn--seg-on" : ""}`}
          title={o.hint}
          disabled={disabled}
          onClick={() => onChange(o.value)}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
