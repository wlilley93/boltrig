import { useEffect, useId, useRef, useState } from "react";

export interface SearchableOption {
  value: string;
  label: string;
  detail?: string;
  info?: string;
}

export function SearchablePicker({
  disabled = false,
  emptyText,
  label,
  onChange,
  options,
  placeholder,
  searchLabel,
  value,
}: {
  disabled?: boolean;
  emptyText: string;
  label: string;
  onChange: (value: string) => void;
  options: SearchableOption[];
  placeholder: string;
  searchLabel: string;
  value: string;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [menuLayout, setMenuLayout] = useState<PickerMenuLayout>({
    placement: "down",
    optionsHeight: 250,
  });
  const root = useRef<HTMLDivElement>(null);
  const search = useRef<HTMLInputElement>(null);
  const listId = useId();
  const selected = options.find((option) => option.value === value);
  const filtered = filterOptions(options, query);

  useEffect(() => pickerDismissal(open, root, () => {
    setOpen(false);
    setQuery("");
  }), [open]);
  useEffect(() => { if (open) search.current?.focus(); }, [open]);

  function choose(next: string) {
    onChange(next);
    setOpen(false);
    setQuery("");
  }

  function toggle() {
    if (!open) setMenuLayout(measurePickerMenu(root.current));
    if (open) setQuery("");
    setOpen((current) => !current);
  }

  return (
    <div className="onboarding-picker" ref={root}>
      <span className="onboarding-picker-label">{label}</span>
      <PickerTrigger
        disabled={disabled}
        listId={listId}
        onToggle={toggle}
        open={open}
        placeholder={placeholder}
        selected={selected}
      />
      {open ? <PickerMenu
        emptyText={emptyText}
        filtered={filtered}
        layout={menuLayout}
        listId={listId}
        onChoose={choose}
        onQuery={setQuery}
        query={query}
        searchLabel={searchLabel}
        searchRef={search}
        selectedValue={value}
      /> : null}
    </div>
  );
}

function PickerTrigger({
  disabled, listId, onToggle, open, placeholder, selected,
}: {
  disabled: boolean;
  listId: string;
  onToggle: () => void;
  open: boolean;
  placeholder: string;
  selected?: SearchableOption;
}) {
  return (
    <button
      aria-controls={listId}
      aria-expanded={open}
      aria-haspopup="listbox"
      className="onboarding-picker-trigger"
      disabled={disabled}
      onClick={onToggle}
      type="button"
    >
      <span className="onboarding-picker-trigger-value">
        <span>{selected?.label ?? placeholder}</span>
        {selected?.info ? <InfoIcon text={selected.info} /> : null}
      </span>
      <i aria-hidden="true">⌄</i>
    </button>
  );
}

interface PickerMenuLayout {
  placement: "up" | "down";
  optionsHeight: number;
}

interface PickerMenuProps {
  emptyText: string;
  filtered: SearchableOption[];
  layout: PickerMenuLayout;
  listId: string;
  onChoose: (value: string) => void;
  onQuery: (value: string) => void;
  query: string;
  searchLabel: string;
  searchRef: React.RefObject<HTMLInputElement>;
  selectedValue: string;
}

function PickerMenu({
  emptyText, filtered, layout, listId, onChoose, onQuery, query, searchLabel,
  searchRef, selectedValue,
}: PickerMenuProps) {
  return (
    <div
      className={`onboarding-picker-menu ${layout.placement}`}
      style={{ "--onboarding-picker-options-max": `${layout.optionsHeight}px` } as React.CSSProperties}
    >
      <input
        aria-label={searchLabel}
        onChange={(event) => onQuery(event.target.value)}
        placeholder={searchLabel}
        ref={searchRef}
        type="search"
        value={query}
      />
      <div className="onboarding-picker-options" id={listId} role="listbox">
        {filtered.length ? filtered.map((option, index) => (
          <button
            aria-describedby={option.info ? `${listId}-info-${index}` : undefined}
            aria-selected={option.value === selectedValue}
            key={option.value}
            onClick={() => onChoose(option.value)}
            role="option"
            type="button"
          >
            <span className="onboarding-picker-option-label">
              <span>{option.label}</span>
              {option.info ? <InfoIcon text={option.info} /> : null}
            </span>
            {option.detail ? <small>{option.detail}</small> : null}
            {option.info ? (
              <span className="onboarding-visually-hidden" id={`${listId}-info-${index}`}>
                {option.info}
              </span>
            ) : null}
            {option.value === selectedValue ? <b aria-hidden="true">✓</b> : null}
          </button>
        )) : <p>{emptyText}</p>}
      </div>
    </div>
  );
}

function measurePickerMenu(root: HTMLDivElement | null): PickerMenuLayout {
  if (!root) return { placement: "down", optionsHeight: 250 };
  const anchor = root.getBoundingClientRect();
  const slide = root.closest(".onboarding-slide")?.getBoundingClientRect();
  const panel = root.closest(".onboarding-panel")?.getBoundingClientRect();
  const boundaryTop = Math.max(slide?.top ?? panel?.top ?? 0, 0);
  const boundaryBottom = Math.min(
    slide?.bottom ?? panel?.bottom ?? window.innerHeight,
    window.innerHeight,
  );
  const above = Math.max(0, anchor.top - boundaryTop - 14);
  const below = Math.max(0, boundaryBottom - anchor.bottom - 14);
  const placement = below < 322 && above > below ? "up" : "down";
  const available = placement === "up" ? above : below;
  return {
    placement,
    optionsHeight: Math.max(110, Math.min(250, Math.floor(available - 72))),
  };
}

function filterOptions(options: SearchableOption[], query: string) {
  const needle = query.trim().toLocaleLowerCase();
  if (!needle) return options;
  return options.filter((option) => `${option.label} ${option.value} ${option.detail ?? ""} ${option.info ?? ""}`
    .toLocaleLowerCase().includes(needle));
}

function InfoIcon({ text }: { text: string }) {
  return (
    <span
      aria-hidden="true"
      className="onboarding-picker-info"
      data-tooltip={text}
      title={text}
    >
      i
    </span>
  );
}

function pickerDismissal(
  open: boolean,
  root: React.RefObject<HTMLDivElement>,
  dismiss: () => void,
) {
  if (!open) return;
  function onPointer(event: PointerEvent) {
    if (!root.current?.contains(event.target as Node)) dismiss();
  }
  function onKey(event: KeyboardEvent) {
    if (event.key === "Escape") dismiss();
  }
  document.addEventListener("pointerdown", onPointer);
  document.addEventListener("keydown", onKey);
  return () => {
    document.removeEventListener("pointerdown", onPointer);
    document.removeEventListener("keydown", onKey);
  };
}
