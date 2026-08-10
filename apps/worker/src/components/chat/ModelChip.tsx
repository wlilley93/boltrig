import { useEffect, useMemo, useRef, useState } from "react";
import type { ModelProfile } from "@wlilley93/boltrig-web-sdk";

interface ModelChipProps {
  profiles: ModelProfile[];
  value: string;
  disabled?: boolean;
  /** Developer detail: label the chip and its options with raw profile ids. */
  tech: boolean;
  onChange(value: string): void;
}

interface ChipOption {
  id: string;
  label: string;
  techLabel: string;
}

/** The model control as the decided target draws it: a quiet label with a
 * chevron that opens a listbox, replacing the native select while keeping its
 * keyboard and screen-reader contract (combobox/listbox roles, arrow keys,
 * Escape, aria-activedescendant). */
export function ModelChip({ profiles, value, disabled, tech, onChange }: ModelChipProps) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const wrapRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);

  const options = useMemo<ChipOption[]>(() => [
    { id: "", label: "Best available", techLabel: "best-available" },
    ...profiles.map((item) => ({ id: item.id, label: item.label, techLabel: item.id })),
  ], [profiles]);
  const selectedIndex = Math.max(0, options.findIndex((option) => option.id === value));
  const selected = options[selectedIndex];

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!wrapRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [open]);

  function show() {
    setActive(selectedIndex);
    setOpen(true);
  }

  function choose(option: ChipOption) {
    onChange(option.id);
    setOpen(false);
    buttonRef.current?.focus();
  }

  function onKeyDown(event: React.KeyboardEvent) {
    if (!open) {
      if (["ArrowDown", "ArrowUp", "Enter", " "].includes(event.key)) {
        event.preventDefault();
        show();
      }
      return;
    }
    if (event.key === "Escape") {
      event.preventDefault();
      setOpen(false);
      buttonRef.current?.focus();
    } else if (event.key === "ArrowDown") {
      event.preventDefault();
      setActive((current) => Math.min(options.length - 1, current + 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive((current) => Math.max(0, current - 1));
    } else if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      const option = options[active];
      if (option) choose(option);
    } else if (event.key === "Tab") {
      setOpen(false);
    }
  }

  return (
    <div className="model-chip-wrap" onKeyDown={onKeyDown} ref={wrapRef}>
      <button
        aria-activedescendant={open ? `worker-model-option-${active}` : undefined}
        aria-controls={open ? "worker-model-listbox" : undefined}
        aria-expanded={open}
        aria-haspopup="listbox"
        aria-label="Model profile"
        className={`model-chip${tech ? " model-chip-tech" : ""}`}
        disabled={disabled}
        onClick={() => (open ? setOpen(false) : show())}
        ref={buttonRef}
        type="button"
      >
        <span>{tech ? selected.techLabel : selected.label}</span>
        <svg aria-hidden fill="none" height="12" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.2" viewBox="0 0 24 24" width="12">
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </button>
      {open && (
        <div
          aria-label="Model profiles"
          className="model-menu"
          id="worker-model-listbox"
          role="listbox"
        >
          {options.map((option, index) => (
            <button
              aria-selected={index === selectedIndex}
              className={tech ? "model-option model-chip-tech" : "model-option"}
              data-active={index === active ? "true" : undefined}
              id={`worker-model-option-${index}`}
              key={option.id || "best-available"}
              onClick={() => choose(option)}
              onPointerEnter={() => setActive(index)}
              role="option"
              type="button"
            >
              {tech ? option.techLabel : option.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
