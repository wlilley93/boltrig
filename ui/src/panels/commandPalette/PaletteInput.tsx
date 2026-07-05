import type { CommandPaletteState } from "./useCommandPalette";

export function PaletteInput({ p }: { p: CommandPaletteState }) {
  const { q, onChangeQuery, onKeyDown, sel, filtered, inputRef } = p;
  return (
    <input
      ref={inputRef}
      className="cmdk__input"
      placeholder="Jump to a page or run a verb..."
      value={q}
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
  );
}
