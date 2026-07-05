import { useEffect, useRef, useState } from "react";

import { api } from "@/api/client";
import { useFetch } from "@/useFetch";

import { usePaletteCommands, type Cmd } from "./usePaletteCommands";

export function useCommandPalette() {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [sel, setSel] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);

  // capabilities only fetch once the palette is first opened.
  const [armed, setArmed] = useState(false);
  const caps = useFetch(() => (armed ? api.capabilities() : Promise.resolve(null)), [armed]);

  // global hotkey: Cmd/Ctrl-K toggles; a visible control dispatches the same open
  // via a custom event, so the palette is discoverable, not just a hidden hotkey.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const k = e.key.toLowerCase();
      if ((e.metaKey || e.ctrlKey) && k === "k") {
        e.preventDefault();
        setOpen((v) => !v);
        setArmed(true);
      } else if (e.key === "Escape") {
        setOpen(false);
      }
    }
    function onOpen() {
      setOpen(true);
      setArmed(true);
    }
    window.addEventListener("keydown", onKey);
    window.addEventListener("boltrig:open-palette", onOpen);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("boltrig:open-palette", onOpen);
    };
  }, []);

  useEffect(() => {
    if (open) {
      setQ("");
      setSel(0);
      setArmed(true);
      // focus after paint
      const t = window.setTimeout(() => inputRef.current?.focus(), 0);
      return () => window.clearTimeout(t);
    }
  }, [open]);

  const { filtered } = usePaletteCommands(caps.data, q);

  function choose(c: Cmd | undefined) {
    if (!c) return;
    setOpen(false);
    c.run();
  }

  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setSel((s) => Math.max(0, Math.min(s + 1, filtered.length - 1)));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setSel((s) => Math.max(s - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      choose(filtered[sel]);
    }
  }

  function onChangeQuery(v: string) {
    setQ(v);
    setSel(0);
  }

  return {
    open, setOpen, q, sel, setSel, filtered, inputRef, dialogRef,
    onChangeQuery, onKeyDown, choose,
  };
}

export type CommandPaletteState = ReturnType<typeof useCommandPalette>;
