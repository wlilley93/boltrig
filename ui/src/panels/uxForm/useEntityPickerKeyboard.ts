import type { KeyboardEvent, MutableRefObject } from "react";

export interface UseEntityPickerKeyboardArgs<T extends { item: { id: string } }> {
  rows: T[];
  active: number;
  setActive: (fn: (v: number) => number) => void;
  setOpen: (fn: (v: boolean) => boolean) => void;
  choose: (id: string) => void;
  triggerRef: MutableRefObject<HTMLButtonElement | null>;
}

export function useEntityPickerKeyboard<T extends { item: { id: string } }>({
  rows,
  active,
  setActive,
  setOpen,
  choose,
  triggerRef,
}: UseEntityPickerKeyboardArgs<T>) {
  return (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((a) => Math.min(a + 1, rows.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => Math.max(a - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const row = rows[active];
      if (row) choose(row.item.id);
    } else if (e.key === "Escape") {
      e.preventDefault();
      setOpen((o) => !o);
      triggerRef.current?.focus();
    }
  };
}
