import type { ReactNode } from "react";

export interface ChipOption {
  value: string;
  label?: string;
  hint?: string;
  disabled?: boolean;
  disabledReason?: string;
}

export interface ChipPickerChipsProps {
  value: string[];
  options: ChipOption[];
  mono: boolean;
  disabled: boolean;
  emptyHint?: ReactNode;
  onChange: (v: string[]) => void;
}

export function ChipPickerChips({ value, options, mono, disabled, emptyHint, onChange }: ChipPickerChipsProps) {
  return (
    <div className="ux-chips__row">
      {value.length === 0 && emptyHint != null && <span className="ux-hint">{emptyHint}</span>}
      {value.map((v) => {
        const opt = options.find((o) => o.value === v);
        return (
          <span key={v} className={`ux-chips__chip ${mono ? "ux-chips__chip--mono" : ""}`}>
            {opt?.label ?? v}
            {!disabled && (
              <button
                type="button"
                className="ux-chips__rm"
                aria-label={`Remove ${v}`}
                onClick={() => onChange(value.filter((x) => x !== v))}
              >
                ×
              </button>
            )}
          </span>
        );
      })}
    </div>
  );
}
