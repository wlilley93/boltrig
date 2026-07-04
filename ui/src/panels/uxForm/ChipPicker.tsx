import type { ReactNode } from "react";

import { ChipPickerChips, type ChipOption } from "./ChipPickerChips";
import { ChipPickerSearch } from "./ChipPickerSearch";
import { useChipPicker } from "./useChipPicker";

// --- N3 ChipPicker: multi-select from a known set (P5). ---------------------
// Selected values are removable chips; a search input filters candidates;
// Backspace in the empty search removes the last chip; ArrowDown enters the
// candidate list (roving via aria-activedescendant, candidates stay out of
// the Tab order). allowFree admits values outside the candidate set, vetted
// by the per-chip validate fn. Amendment 12: candidates may be disabled with
// a visible reason line (the automations parents editor consumes this).
export function ChipPicker({
  value,
  onChange,
  options = [],
  searchable = true,
  allowFree = false,
  validate,
  mono = false,
  disabled = false,
  placeholder,
  ariaLabel,
  emptyHint,
}: {
  value: string[];
  onChange: (v: string[]) => void;
  options?: ChipOption[];
  searchable?: boolean;
  allowFree?: boolean;
  // free entries only; candidates are pre-vetted. Return a reason to reject.
  validate?: (v: string) => string | null;
  mono?: boolean;
  disabled?: boolean;
  placeholder?: string;
  ariaLabel?: string;
  emptyHint?: ReactNode;
}) {
  const hook = useChipPicker({ value, onChange, options, allowFree, validate, disabled, searchable });

  return (
    <div className={`ux-chips ${mono ? "ux-chips--mono" : ""}`} role="group" aria-label={ariaLabel}>
      <ChipPickerChips
        value={value}
        options={options}
        mono={mono}
        disabled={disabled}
        emptyHint={emptyHint}
        onChange={onChange}
      />
      <ChipPickerSearch {...hook} placeholder={placeholder} ariaLabel={ariaLabel} disabled={disabled} allowFree={allowFree} />
    </div>
  );
}

export type { ChipOption } from "./ChipPickerChips";
