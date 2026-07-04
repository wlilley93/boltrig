import { useState } from "react";

import type { ChipOption } from "./ChipPicker";

export interface UseOrderedPickerArgs {
  value: string[];
  onChange: (v: string[]) => void;
  options: ChipOption[];
}

export interface UseOrderedPickerResult {
  announce: string;
  labelOf: (v: string) => string;
  move: (i: number, delta: number) => void;
  remove: (i: number) => void;
  addRow: (v: string) => void;
}

export function useOrderedPicker({ value, onChange, options }: UseOrderedPickerArgs): UseOrderedPickerResult {
  const [announce, setAnnounce] = useState("");
  const labelOf = (v: string) => options.find((o) => o.value === v)?.label ?? v;

  function move(i: number, delta: number) {
    const j = i + delta;
    if (j < 0 || j >= value.length) return;
    const next = [...value];
    const [row] = next.splice(i, 1);
    next.splice(j, 0, row);
    onChange(next);
    setAnnounce(`${labelOf(row)} moved to position ${j + 1} of ${next.length}`);
  }

  function remove(i: number) {
    const row = value[i];
    onChange(value.filter((_, x) => x !== i));
    setAnnounce(`${labelOf(row)} removed`);
  }

  function addRow(v: string) {
    onChange([...value, v]);
    setAnnounce(`${labelOf(v)} added at position ${value.length + 1}`);
  }

  return { announce, labelOf, move, remove, addRow };
}
