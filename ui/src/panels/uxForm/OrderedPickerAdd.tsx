import type { ChipOption } from "./ChipPicker";

export interface OrderedPickerAddProps {
  remaining: ChipOption[];
  disabled: boolean;
  addRow: (v: string) => void;
}

export function OrderedPickerAdd({ remaining, disabled, addRow }: OrderedPickerAddProps) {
  if (remaining.length === 0 || disabled) return null;
  return (
    <div className="ux-ordered__add">
      {remaining.map((o) =>
        o.disabled ? (
          <span key={o.value} className="ux-chips__cand ux-chips__cand--off">
            <span>{o.label ?? o.value}</span>
            {o.disabledReason && <span className="ux-chips__cand-why">{o.disabledReason}</span>}
          </span>
        ) : (
          <button
            key={o.value}
            type="button"
            className="ux-chips__addbtn"
            onClick={() => addRow(o.value)}
          >
            + {o.label ?? o.value}
          </button>
        ),
      )}
    </div>
  );
}
