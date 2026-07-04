import { useCallback, useId, useMemo, useState } from "react";
import type { Dispatch, KeyboardEvent, SetStateAction } from "react";

import type { ChipOption } from "./ChipPickerChips";

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
  active: number;
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
  const cands = useMemo(
    () =>
      options.filter(
        (o) =>
          !value.includes(o.value) &&
          (!q || o.value.toLowerCase().includes(q) || (o.label ?? "").toLowerCase().includes(q)),
      ),
    [options, value, q],
  );
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

  const onKey = useCallback(
    (e: KeyboardEvent<HTMLInputElement>) => {
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
    },
    [query, value, onChange, enabled, act, cands, allowFree, addValue, addFree],
  );

  return {
    query,
    setQuery,
    active,
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
