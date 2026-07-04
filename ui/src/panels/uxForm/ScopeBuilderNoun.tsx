import type { Dispatch, SetStateAction } from "react";

import type { ScopeVerb } from "./scopeMatches";
import { ScopeBuilderVerbList } from "./ScopeBuilderVerbList";

export interface ScopeBuilderNounProps {
  noun: string;
  list: ScopeVerb[];
  value: string[];
  openNouns: Record<string, boolean>;
  setOpenNouns: Dispatch<SetStateAction<Record<string, boolean>>>;
  q: string;
  disabled: boolean;
  add: (p: string) => void;
  onChange: (v: string[]) => void;
}

export function ScopeBuilderNoun({
  noun,
  list,
  value,
  openNouns,
  setOpenNouns,
  q,
  disabled,
  add,
  onChange,
}: ScopeBuilderNounProps) {
  const hits = q ? list.filter((v) => v.id.toLowerCase().includes(q)) : list;
  if (q && hits.length === 0 && !noun.toLowerCase().includes(q)) return null;
  const shown = q && hits.length > 0 ? hits : list;
  const open = q ? true : (openNouns[noun] ?? false);
  const pattern = `${noun}.*`;

  const addAll = () => {
    const next = [...value];
    for (const v of list) if (!next.includes(v.id)) next.push(v.id);
    onChange(next);
  };

  return (
    <div key={noun} className="ux-scope__noun">
      <div className="ux-scope__nounrow">
        <button
          type="button"
          className="ux-scope__toggle"
          aria-expanded={open}
          onClick={() => setOpenNouns((m) => ({ ...m, [noun]: !open }))}
        >
          <span className="ux-scope__caret" aria-hidden="true">
            {open ? "▾" : "▸"}
          </span>
          <span className="ux-scope__nounname">{noun}</span>
          <span className="ux-scope__count">
            {list.length} {list.length === 1 ? "verb" : "verbs"}
          </span>
        </button>
        <button
          type="button"
          className="btn btn--sm btn--ghost"
          disabled={disabled || value.includes(pattern)}
          title="A pattern also covers verbs added to this noun later."
          onClick={() => add(pattern)}
        >
          Add {pattern}
        </button>
        <button
          type="button"
          className="btn btn--sm btn--ghost"
          disabled={disabled}
          onClick={addAll}
        >
          Add {list.length} individually
        </button>
      </div>
      {open && <ScopeBuilderVerbList shown={shown} value={value} disabled={disabled} add={add} />}
    </div>
  );
}
