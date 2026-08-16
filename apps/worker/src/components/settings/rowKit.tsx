import { useId, useState } from "react";

import { setDeveloperDetails, useDeveloperDetails } from "./devDetails";
import "./settings-kit.css";

// The typed row-control kit the decided target draws every settings row with:
// toggle switch, native select, segmented control, action button, inline
// input, status-word-plus-switch, and read-only value. Sections compose these
// into SettingsRow controls instead of hand-rolling markup, so every switch
// and segment reads identically across the family.

export type Tone = "green" | "amber" | "red" | "unknown";

export function SettingsGroup({ title, eyebrow = false, children, advanced, foot }: {
  title?: string;
  /** Uppercase small label above the card, as the custom screens draw it. */
  eyebrow?: boolean;
  children?: React.ReactNode;
  /** Keyed rows kept behind "N more, for when you need them". */
  advanced?: React.ReactNode[];
  foot?: React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const extra = (advanced ?? []).filter(Boolean);
  return (
    <div className="settings-group">
      {title && (
        <div className={eyebrow ? "settings-group-eyebrow" : "console-section-title"}>{title}</div>
      )}
      <div className="console-table">
        {children}
        {open && extra}
        {extra.length > 0 && (
          <button
            aria-expanded={open}
            className="settings-disclose"
            onClick={() => setOpen((current) => !current)}
            type="button"
          >
            <i aria-hidden>›</i>
            <span>{open ? "Hide advanced" : `${extra.length} more, for when you need them`}</span>
          </button>
        )}
      </div>
      {foot && <p className="console-foot">{foot}</p>}
    </div>
  );
}

export function SettingsRow({ title, desc, tech, control }: {
  title: string;
  desc?: string;
  tech?: string;
  control?: React.ReactNode;
}) {
  // Tech identifiers only appear when the persisted Developer-details
  // preference is on — the same gate for every chip in the app.
  const showTech = useDeveloperDetails();
  return (
    <div className="settings-row">
      <div className="settings-row-main">
        <div className="console-row-title">
          <span>{title}</span>
          {tech && showTech && <span className="console-tech">{tech}</span>}
        </div>
        {desc && <div className="settings-row-desc">{desc}</div>}
      </div>
      {control}
    </div>
  );
}

export function SettingsToggle({ on, onToggle, label, disabled = false }: {
  on: boolean;
  onToggle(next: boolean): void;
  /** Names the switch for assistive tech; the row title is not programmatically linked. */
  label: string;
  disabled?: boolean;
}) {
  return (
    <button
      aria-checked={on}
      aria-label={label}
      className="settings-switch"
      disabled={disabled}
      onClick={() => onToggle(!on)}
      role="switch"
      type="button"
    >
      <i aria-hidden />
    </button>
  );
}

export function SettingsInfo({ label, text }: { label: string; text: string }) {
  const tooltipId = useId();
  return (
    <span className="settings-info-wrap">
      <button
        aria-describedby={tooltipId}
        aria-label={label}
        className="settings-info"
        type="button"
      >
        <svg aria-hidden fill="none" height="11" stroke="currentColor" strokeLinecap="round" strokeWidth="2" viewBox="0 0 16 16" width="11">
          <circle cx="8" cy="8" r="6" />
          <path d="M8 7v4M8 4.5h.01" />
        </svg>
      </button>
      <span className="settings-info-tip" id={tooltipId} role="tooltip">{text}</span>
    </span>
  );
}

export function SettingsSelect({ value, options, onChange, label, disabled = false }: {
  value: string;
  options: string[];
  onChange(next: string): void;
  label: string;
  disabled?: boolean;
}) {
  return (
    <div className="settings-select">
      <select
        aria-label={label}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
        value={value}
      >
        {options.map((option) => <option key={option} value={option}>{option}</option>)}
      </select>
      <svg aria-hidden fill="none" height="12" stroke="var(--text-3)" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.2" viewBox="0 0 24 24" width="12">
        <polyline points="6 9 12 15 18 9" />
      </svg>
    </div>
  );
}

export function SettingsSegmented({ value, options, onChange, label, disabled = false }: {
  value: string;
  options: string[];
  onChange(next: string): void;
  label: string;
  disabled?: boolean;
}) {
  return (
    <div aria-label={label} className="settings-seg" role="group">
      {options.map((option) => (
        <button
          aria-pressed={option === value}
          disabled={disabled}
          key={option}
          onClick={() => onChange(option)}
          type="button"
        >
          {option}
        </button>
      ))}
    </div>
  );
}

export function SettingsButton({ label, onClick, tone, disabled = false, title }: {
  label: string;
  onClick(): void;
  tone?: "danger";
  disabled?: boolean;
  title?: string;
}) {
  return (
    <button
      className="settings-kit-button"
      data-tone={tone}
      disabled={disabled}
      onClick={onClick}
      title={title}
      type="button"
    >
      {label}
    </button>
  );
}

export function SettingsInput({ value, onChange, label, placeholder }: {
  value: string;
  onChange(next: string): void;
  label: string;
  placeholder?: string;
}) {
  return (
    <input
      aria-label={label}
      className="settings-inline-input"
      onChange={(event) => onChange(event.target.value)}
      placeholder={placeholder}
      value={value}
    />
  );
}

export function StateWord({ tone, children }: { tone: Tone; children: React.ReactNode }) {
  return <span className="settings-state-word" data-tone={tone}>{children}</span>;
}

export function SettingsStatus({ state, tone, on, onToggle, label }: {
  state: string;
  tone: Tone;
  on: boolean;
  onToggle(next: boolean): void;
  label: string;
}) {
  return (
    <div className="settings-status">
      <StateWord tone={tone}>{state}</StateWord>
      <SettingsToggle label={label} on={on} onToggle={onToggle} />
    </div>
  );
}

/** A humanised reading: tone dot, plain title and sub, short state word. */
export function ToneRow({ title, sub, tone, state, tech }: {
  title: string;
  sub?: string;
  tone: Tone;
  state: string;
  tech?: string;
}) {
  const showTech = useDeveloperDetails();
  return (
    <div className="settings-tone-row">
      <span aria-hidden className="settings-tone-dot" data-tone={tone} />
      <div className="settings-tone-main">
        <span className="settings-tone-title">
          <span>{title}</span>
          {tech && showTech && <span className="console-tech">{tech}</span>}
        </span>
        {sub && <span className="settings-tone-sub">{sub}</span>}
      </div>
      <StateWord tone={tone}>{state}</StateWord>
    </div>
  );
}

/** The persisted Developer-details switch as a ready-made row. */
export function DeveloperDetailsRow() {
  const on = useDeveloperDetails();
  const [message, setMessage] = useState("");
  return (
    <SettingsRow
      control={(
        <SettingsToggle
          label="Developer details"
          on={on}
          onToggle={(next) => {
            setMessage("");
            void setDeveloperDetails(next).then((stored) => {
              if (!stored) setMessage("The preference could not be saved.");
            });
          }}
        />
      )}
      desc={message || "Shows the identifiers behind each row, throughout the app."}
      title="Developer details"
    />
  );
}
