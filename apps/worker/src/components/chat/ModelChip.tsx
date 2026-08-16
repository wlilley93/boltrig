import { useEffect, useRef, useState } from "react";
import type { ChatModelChoice } from "@wlilley93/boltrig-web-sdk";

import "./ModelChip.css";
import { ModelRuntimePopover } from "./ModelRuntimePopover";
import { nextAvailable } from "./modelChipOptions";
import type { ChipOption } from "./modelChipOptions";
import { useModelChipOptions } from "./useModelChipOptions";

interface ModelChipProps {
  choices: ChatModelChoice[];
  defaultModelName?: string | null;
  defaultModelSource?: "personal" | "platform";
  defaultAvailable?: boolean;
  defaultUnavailableReason?: string | null;
  value: string;
  disabled?: boolean;
  disabledReason?: string;
  onChange(value: string): void;
  onManage?(): void;
}

export function ModelChip(props: ModelChipProps) {
  const [open, setOpen] = useState(false);
  const [view, setView] = useState<"overview" | "models">("overview");
  const [active, setActive] = useState(0);
  const wrapRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const listboxRef = useRef<HTMLDivElement>(null);
  const options = useModelChipOptions(props);
  const selectedIndex = Math.max(0, options.findIndex((option) => option.id === props.value));
  const selected = options[selectedIndex]!;

  useOutsideClose(open, wrapRef, close);
  useEffect(() => {
    if (open && view === "models") listboxRef.current?.focus();
  }, [open, view]);

  function close() {
    setOpen(false);
    setView("overview");
  }

  function show(initialView: "overview" | "models" = "overview") {
    setActive(selectedIndex);
    setView(initialView);
    setOpen(true);
  }

  function choose(option: ChipOption) {
    if (!option.available) return;
    props.onChange(option.id);
    close();
    buttonRef.current?.focus();
  }

  function onKeyDown(event: React.KeyboardEvent) {
    if (!open) return handleClosedKey(event, show);
    if (event.key === "Escape") {
      event.preventDefault();
      close();
      buttonRef.current?.focus();
    } else if (view === "models") {
      handleModelKey({
        active,
        back: () => setView("overview"),
        choose,
        event,
        options,
        setActive,
      });
    }
  }

  return (
    <div className="model-chip-wrap" onKeyDown={onKeyDown} ref={wrapRef}>
      <button
        aria-controls={open ? "worker-model-runtime-menu" : undefined}
        aria-expanded={open}
        aria-haspopup="menu"
        aria-label="Model"
        className="model-chip"
        disabled={props.disabled}
        onClick={() => (open ? close() : show())}
        ref={buttonRef}
        title={props.disabled ? props.disabledReason : selected.label}
        type="button"
      >
        <BoltIcon />
        <span>{selected.label}</span>
        {selected.disambiguator && <small>{selected.disambiguator}</small>}
        {!selected.available && <small>Unavailable</small>}
        <DownIcon />
      </button>
      {open && (
        <div id="worker-model-runtime-menu">
          <ModelRuntimePopover
            active={active}
            canReset={Boolean(props.value) && options[0]!.available}
            listboxRef={listboxRef}
            onBack={() => setView("overview")}
            onChoose={choose}
            onManage={props.onManage ? () => { close(); props.onManage?.(); } : undefined}
            onModelView={() => setView("models")}
            onPointerOption={setActive}
            options={options}
            selected={selected}
            selectedIndex={selectedIndex}
            view={view}
          />
        </div>
      )}
    </div>
  );
}

function useOutsideClose(
  open: boolean, wrapRef: React.RefObject<HTMLDivElement | null>, close: () => void,
) {
  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!wrapRef.current?.contains(event.target as Node)) close();
    };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [close, open, wrapRef]);
}

function handleClosedKey(
  event: React.KeyboardEvent, show: (view?: "overview" | "models") => void,
) {
  if (!["ArrowDown", "ArrowUp", "Enter", " "].includes(event.key)) return;
  event.preventDefault();
  show(event.key.startsWith("Arrow") ? "models" : "overview");
}

interface ModelKeyContext {
  active: number;
  back(): void;
  choose(option: ChipOption): void;
  event: React.KeyboardEvent;
  options: ChipOption[];
  setActive(index: number): void;
}

function handleModelKey({ active, back, choose, event, options, setActive }: ModelKeyContext) {
  if (event.key === "ArrowDown" || event.key === "ArrowUp") {
    event.preventDefault();
    setActive(nextAvailable(options, active, event.key === "ArrowDown" ? 1 : -1));
  } else if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    const option = options[active];
    if (option) choose(option);
  } else if (event.key === "ArrowLeft" || event.key === "Backspace") {
    event.preventDefault();
    back();
  }
}

function BoltIcon() {
  return <svg aria-hidden className="model-chip-bolt" height="13" viewBox="0 0 24 24" width="13"><path d="M13.4 1.8 4.7 13h6l-1 9.2L19.3 10h-6.1l.2-8.2Z" /></svg>;
}

function DownIcon() {
  return <svg aria-hidden fill="none" height="12" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.2" viewBox="0 0 24 24" width="12"><polyline points="6 9 12 15 18 9" /></svg>;
}
