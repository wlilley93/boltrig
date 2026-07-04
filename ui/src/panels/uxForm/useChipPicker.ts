import { useCallback, useId, useMemo, useState } from "react";
import type { Dispatch, KeyboardEvent, SetStateAction } from "react";

import type { ChipOption } from "./ChipPickerChips";
import { useChipPickerKeyboard } from "./useChipPickerKeyboard";

function matchesChipOption(o: ChipOption, value: string[], q: string): boolean {
  if (value.includes(o.value)) return false;
  if (!q) return true;
  return o.value.toLowerCase().includes(q) || (o.label ?? "").toLowerCase().includes(q);
}

export interface UseChipPickerArgs {
  value: string[];
  onChange: (v: string[]) => void;
  options: ChipOption[];
  allowFree: boolean;
  validate?: (v: string) => string | null;
  disabled: boolean;
  searchable: boolean;
}

export interface UseChipPickerResult {
  query: string;
  setQuery: Dispatch<SetStateAction<string>>;
  setActive: Dispatch<SetStateAction<number>>;
  freeError: string | null;
  setFreeError: Dispatch<SetStateAction<string | null>>;
  listId: string;
  cands: ChipOption[];
  act: number;
  addValue: (v: string) => void;
  addFree: () => void;
  onKey: (e: KeyboardEvent<HTMLInputElement>) => void;
  showFreeRow: boolean;
  showInput: boolean;
}

export function useChipPicker({
  value,
  onChange,
  options,
  allowFree,
  validate,
  disabled,
  searchable,
}: UseChipPickerArgs): UseChipPickerResult {
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(-1);
  const [freeError, setFreeError] = useState<string | null>(null);
  const listId = useId();

  const q = query.trim().toLowerCase();
  const cands = useMemo(() => options.filter((o) => matchesChipOption(o, value, q)), [options, value, q]);
  const enabled = useMemo(() => cands.map((c, i) => (c.disabled ? -1 : i)).filter((i) => i >= 0), [cands]);
  const act = active >= 0 && active < cands.length && !cands[active].disabled ? active : -1;

  const addValue = useCallback(
    (v: string) => {
      if (!value.includes(v)) onChange([...value, v]);
      setQuery("");
      setActive(-1);
      setFreeError(null);
    },
    [value, onChange],
  );

  const addFree = useCallback(() => {
    const v = query.trim();
    if (!v) return;
    const err = validate ? validate(v) : null;
    if (err) {
      setFreeError(err);
      return;
    }
    addValue(v);
  }, [query, validate, addValue]);

  const showFreeRow = allowFree && query.trim().length > 0 && !options.some((o) => o.value === query.trim());
  const showInput = searchable && !disabled && (options.length > 0 || allowFree);

  const onKey = useChipPickerKeyboard({
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
  });

  return {
    query,
    setQuery,
    setActive,
    freeError,
    setFreeError,
    listId,
    cands,
    act,
    addValue,
    addFree,
    onKey,
    showFreeRow,
    showInput,
  };
}
