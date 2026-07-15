import type { CommandPaletteState } from "./useCommandPalette";

const FILTERS = [
  { id: "all", label: "All" },
  { id: "page", label: "Pages" },
  { id: "workflow", label: "Workflows" },
  { id: "run", label: "Runs" },
  { id: "verb", label: "Verbs" },
] as const;

export function PaletteInput({ p }: { p: CommandPaletteState }) {
  const { q, onChangeQuery, onKeyDown, sel, filtered, inputRef, kind, setKind } = p;
  return (
    <>
      <input
        ref={inputRef}
        className="cmdk__input"
        placeholder="Search pages, workflows, runs, and verbs..."
        value={q}
        autoComplete="off"
        spellCheck={false}
        onChange={(e) => onChangeQuery(e.target.value)}
        onKeyDown={onKeyDown}
        aria-label="Command palette search"
        role="combobox"
        aria-expanded={true}
        aria-controls="cmdk-listbox"
        aria-autocomplete="list"
        aria-activedescendant={
          filtered.length > 0 ? `cmdk-opt-${sel}` : undefined
        }
      />
      <div className="subtabs" role="toolbar" aria-label="Command filters">
        {FILTERS.map((filter) => (
          <button
            key={filter.id}
            type="button"
            className={`subtab ${kind === filter.id ? "subtab--active" : ""}`}
            aria-pressed={kind === filter.id}
            onClick={() => setKind(filter.id)}
          >
            {filter.label}
          </button>
        ))}
      </div>
    </>
  );
}
