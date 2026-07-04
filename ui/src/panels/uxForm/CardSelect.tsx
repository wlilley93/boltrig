import { useRef } from "react";
import type { KeyboardEvent, ReactNode } from "react";

import { nextEnabled } from "./nextEnabled";

// --- N2 CardSelect: enum whose correct choice needs metadata (P4). ----------
// 2-5 cards, single select, radio semantics (arrows move + select, roving
// tabindex). Badges reuse the existing .badge families.
export interface CardOption {
  value: string;
  label: ReactNode;
  body?: ReactNode;
  badges?: ReactNode;
  disabled?: boolean;
}

export function CardSelect({
  value,
  onChange,
  options,
  ariaLabel,
}: {
  value: string;
  onChange: (v: string) => void;
  options: CardOption[];
  ariaLabel?: string;
}) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const selIdx = options.findIndex((o) => o.value === value);

  function onKey(e: KeyboardEvent<HTMLDivElement>) {
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
      (i) => !!options[i].disabled,
      selIdx < 0 ? (delta > 0 ? -1 : 0) : selIdx,
      delta,
    );
    if (next < 0) return;
    onChange(options[next].value);
    refs.current[next]?.focus();
  }

  return (
    <div className="ux-cardsel" role="radiogroup" aria-label={ariaLabel} onKeyDown={onKey}>
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
          className="ux-cardsel__card"
          disabled={o.disabled}
          onClick={() => onChange(o.value)}
        >
          <span className="ux-cardsel__title">{o.label}</span>
          {o.body != null && <span className="ux-cardsel__body">{o.body}</span>}
          {o.badges != null && <span className="ux-cardsel__badges">{o.badges}</span>}
        </button>
      ))}
    </div>
  );
}
