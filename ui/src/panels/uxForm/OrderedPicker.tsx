import type { ReactNode } from "react";

import type { ChipOption } from "./ChipPicker";
import { OrderedPickerAdd } from "./OrderedPickerAdd";
import { OrderedPickerRow } from "./OrderedPickerRow";
import { useOrderedPicker } from "./useOrderedPicker";

// --- N17 OrderedPicker: an ordered list where position is the value. --------
// Numbered rows with up/down buttons; Alt+ArrowUp/Down moves the focused row;
// every move is announced via a polite live region. Candidates not yet in the
// list render as add affordances (amendment 12 disabled-with-reason honoured).
export function OrderedPicker({
  value,
  onChange,
  options = [],
  mono = true,
  ariaLabel,
  disabled = false,
  emptyHint = "Nothing here yet. Add from the options below; the order is applied top to bottom.",
}: {
  value: string[];
  onChange: (v: string[]) => void;
  options?: ChipOption[];
  mono?: boolean;
  ariaLabel?: string;
  disabled?: boolean;
  emptyHint?: ReactNode;
}) {
  const { announce, labelOf, move, remove, addRow } = useOrderedPicker({ value, onChange, options });
  const remaining = options.filter((o) => !value.includes(o.value));

  return (
    <div className="ux-ordered" role="group" aria-label={ariaLabel}>
      <div className="ux-vh" aria-live="polite">
        {announce}
      </div>
      {value.length === 0 ? (
        <span className="ux-hint">{emptyHint}</span>
      ) : (
        <ol className="ux-ordered__list">
          {value.map((v, i) => (
            <OrderedPickerRow
              key={v}
              index={i}
              label={labelOf(v)}
              mono={mono}
              disabled={disabled}
              isFirst={i === 0}
              isLast={i === value.length - 1}
              move={move}
              remove={remove}
            />
          ))}
        </ol>
      )}
      <OrderedPickerAdd remaining={remaining} disabled={disabled} addRow={addRow} />
    </div>
  );
}
