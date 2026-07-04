import type { ReactNode } from "react";

import { EntityPickerPanel } from "./EntityPickerPanel";
import { EntityPickerTrigger } from "./EntityPickerTrigger";
import { useEntityPicker } from "./useEntityPicker";

// --- N4 EntityPicker: reference to one entity, grouped + previewed (P6). ----
// Combobox pattern: a trigger styled as an input opens an in-flow absolute
// panel (no portals; the deck transform breaks position:fixed; z 30 sits
// below drawer 70 / palette 80) with search + grouped listbox. Arrows move,
// Enter selects, Escape closes, outside click closes. renderPreview renders
// the inline preview card under the field once a value is chosen.
export interface EntityItem {
  id: string;
  label?: string;
  badges?: ReactNode;
}

export interface EntityGroup {
  label: string;
  items: EntityItem[];
}

export function EntityPicker({
  value,
  onChange,
  groups,
  placeholder = "Choose...",
  renderPreview,
  disabled = false,
  ariaLabel,
}: {
  value: string | null;
  onChange: (id: string) => void;
  groups: EntityGroup[];
  placeholder?: string;
  renderPreview?: (id: string) => ReactNode;
  disabled?: boolean;
  ariaLabel?: string;
}) {
  const {
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
  } = useEntityPicker({ value, onChange, groups });

  return (
    <div className="ux-picker" ref={rootRef}>
      <EntityPickerTrigger
        value={value}
        placeholder={placeholder}
        current={current}
        ariaLabel={ariaLabel}
        disabled={disabled}
        open={open}
        setOpen={setOpen}
        setQuery={setQuery}
        setActive={setActive}
        triggerRef={triggerRef}
      />
      <EntityPickerPanel
        open={open}
        baseId={baseId}
        query={query}
        setQuery={setQuery}
        active={active}
        setActive={setActive}
        rows={rows}
        value={value}
        choose={choose}
        onKey={onKey}
        ariaLabel={ariaLabel}
      />
      {value && renderPreview && <div className="ux-picker__preview">{renderPreview(value)}</div>}
    </div>
  );
}

