import type { CommandPaletteState } from "./useCommandPalette";

export function CommandResultsList({ p }: { p: CommandPaletteState }) {
  const { filtered, sel, setSel, choose } = p;
  return (
    <ul className="cmdk__list" id="cmdk-listbox" role="listbox" aria-label="Results">
      {filtered.length === 0 && <li className="cmdk__empty">No matches.</li>}
      {filtered.map((c, i) => (
        <li key={c.id} role="presentation">
          <button
            id={`cmdk-opt-${i}`}
            role="option"
            aria-selected={i === sel}
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
  );
}
