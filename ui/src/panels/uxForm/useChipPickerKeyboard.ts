import type { KeyboardEvent } from "react";

export interface UseChipPickerKeyboardArgs {
  query: string;
  value: string[];
  onChange: (v: string[]) => void;
  enabled: number[];
  act: number;
  cands: { value: string }[];
  allowFree: boolean;
  addValue: (v: string) => void;
  addFree: () => void;
  setActive: (v: number) => void;
}

export function useChipPickerKeyboard({
  query,
  value,
  onChange,
  enabled,
  act,
  cands,
  allowFree,
  addValue,
  addFree,
  setActive,
}: UseChipPickerKeyboardArgs) {
  return (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Backspace" && query === "" && value.length > 0) {
      onChange(value.slice(0, -1));
      return;
    }
    if (e.key === "ArrowDown") {
      e.preventDefault();
      const pos = enabled.indexOf(act);
      const next = enabled[Math.min(pos + 1, enabled.length - 1)];
      setActive(next === undefined ? -1 : next);
      return;
    }
    if (e.key === "ArrowUp") {
      e.preventDefault();
      const pos = enabled.indexOf(act);
      setActive(pos <= 0 ? -1 : enabled[pos - 1]);
      return;
    }
    if (e.key === "Enter") {
      e.preventDefault();
      if (act >= 0) addValue(cands[act].value);
      else if (allowFree) addFree();
      return;
    }
    if (e.key === "Escape") setActive(-1);
  };
}
