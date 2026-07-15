import { useEffect, useRef, useState } from "react";

import { api } from "@/api/client";
import { useIdentity } from "@/identity";
import { useFetch } from "@/useFetch";

import {
  usePaletteCommands,
  type Cmd,
  type CommandKind,
} from "./usePaletteCommands";

export function useCommandPalette() {
  const identity = useIdentity();
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [sel, setSel] = useState(0);
  const [kind, setKindState] = useState<CommandKind>("all");
  const inputRef = useRef<HTMLInputElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);

  // capabilities only fetch once the palette is first opened.
  const [armed, setArmed] = useState(false);
  const caps = useFetch(() => (armed ? api.capabilities() : Promise.resolve(null)), [armed]);
  const workflows = useFetch(() => (armed ? api.workflows() : Promise.resolve(null)), [armed]);
  const runs = useFetch(() => (armed ? api.runs() : Promise.resolve(null)), [armed]);

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
      setKindState("all");
      setArmed(true);
      // focus after paint
      const t = window.setTimeout(() => inputRef.current?.focus(), 0);
      return () => window.clearTimeout(t);
    }
  }, [open]);

  const { filtered } = usePaletteCommands(
    caps.data,
    workflows.data,
    runs.data,
    identity.role,
    q,
    kind,
  );

  useEffect(() => {
    setSel((current) =>
      filtered.length === 0 ? 0 : Math.min(current, filtered.length - 1),
    );
  }, [filtered.length]);

  useEffect(() => {
    if (!open || filtered.length === 0) return;
    document
      .getElementById(`cmdk-opt-${sel}`)
      ?.scrollIntoView?.({ block: "nearest" });
  }, [open, sel, filtered.length]);

  function choose(c: Cmd | undefined) {
    if (!c) return;
    setOpen(false);
    c.run();
  }

  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      if (filtered.length > 0) setSel((s) => (s + 1) % filtered.length);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      if (filtered.length > 0) {
        setSel((s) => (s - 1 + filtered.length) % filtered.length);
      }
    } else if (e.key === "Home") {
      e.preventDefault();
      setSel(0);
    } else if (e.key === "End") {
      e.preventDefault();
      if (filtered.length > 0) setSel(filtered.length - 1);
    } else if (e.key === "Enter") {
      e.preventDefault();
      choose(filtered[sel]);
    }
  }

  function onChangeQuery(v: string) {
    setQ(v);
    setSel(0);
  }

  function setKind(next: CommandKind) {
    setKindState(next);
    setSel(0);
  }

  return {
    open, setOpen, q, sel, setSel, kind, setKind, filtered, inputRef, dialogRef,
    onChangeQuery, onKeyDown, choose,
  };
}

export type CommandPaletteState = ReturnType<typeof useCommandPalette>;
