import { useEffect, useMemo, useRef, useState } from "react";

import { navigate, type WorkerRoute } from "../../routes";
import "./ComposerAddMenu.css";

interface AddAction {
  id: string;
  label: string;
  description: string;
  icon: AddIcon;
  disabled?: boolean;
  run(): void;
}

interface AddSection {
  label: string;
  actions: AddAction[];
}

type AddIcon = "file" | "search" | "work" | "routine" | "skill" | "plugin" | "knowledge";

export function ComposerAddMenu({
  attachmentsDisabled,
  disabled,
  onAttach,
  onOpenCommands,
}: {
  attachmentsDisabled?: boolean;
  disabled: boolean;
  onAttach(): void;
  onOpenCommands?(): void;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const rootRef = useRef<HTMLSpanElement>(null);
  const openerRef = useRef<HTMLButtonElement>(null);
  const sections = useMemo(
    () => buildSections({ attachmentsDisabled, onAttach, onOpenCommands }),
    [attachmentsDisabled, onAttach, onOpenCommands],
  );
  const filtered = filterSections(sections, query);

  useEffect(() => {
    if (!open) return;
    const closeOutside = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", closeOutside);
    return () => document.removeEventListener("pointerdown", closeOutside);
  }, [open]);

  useEffect(() => {
    if (disabled) setOpen(false);
  }, [disabled]);

  function close({ restore = false } = {}) {
    setOpen(false);
    if (restore) window.setTimeout(() => openerRef.current?.focus(), 0);
  }

  function choose(action: AddAction) {
    if (action.disabled) return;
    close();
    action.run();
  }

  return (
    <span className="composer-add" ref={rootRef}>
      <button
        aria-controls="composer-add-popover"
        aria-expanded={open}
        aria-haspopup="dialog"
        aria-label="Add"
        className="icon-button composer-add-trigger"
        disabled={disabled}
        onClick={() => {
          setOpen((current) => !current);
          setQuery("");
        }}
        ref={openerRef}
        type="button"
      >
        <svg aria-hidden fill="none" height="17" stroke="currentColor" strokeLinecap="round" strokeWidth="1.9" viewBox="0 0 24 24" width="17">
          <line x1="12" x2="12" y1="5" y2="19" />
          <line x1="5" x2="19" y1="12" y2="12" />
        </svg>
      </button>
      {open && <AddPopover close={close} onChoose={choose} onQuery={setQuery}
        query={query} sections={filtered} />}
    </span>
  );
}

function AddPopover({
  close,
  onChoose,
  onQuery,
  query,
  sections,
}: {
  close(options?: { restore?: boolean }): void;
  onChoose(action: AddAction): void;
  onQuery(value: string): void;
  query: string;
  sections: AddSection[];
}) {
  const searchRef = useRef<HTMLInputElement>(null);
  useEffect(() => searchRef.current?.focus({ preventScroll: true }), []);
  return (
    <section aria-label="Add to task" className="composer-add-popover"
      id="composer-add-popover" onKeyDown={(event) => handleMenuKey(event, close)}
      role="dialog">
      <label className="composer-add-search">
        <svg aria-hidden fill="none" height="14" stroke="currentColor" strokeWidth="1.8"
          viewBox="0 0 24 24" width="14">
          <circle cx="11" cy="11" r="6" /><path d="m16 16 4 4" />
        </svg>
        <input aria-label="Search actions" onChange={(event) => onQuery(event.target.value)}
          placeholder="Search actions" ref={searchRef} value={query} />
      </label>
      <div className="composer-add-scroll">
        {sections.map((section) => (
          <div className="composer-add-section" key={section.label}>
            <p>{section.label}</p>
            {section.actions.map((action) => (
              <button className="composer-add-row" disabled={action.disabled} key={action.id}
                onClick={() => onChoose(action)} type="button">
                <AddMenuIcon kind={action.icon} />
                <span><strong>{action.label}</strong><small>{action.description}</small></span>
              </button>
            ))}
          </div>
        ))}
        {sections.length === 0 && <p className="composer-add-empty">No matching action</p>}
      </div>
    </section>
  );
}

function buildSections({
  attachmentsDisabled,
  onAttach,
  onOpenCommands,
}: {
  attachmentsDisabled?: boolean;
  onAttach(): void;
  onOpenCommands?(): void;
}): AddSection[] {
  const route = (destination: WorkerRoute, id?: string) => () => navigate(destination, id);
  return [
    {
      label: "Add",
      actions: [
        { id: "files", label: "Files", description: attachmentsDisabled ? "Unavailable for local tasks" : "Attach from this device", icon: "file", disabled: attachmentsDisabled, run: onAttach },
        ...(onOpenCommands ? [{ id: "search", label: "Search Boltrig", description: "Chats, runs, knowledge and memory", icon: "search" as const, run: onOpenCommands }] : []),
      ],
    },
    {
      label: "Agent tools",
      actions: [
        { id: "work", label: "Work and goals", description: "Review governed work", icon: "work", run: route("work") },
        { id: "routines", label: "Routines", description: "Build scheduled or triggered work", icon: "routine", run: route("automations") },
        { id: "skills", label: "Record a skill", description: "Teach an approved repeatable method", icon: "skill", run: route("build", "skills") },
      ],
    },
    {
      label: "Workspace",
      actions: [
        { id: "plugins", label: "Plugins", description: "Connect external context", icon: "plugin", run: route("integrations") },
        { id: "knowledge", label: "Knowledge", description: "Browse governed sources", icon: "knowledge", run: route("knowledge") },
      ],
    },
  ];
}

function filterSections(sections: AddSection[], query: string): AddSection[] {
  const term = query.trim().toLowerCase();
  if (!term) return sections;
  return sections
    .map((section) => ({
      ...section,
      actions: section.actions.filter((action) => (
        `${action.label} ${action.description}`.toLowerCase().includes(term)
      )),
    }))
    .filter((section) => section.actions.length > 0);
}

function handleMenuKey(
  event: React.KeyboardEvent<HTMLElement>,
  close: (options?: { restore?: boolean }) => void,
) {
  if (event.key === "Escape") {
    event.preventDefault();
    close({ restore: true });
    return;
  }
  if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
  event.preventDefault();
  const rows = Array.from(
    event.currentTarget.querySelectorAll<HTMLButtonElement>(".composer-add-row:not(:disabled)"),
  );
  if (rows.length === 0) return;
  const current = rows.indexOf(document.activeElement as HTMLButtonElement);
  const delta = event.key === "ArrowDown" ? 1 : -1;
  rows[(current + delta + rows.length) % rows.length]?.focus();
}

function AddMenuIcon({ kind }: { kind: AddIcon }) {
  const paths: Record<AddIcon, React.ReactNode> = {
    file: <><path d="M8 12.5 14.5 6a3 3 0 0 1 4.2 4.2l-8.1 8.1a5 5 0 0 1-7.1-7.1l8-8" /></>,
    search: <><circle cx="10.5" cy="10.5" r="6" /><path d="m15 15 5 5" /></>,
    work: <><path d="M5 6h14v13H5z" /><path d="M9 6V4h6v2M8 11h8" /></>,
    routine: <><path d="M6 7h10l-2.5-2.5M18 17H8l2.5 2.5" /><path d="M18 7a7 7 0 0 1 0 10M6 17a7 7 0 0 1 0-10" /></>,
    skill: <><path d="m12 3 2.3 4.7 5.2.8-3.8 3.7.9 5.3-4.6-2.5-4.6 2.5.9-5.3-3.8-3.7 5.2-.8z" /></>,
    plugin: <><path d="M8 4v4H4v5h4v4h5v-4h4V8h-4V4z" /><path d="M17 10h3v8h-8v-1" /></>,
    knowledge: <><path d="M4 5.5A3.5 3.5 0 0 1 7.5 2H12v17H7.5A3.5 3.5 0 0 0 4 22z" /><path d="M20 5.5A3.5 3.5 0 0 0 16.5 2H12v17h4.5A3.5 3.5 0 0 1 20 22z" /></>,
  };
  return <svg aria-hidden className="composer-add-icon" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.55" viewBox="0 0 24 24">{paths[kind]}</svg>;
}
