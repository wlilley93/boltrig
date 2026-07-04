import type { Dispatch, MutableRefObject, SetStateAction } from "react";

import type { EntityItem } from "./EntityPicker";

export interface EntityPickerTriggerProps {
  value: string | null;
  placeholder: string;
  current: EntityItem | undefined;
  ariaLabel?: string;
  disabled: boolean;
  open: boolean;
  setOpen: Dispatch<SetStateAction<boolean>>;
  setQuery: Dispatch<SetStateAction<string>>;
  setActive: Dispatch<SetStateAction<number>>;
  triggerRef: MutableRefObject<HTMLButtonElement | null>;
}

export function EntityPickerTrigger({
  value,
  placeholder,
  current,
  ariaLabel,
  disabled,
  open,
  setOpen,
  setQuery,
  setActive,
  triggerRef,
}: EntityPickerTriggerProps) {
  return (
    <button
      type="button"
      ref={triggerRef}
      className="ux-picker__trigger"
      aria-haspopup="listbox"
      aria-expanded={open}
      aria-label={ariaLabel}
      disabled={disabled}
      onClick={() => {
        setQuery("");
        setActive(0);
        setOpen((o) => !o);
      }}
    >
      {value ? (
        <code className="ux-picker__val">{value}</code>
      ) : (
        <span className="ux-picker__ph">{placeholder}</span>
      )}
      {current?.badges}
      <span className="ux-picker__chev" aria-hidden="true">
        ▾
      </span>
    </button>
  );
}
