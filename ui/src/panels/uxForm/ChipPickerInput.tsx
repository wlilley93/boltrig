import type { Dispatch, KeyboardEvent, SetStateAction } from "react";

import type { ChipOption } from "./ChipPickerChips";

export interface ChipPickerInputProps {
  query: string;
  setQuery: Dispatch<SetStateAction<string>>;
  setActive: Dispatch<SetStateAction<number>>;
  setFreeError: Dispatch<SetStateAction<string | null>>;
  listId: string;
  act: number;
  cands: ChipOption[];
  showInput: boolean;
  showFreeRow: boolean;
  placeholder?: string;
  ariaLabel?: string;
  disabled: boolean;
  onKey: (e: KeyboardEvent<HTMLInputElement>) => void;
}

export function ChipPickerInput({
  query,
  setQuery,
  setActive,
  setFreeError,
  listId,
  act,
  cands,
  showInput,
  showFreeRow,
  placeholder,
  ariaLabel,
  disabled,
  onKey,
}: ChipPickerInputProps) {
  if (!showInput) return null;
  return (
    <input
      className="ux-chips__search"
      role="combobox"
      aria-expanded={cands.length > 0 || showFreeRow}
      aria-controls={listId}
      aria-activedescendant={act >= 0 ? `${listId}-o${act}` : undefined}
      aria-label={ariaLabel ?? "Add values"}
      value={query}
      placeholder={placeholder ?? (cands.length > 0 ? "Type to filter..." : "Type a value and press Enter")}
      onChange={(e) => {
        setQuery(e.target.value);
        setActive(-1);
        setFreeError(null);
      }}
      onKeyDown={onKey}
      disabled={disabled}
    />
  );
}
