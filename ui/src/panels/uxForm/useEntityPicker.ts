import { useEffect, useId, useMemo, useRef, useState } from "react";
import type { Dispatch, KeyboardEvent, MutableRefObject, SetStateAction } from "react";

import type { EntityGroup, EntityItem } from "./EntityPicker";
import { useEntityPickerKeyboard } from "./useEntityPickerKeyboard";

export interface UseEntityPickerArgs {
  value: string | null;
  onChange: (id: string) => void;
  groups: EntityGroup[];
}

export interface UseEntityPickerResult {
  open: boolean;
  setOpen: Dispatch<SetStateAction<boolean>>;
  query: string;
  setQuery: Dispatch<SetStateAction<string>>;
  active: number;
  setActive: Dispatch<SetStateAction<number>>;
  rootRef: MutableRefObject<HTMLDivElement | null>;
  triggerRef: MutableRefObject<HTMLButtonElement | null>;
  baseId: string;
  rows: { group: string; first: boolean; item: EntityItem }[];
  current: EntityItem | undefined;
  choose: (id: string) => void;
  onKey: (e: KeyboardEvent<HTMLInputElement>) => void;
}

export function useEntityPicker({ value, onChange, groups }: UseEntityPickerArgs): UseEntityPickerResult {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const baseId = useId();

  const rows = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const out: { group: string; first: boolean; item: EntityItem }[] = [];
    for (const g of groups) {
      let first = true;
      for (const it of g.items) {
        if (needle && !`${it.id} ${it.label ?? ""}`.toLowerCase().includes(needle)) continue;
        out.push({ group: g.label, first, item: it });
        first = false;
      }
    }
    return out;
  }, [groups, query]);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    document.getElementById(`${baseId}-o${active}`)?.scrollIntoView({ block: "nearest" });
  }, [open, active, baseId]);

  const current = useMemo(() => {
    for (const g of groups) for (const it of g.items) if (it.id === value) return it;
    return undefined;
  }, [groups, value]);

  const choose = (id: string) => {
    onChange(id);
    setOpen(false);
    setQuery("");
    triggerRef.current?.focus();
  };

  const onKey = useEntityPickerKeyboard({ rows, active, setActive, setOpen, choose, triggerRef });

  return {
    open,
    setOpen,
    query,
    setQuery,
    active,
    setActive,
    rootRef,
    triggerRef,
    baseId,
    rows,
    current,
    choose,
    onKey,
  };
}
