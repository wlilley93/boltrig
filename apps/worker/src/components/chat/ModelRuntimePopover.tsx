import type { RefObject } from "react";

import { modelUnavailableCopy } from "./modelAvailabilityCopy";
import type { ChipOption } from "./modelChipOptions";

interface ModelRuntimePopoverProps {
  active: number;
  canReset: boolean;
  listboxRef: RefObject<HTMLDivElement | null>;
  onBack(): void;
  onChoose(option: ChipOption): void;
  onManage?(): void;
  onModelView(): void;
  onPointerOption(index: number): void;
  options: ChipOption[];
  selected: ChipOption;
  selectedIndex: number;
  view: "overview" | "models";
}

export function ModelRuntimePopover(props: ModelRuntimePopoverProps) {
  return (
    <div className="model-runtime-popover">
      {props.view === "overview"
        ? <RuntimeOverview {...props} />
        : <ModelOptions {...props} />}
    </div>
  );
}

function RuntimeOverview(props: ModelRuntimePopoverProps) {
  return (
    <div aria-label="Model and runtime" className="model-runtime-overview" role="menu">
      <button
        aria-label="Choose model"
        className="model-runtime-row"
        onClick={props.onModelView}
        role="menuitem"
        type="button"
      >
        <span>Model</span>
        <RuntimeValue value={props.selected.label} />
        <Chevron />
      </button>
      <RuntimeFact
        label="Effort"
        title="Reasoning effort is fixed by the trusted runtime admission policy."
        value="Workspace policy"
      />
      <RuntimeFact
        label="Speed"
        title="Request priority is managed by the configured model gateway."
        value="Gateway managed"
      />
      <div className="model-runtime-rule" />
      <button
        className="model-runtime-reset"
        disabled={!props.canReset}
        onClick={() => props.onChoose(props.options[0]!)}
        role="menuitem"
        type="button"
      >
        <span>Reset to Automatic</span>
        <ResetIcon />
      </button>
      {props.onManage && (
        <button
          className="model-runtime-manage"
          onClick={props.onManage}
          role="menuitem"
          type="button"
        >
          Manage models…
        </button>
      )}
    </div>
  );
}

function ModelOptions(props: ModelRuntimePopoverProps) {
  return (
    <div className="model-runtime-models">
      <button aria-label="Back to runtime settings" className="model-runtime-back" onClick={props.onBack} type="button">
        <Chevron back />
        <span>Model</span>
      </button>
      <div
        aria-activedescendant={`worker-model-option-${props.active}`}
        aria-label="Models"
        className="model-runtime-listbox"
        id="worker-model-listbox"
        ref={props.listboxRef}
        role="listbox"
        tabIndex={0}
      >
        {props.options.map((option, index) => (
          <button
            aria-disabled={!option.available}
            aria-selected={index === props.selectedIndex}
            className="model-option"
            data-active={index === props.active ? "true" : undefined}
            id={`worker-model-option-${index}`}
            key={option.id || "automatic"}
            onClick={() => props.onChoose(option)}
            onPointerEnter={() => props.onPointerOption(index)}
            role="option"
            type="button"
          >
            <span>{option.label}</span>
            {option.disambiguator && <small>{option.disambiguator}</small>}
            {!option.available && (
              <small title={modelUnavailableCopy(option.unavailableReason)}>Unavailable</small>
            )}
            {index === props.selectedIndex && <CheckIcon />}
          </button>
        ))}
      </div>
    </div>
  );
}

function RuntimeFact({ label, title, value }: { label: string; title: string; value: string }) {
  return (
    <div className="model-runtime-row model-runtime-fact" title={title}>
      <span>{label}</span>
      <RuntimeValue value={value} />
      <LockIcon />
    </div>
  );
}

function RuntimeValue({ value }: { value: string }) {
  return <small title={value}>{value}</small>;
}

function Chevron({ back = false }: { back?: boolean }) {
  return (
    <svg aria-hidden fill="none" height="13" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" viewBox="0 0 24 24" width="13">
      <polyline points={back ? "15 18 9 12 15 6" : "9 18 15 12 9 6"} />
    </svg>
  );
}

function LockIcon() {
  return (
    <svg aria-hidden fill="none" height="12" stroke="currentColor" strokeWidth="1.8" viewBox="0 0 24 24" width="12">
      <rect height="10" rx="2" width="14" x="5" y="10" />
      <path d="M8 10V7a4 4 0 0 1 8 0v3" />
    </svg>
  );
}

function ResetIcon() {
  return (
    <svg aria-hidden fill="none" height="13" stroke="currentColor" strokeLinecap="round" strokeWidth="1.8" viewBox="0 0 24 24" width="13">
      <path d="M4 4v6h6" />
      <path d="M5.5 15a7 7 0 1 0 1.1-8.2L4 10" />
    </svg>
  );
}

function CheckIcon() {
  return (
    <svg aria-hidden className="model-option-check" fill="none" height="13" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.2" viewBox="0 0 24 24" width="13">
      <polyline points="5 12 10 17 19 7" />
    </svg>
  );
}
