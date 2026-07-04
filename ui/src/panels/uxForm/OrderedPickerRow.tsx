import type { KeyboardEvent } from "react";

export interface OrderedPickerRowProps {
  index: number;
  label: string;
  mono: boolean;
  disabled: boolean;
  isFirst: boolean;
  isLast: boolean;
  move: (i: number, delta: number) => void;
  remove: (i: number) => void;
}

export function OrderedPickerRow({
  index,
  label,
  mono,
  disabled,
  isFirst,
  isLast,
  move,
  remove,
}: OrderedPickerRowProps) {
  return (
    <li
      className="ux-ordered__row"
      tabIndex={0}
      onKeyDown={(e: KeyboardEvent<HTMLLIElement>) => {
        if (disabled || !e.altKey) return;
        if (e.key === "ArrowUp") {
          e.preventDefault();
          move(index, -1);
        } else if (e.key === "ArrowDown") {
          e.preventDefault();
          move(index, 1);
        }
      }}
    >
      <span className="ux-ordered__num" aria-hidden="true">
        {index + 1}
      </span>
      <span className="ux-ordered__label">{mono ? <code>{label}</code> : label}</span>
      <span className="ux-ordered__acts">
        <button
          type="button"
          className="btn btn--sm btn--ghost ux-ordered__btn"
          aria-label={`Move ${label} up`}
          disabled={disabled || isFirst}
          onClick={() => move(index, -1)}
        >
          ↑
        </button>
        <button
          type="button"
          className="btn btn--sm btn--ghost ux-ordered__btn"
          aria-label={`Move ${label} down`}
          disabled={disabled || isLast}
          onClick={() => move(index, 1)}
        >
          ↓
        </button>
        <button
          type="button"
          className="btn btn--sm btn--ghost ux-ordered__btn"
          aria-label={`Remove ${label}`}
          disabled={disabled}
          onClick={() => remove(index)}
        >
          ×
        </button>
      </span>
    </li>
  );
}
