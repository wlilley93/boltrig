import {
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";
import type { IntegrationCatalogueEntry } from "@wlilley93/boltrig-web-sdk";

import { IntegrationsTabs } from "./IntegrationsTabs";

/**
 * The page title, and the tab strip beneath it.
 *
 * The tabs render HERE, inside the pane, rather than around the whole route:
 * the visual contract pins the pane's column, and a strip above `.plugins-page`
 * lands at x=266 against a pane at x=435, which is not a styling detail but a
 * different page. Every tab shows the same heading and the same strip, so this
 * is also the only place they have to be written.
 *
 * `onAdd` is optional. Adding a plugin is a Connections action, and a page-level
 * button that does nothing on three of four tabs is worse than its absence.
 */
export function PluginPageHeading({ onAdd }: { onAdd?: () => void }) {
  return (
    <>
      <header className="plugins-heading">
        <div className="plugins-heading-copy">
          <h1>Plugins</h1>
          <p>Connect the apps and services you want Boltrig to use.</p>
        </div>
        {onAdd && (
          <button className="plugins-add-button" onClick={onAdd} type="button">
            <PlusIcon />
            <span>Add plugin</span>
          </button>
        )}
      </header>
      <IntegrationsTabs />
    </>
  );
}

export function PluginInventoryStatus({
  connectionState,
  mcpState,
  mcpTruncated,
}: {
  connectionState: "loading" | "available" | "unavailable";
  mcpState: "loading" | "available" | "denied" | "unavailable";
  mcpTruncated: boolean;
}) {
  return (
    <>
      {connectionState === "unavailable" && (
        <p className="plugins-api-state" role="status">Plugin setup is unavailable right now.</p>
      )}
      {connectionState === "loading" && (
        <p className="plugins-api-state" role="status">Checking plugin connections…</p>
      )}
      {mcpState === "loading" && (
        <p className="plugins-api-state" role="status">Checking your connected servers…</p>
      )}
      {mcpState === "denied" && (
        <p className="plugins-api-state" role="status">You cannot view connected servers with this account.</p>
      )}
      {mcpState === "unavailable" && (
        <p className="plugins-api-state" role="status">Connected servers are unavailable right now.</p>
      )}
      {mcpState === "available" && mcpTruncated && (
        <p className="plugins-api-state" role="status">Only the first page of connected servers is shown.</p>
      )}
    </>
  );
}

export function AddPluginModal({
  connectedIds,
  entries,
  onClose,
  onSelect,
}: {
  connectedIds: ReadonlySet<string>;
  entries: IntegrationCatalogueEntry[];
  onClose(): void;
  onSelect(entry: IntegrationCatalogueEntry): void;
}) {
  const [query, setQuery] = useState("");
  const titleId = useId();
  const { cardRef, handleKeyDown, searchRef } = usePluginDialogFocus(onClose);
  const choices = useMemo(() => {
    const term = query.trim().toLowerCase();
    return entries
      .filter((entry) => !connectedIds.has(entry.id))
      .filter((entry) => entry.available && entry.setup_supported)
      .filter((entry) => !term || `${entry.label} ${entry.description}`.toLowerCase().includes(term))
      .sort((left, right) => left.label.localeCompare(right.label));
  }, [connectedIds, entries, query]);

  return (
    <div className="add-plugin-scrim" onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose();
    }} role="presentation">
      <section
        aria-labelledby={titleId}
        aria-modal="true"
        className="add-plugin-modal"
        onKeyDown={handleKeyDown}
        ref={cardRef}
        role="dialog"
      >
        <header>
          <div><h2 id={titleId}>Add a plugin</h2><p>Choose an app or service.</p></div>
          <button aria-label="Close add plugin" onClick={onClose} type="button">×</button>
        </header>
        <label className="add-plugin-search">
          <SearchIcon />
          <span className="sr-only">Search plugins</span>
          <input
            aria-label="Search plugins"
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search plugins…"
            ref={searchRef}
            value={query}
          />
        </label>
        <PluginChoiceList choices={choices} onSelect={onSelect} />
      </section>
    </div>
  );
}

function usePluginDialogFocus(onClose: () => void) {
  const cardRef = useRef<HTMLElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  useEffect(() => {
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    searchRef.current?.focus();
    return () => {
      document.body.style.overflow = previousOverflow;
      previous?.focus();
    };
  }, []);
  function handleKeyDown(event: KeyboardEvent<HTMLElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      closeRef.current();
      return;
    }
    if (event.key !== "Tab") return;
    const controls = Array.from(cardRef.current?.querySelectorAll<HTMLElement>(
      'button:not(:disabled), input:not(:disabled), [tabindex]:not([tabindex="-1"])',
    ) ?? []);
    if (controls.length === 0) return;
    const current = controls.indexOf(document.activeElement as HTMLElement);
    if (event.shiftKey && current <= 0) {
      event.preventDefault();
      controls.at(-1)?.focus();
    } else if (!event.shiftKey && current === controls.length - 1) {
      event.preventDefault();
      controls[0]?.focus();
    }
  }
  return { cardRef, handleKeyDown, searchRef };
}

function PluginChoiceList({ choices, onSelect }: {
  choices: IntegrationCatalogueEntry[];
  onSelect(entry: IntegrationCatalogueEntry): void;
}) {
  return (
    <div className="add-plugin-list">
      {choices.map((entry) => {
        return (
          <button aria-label={`Add ${entry.label}`} key={entry.id} onClick={() => onSelect(entry)} type="button">
            <span className="add-plugin-mark" aria-hidden>{entry.label.slice(0, 1)}</span>
            <span><strong>{entry.label}</strong><small>{entry.description}</small></span>
            <em>Add</em>
          </button>
        );
      })}
      {choices.length === 0 && <p>No plugins match that search.</p>}
    </div>
  );
}

function PlusIcon() {
  return <svg aria-hidden fill="none" height="14" stroke="currentColor" strokeLinecap="round" strokeWidth="2" viewBox="0 0 24 24" width="14"><path d="M12 5v14M5 12h14" /></svg>;
}

function SearchIcon() {
  return <svg aria-hidden fill="none" height="15" stroke="currentColor" strokeLinecap="round" strokeWidth="1.8" viewBox="0 0 24 24" width="15"><circle cx="11" cy="11" r="6.5" /><path d="m16 16 4 4" /></svg>;
}
