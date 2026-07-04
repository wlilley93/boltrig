import { Fragment } from "react";
import type { Dispatch, KeyboardEvent, SetStateAction } from "react";

import type { EntityItem } from "./EntityPicker";

export interface EntityPickerPanelProps {
  open: boolean;
  baseId: string;
  query: string;
  setQuery: Dispatch<SetStateAction<string>>;
  active: number;
  setActive: Dispatch<SetStateAction<number>>;
  rows: { group: string; first: boolean; item: EntityItem }[];
  value: string | null;
  choose: (id: string) => void;
  onKey: (e: KeyboardEvent<HTMLInputElement>) => void;
  ariaLabel?: string;
}

export function EntityPickerPanel({
  open,
  baseId,
  query,
  setQuery,
  active,
  setActive,
  rows,
  value,
  choose,
  onKey,
  ariaLabel,
}: EntityPickerPanelProps) {
  if (!open) return null;
  return (
    <div className="ux-picker__panel">
      <input
        autoFocus
        role="combobox"
        aria-expanded="true"
        aria-controls={`${baseId}-list`}
        aria-activedescendant={rows.length > 0 ? `${baseId}-o${active}` : undefined}
        aria-label={ariaLabel ?? "Search"}
        value={query}
        placeholder="Type to search..."
        onChange={(e) => {
          setQuery(e.target.value);
          setActive(0);
        }}
        onKeyDown={onKey}
      />
      <div className="ux-picker__list" role="listbox" id={`${baseId}-list`}>
        {rows.length === 0 && <span className="ux-picker__none">No matches.</span>}
        {rows.map((r, i) => (
          <Fragment key={r.item.id}>
            {r.first && (
              <div className="ux-picker__group" role="presentation">
                {r.group}
              </div>
            )}
            <button
              type="button"
              id={`${baseId}-o${i}`}
              role="option"
              aria-selected={r.item.id === value}
              tabIndex={-1}
              className={`ux-picker__opt ${i === active ? "ux-picker__opt--act" : ""}`}
              onClick={() => choose(r.item.id)}
            >
              <code>{r.item.id}</code>
              {r.item.label && <span className="ux-picker__optlabel">{r.item.label}</span>}
              {r.item.badges}
            </button>
          </Fragment>
        ))}
      </div>
    </div>
  );
}
