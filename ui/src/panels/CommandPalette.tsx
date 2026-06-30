// Command palette (Cmd/Ctrl-K): a fast jump-to-anything overlay. Lists the
// pages and the caller's scoped verbs; selecting a page navigates, selecting a
// verb jumps to the Dev console to run it. Pure client; capabilities load lazily
// the first time it opens. Esc closes, arrow keys move, Enter runs.

import { useEffect, useMemo, useRef, useState } from "react";

import { api } from "../api/client";
import { navigate } from "../router";
import { useFetch } from "../useFetch";

interface Cmd {
  id: string;
  label: string;
  hint: string;
  run: () => void;
}

const PAGES: ReadonlyArray<{ id: string; label: string }> = [
  { id: "home", label: "Home" },
  { id: "router", label: "Router" },
  { id: "studio", label: "Studio" },
  { id: "dev", label: "Dev console" },
  { id: "chat", label: "Chat" },
  { id: "kanban", label: "Kanban" },
  { id: "approvals", label: "Approvals" },
  { id: "insight", label: "Insight" },
  { id: "eval", label: "Eval" },
  { id: "memory", label: "Memory" },
  { id: "me", label: "Me" },
  { id: "settings", label: "Settings" },
];

export function CommandPalette() {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [sel, setSel] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

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

  const commands: Cmd[] = useMemo(() => {
    const pages: Cmd[] = PAGES.map((p) => ({
      id: `page:${p.id}`,
      label: p.label,
      hint: "Page",
      run: () => navigate(`/${p.id}`),
    }));
    const verbs: Cmd[] = (caps.data?.verbs ?? []).map((v) => ({
      id: `verb:${v.id}`,
      label: v.id,
      hint: `Run verb (${v.noun})`,
      run: () => navigate("/dev"),
    }));
    return [...pages, ...verbs];
  }, [caps.data]);

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    if (!needle) return commands.slice(0, 30);
    return commands.filter((c) => c.label.toLowerCase().includes(needle)).slice(0, 30);
  }, [commands, q]);

  function choose(c: Cmd | undefined) {
    if (!c) return;
    setOpen(false);
    c.run();
  }

  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setSel((s) => Math.min(s + 1, filtered.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setSel((s) => Math.max(s - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      choose(filtered[sel]);
    }
  }

  if (!open) return null;

  return (
    <div className="cmdk-overlay" onClick={() => setOpen(false)}>
      <div className="cmdk" role="dialog" aria-label="Command palette" onClick={(e) => e.stopPropagation()}>
        <input
          ref={inputRef}
          className="cmdk__input"
          placeholder="Jump to a page or run a verb..."
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setSel(0);
          }}
          onKeyDown={onKeyDown}
          aria-label="Command palette search"
        />
        <ul className="cmdk__list">
          {filtered.length === 0 && <li className="cmdk__empty">No matches.</li>}
          {filtered.map((c, i) => (
            <li key={c.id}>
              <button
                className={`cmdk__item ${i === sel ? "cmdk__item--sel" : ""}`}
                onMouseEnter={() => setSel(i)}
                onClick={() => choose(c)}
              >
                <span className="cmdk__label">{c.label}</span>
                <span className="cmdk__hint">{c.hint}</span>
              </button>
            </li>
          ))}
        </ul>
        <div className="cmdk__foot">
          <kbd>up/down</kbd> move <kbd>enter</kbd> run <kbd>esc</kbd> close
        </div>
      </div>
    </div>
  );
}
