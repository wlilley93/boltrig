import { useEffect, useMemo, useRef, useState } from "react";
import type { ChatModelChoice } from "@wlilley93/boltrig-web-sdk";
import { modelUnavailableCopy } from "./modelAvailabilityCopy";
interface ModelChipProps {
  choices: ChatModelChoice[];
  defaultModelName?: string | null;
  defaultAvailable?: boolean;
  defaultUnavailableReason?: string | null;
  value: string;
  disabled?: boolean;
  disabledReason?: string;
  onChange(value: string): void;
  onManage?(): void;
}

interface ChipOption {
  id: string;
  label: string;
  available: boolean;
  disambiguator?: string;
  unavailableReason?: string | null;
}

/** The model control as the decided target draws it: a quiet label with a
 * chevron that opens a listbox, replacing the native select while keeping its
 * keyboard and screen-reader contract (combobox/listbox roles, arrow keys,
 * Escape, aria-activedescendant). */
export function ModelChip({
  choices,
  defaultModelName,
  defaultAvailable = Boolean(defaultModelName),
  defaultUnavailableReason,
  value,
  disabled,
  disabledReason,
  onChange,
  onManage,
}: ModelChipProps) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const wrapRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const manageRef = useRef<HTMLButtonElement>(null);

  const options = useMemo<ChipOption[]>(() => [
    {
      id: "",
      label: defaultModelName
        ? `Automatic · ${defaultModelName}`
        : "Automatic",
      available: defaultAvailable,
      unavailableReason: defaultUnavailableReason,
    },
    ...choices.map((item) => ({
      id: item.id,
      label: item.model_name,
      available: item.available,
      // Exact model names remain primary. The otherwise-opaque choice id is
      // exposed only when two routes would be indistinguishable by name.
      disambiguator: choices.filter((candidate) => (
        candidate.model_name === item.model_name
      )).length > 1 ? item.id : undefined,
      unavailableReason: item.unavailable_reason,
    })),
  ], [choices, defaultAvailable, defaultModelName, defaultUnavailableReason]);
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
    if (!option.available) return;
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
      setActive((current) => nextAvailable(options, current, 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive((current) => nextAvailable(options, current, -1));
    } else if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      const option = options[active];
      if (option) choose(option);
    } else if (event.key === "Tab") {
      if (onManage && !event.shiftKey && document.activeElement === buttonRef.current) {
        event.preventDefault();
        manageRef.current?.focus();
      } else {
        setOpen(false);
      }
    }
  }

  return (
    <div className="model-chip-wrap" onKeyDown={onKeyDown} ref={wrapRef}>
      <button
        aria-activedescendant={open ? `worker-model-option-${active}` : undefined}
        aria-controls={open ? "worker-model-listbox" : undefined}
        aria-expanded={open}
        aria-haspopup="listbox"
        aria-label="Model"
        className="model-chip"
        disabled={disabled}
        onClick={() => (open ? setOpen(false) : show())}
        ref={buttonRef}
        title={disabled ? disabledReason : undefined}
        type="button"
      >
        <span>{selected.label}</span>
        {selected.disambiguator && (
          <small className="model-chip-disambiguator">{selected.disambiguator}</small>
        )}
        {!selected.available && <small>Unavailable</small>}
        <svg aria-hidden fill="none" height="12" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.2" viewBox="0 0 24 24" width="12">
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </button>
      {open && (
        <div className="model-menu">
          <div aria-label="Models" id="worker-model-listbox" role="listbox">
            {options.map((option, index) => (
              <button
                aria-disabled={!option.available}
                aria-selected={index === selectedIndex}
                className="model-option"
                data-active={index === active ? "true" : undefined}
                id={`worker-model-option-${index}`}
                key={option.id || "automatic"}
                onClick={() => choose(option)}
                onPointerEnter={() => setActive(index)}
                role="option"
                type="button"
              >
                <span>{option.label}</span>
                {option.disambiguator && <small>{option.disambiguator}</small>}
                {!option.available && (
                  <small title={modelUnavailableCopy(option.unavailableReason)}>Unavailable</small>
                )}
              </button>
            ))}
          </div>
          {onManage && (
            <button
              className="model-manage"
              onClick={() => {
                setOpen(false);
                onManage();
              }}
              ref={manageRef}
              type="button"
            >
              Manage models…
            </button>
          )}
        </div>
      )}
    </div>
  );
}

function nextAvailable(options: ChipOption[], current: number, direction: 1 | -1) {
  let next = current;
  for (let checked = 0; checked < options.length; checked += 1) {
    next = (next + direction + options.length) % options.length;
    if (options[next]?.available) return next;
  }
  return current;
}
