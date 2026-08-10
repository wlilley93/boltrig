import { useEffect, useMemo, useRef, useState } from "react";
import type {
  FederatedSearchHit,
  FederatedSearchResponse,
  FederatedSearchSource,
  FederatedSearchSourceResult,
} from "@wlilley93/boltrig-web-sdk";

import { client } from "../client";
import type { WorkerRoute } from "../routes";

interface Command {
  route: WorkerRoute;
  /** Sub-surface within the route (e.g. a Build tab), passed as the route id. */
  routeId?: string;
  label: string;
  description: string;
  keywords: string;
}

type SearchState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "ready"; response: FederatedSearchResponse }
  | { kind: "unavailable" };

type PaletteOption =
  | { key: string; kind: "command"; command: Command }
  | { key: string; kind: "content"; hit: FederatedSearchHit };

interface ContentGroup {
  source: FederatedSearchSourceResult;
  hits: Array<{ key: string; hit: FederatedSearchHit }>;
}

const optionId = (index: number) => `worker-command-option-${index}`;
const SOURCE_LABELS: Record<FederatedSearchSource, string> = {
  conversations: "Conversations",
  executions: "Runs and work",
  knowledge: "Knowledge",
  memory: "Memory",
  audit: "Audit",
};

export const workerCommands: Command[] = [
  { route: "chat", label: "New task", description: "Start an agent task or voice call", keywords: "chat codex voice call" },
  { route: "home", label: "Home", description: "See workspace activity and operational status", keywords: "overview dashboard" },
  { route: "inbox", label: "Inbox", description: "Review questions and human approvals", keywords: "hitl approval questions" },
  { route: "work", label: "Work", description: "Browse canonical work and project dependencies", keywords: "tasks projects queue dag" },
  { route: "runs", label: "Runs", description: "Inspect execution, cost, and subagent topology", keywords: "history audit subagents codex" },
  { route: "agents", label: "Agents", description: "Configure governed Codex worker profiles", keywords: "subagents profiles familiar runtime" },
  // Labels follow the sidebar's decided-target vocabulary; the words they
  // replaced stay searchable as keywords.
  { route: "automations", label: "Routines", description: "Author workflows, DAGs, triggers, and schedules", keywords: "automations hatchet workflow cron webhook routine" },
  { route: "evaluations", label: "Evaluations", description: "Test governed agent behavior", keywords: "eval fixtures regression" },
  { route: "knowledge", label: "Knowledge", description: "Search and manage governed sources", keywords: "documents rag files citations" },
  { route: "memory", label: "Memory", description: "Browse, recall, and improve durable memory", keywords: "facts remember ingest kernel" },
  { route: "channels", label: "Channels", description: "Connect external message and event channels", keywords: "webhook messaging pairing" },
  { route: "integrations", label: "Plugins", description: "Manage provider connections", keywords: "integrations connectors oauth external plugin" },
  { route: "build", label: "Build", description: "Author capabilities and model endpoints", keywords: "skills mcp models tools" },
  { route: "build", routeId: "skills", label: "Skills", description: "What the agents know how to do, and where it came from", keywords: "build capabilities know-how provenance" },
  { route: "build", routeId: "actions", label: "Actions", description: "Every governed verb an agent can reach", keywords: "build verbs registry approval" },
  { route: "operate", label: "Operate", description: "Monitor operational health", keywords: "operations health status" },
  { route: "account", label: "Account", description: "Manage your profile, security, and automation", keywords: "identity auth devices keys" },
  { route: "organisation", label: "Organisation", description: "Manage workspace members and policy", keywords: "team roles directory workspace" },
  { route: "settings", label: "Settings", description: "Configure Worker preferences", keywords: "theme device preferences" },
];

export function CommandPalette({
  open,
  onClose,
  onNavigate,
}: {
  open: boolean;
  onClose(): void;
  onNavigate(route: WorkerRoute, routeId: string | null): void;
}) {
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const [searchState, setSearchState] = useState<SearchState>({ kind: "idle" });
  const dialogRef = useRef<HTMLElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const requestSequence = useRef(0);
  const visibleCommands = useMemo(() => {
    const term = query.trim().toLowerCase();
    if (!term) return workerCommands;
    return workerCommands.filter((command) => (
      `${command.label} ${command.description} ${command.keywords}`
        .toLowerCase()
        .includes(term)
    ));
  }, [query]);

  useEffect(() => {
    if (!open) return;
    requestSequence.current += 1;
    setQuery("");
    setActiveIndex(0);
    setSearchState({ kind: "idle" });
  }, [open]);

  useEffect(() => {
    const term = query.trim();
    const sequence = ++requestSequence.current;
    if (!open || term.length < 2) {
      setSearchState({ kind: "idle" });
      return;
    }
    setSearchState({ kind: "loading" });
    const timer = window.setTimeout(() => {
      void client.federatedSearch({ query: term, limit: 5 })
        .then((response) => {
          if (requestSequence.current === sequence) {
            setSearchState({ kind: "ready", response });
          }
        })
        .catch(() => {
          if (requestSequence.current === sequence) {
            setSearchState({ kind: "unavailable" });
          }
        });
    }, 250);
    return () => {
      window.clearTimeout(timer);
      if (requestSequence.current === sequence) requestSequence.current += 1;
    };
  }, [open, query]);

  const contentGroups = useMemo(
    () => searchState.kind === "ready"
      ? groupContentResults(searchState.response)
      : [],
    [searchState],
  );
  const options = useMemo<PaletteOption[]>(() => [
    ...visibleCommands.map((command) => ({
      key: `command:${command.route}${command.routeId ? `:${command.routeId}` : ""}`,
      kind: "command" as const,
      command,
    })),
    ...contentGroups.flatMap((group) => group.hits.map(({ key, hit }) => ({
      key,
      kind: "content" as const,
      hit,
    }))),
  ], [contentGroups, visibleCommands]);
  const optionIndexes = useMemo(
    () => new Map(options.map((option, index) => [option.key, index])),
    [options],
  );

  useEffect(() => {
    setActiveIndex((current) => (
      options.length === 0 ? 0 : Math.min(current, options.length - 1)
    ));
  }, [options.length]);

  useEffect(() => {
    if (!open) return;
    const opener = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null;
    inputRef.current?.focus();
    return () => {
      if (opener?.isConnected) opener.focus();
    };
  }, [open]);

  if (!open) return null;

  function choose(option: PaletteOption) {
    if (option.kind === "command") {
      onNavigate(option.command.route, option.command.routeId ?? null);
    } else {
      onNavigate(option.hit.route, boundedRouteId(option.hit.route_id));
    }
    onClose();
  }

  return (
    <div className="command-backdrop" onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose();
    }}>
      <section
        aria-label="Worker commands"
        aria-modal="true"
        className="command-palette"
        onKeyDown={(event) => {
          // Escape is owned here rather than on the input: Tab moves focus onto
          // the option rows, and from there a keydown on the input never fires.
          if (event.key === "Escape") {
            event.preventDefault();
            onClose();
            return;
          }
          if (event.key !== "Tab") return;
          const focusable = dialogRef.current
            ? focusableElements(dialogRef.current)
            : [];
          if (focusable.length === 0) {
            event.preventDefault();
            return;
          }
          const first = focusable[0];
          const last = focusable[focusable.length - 1];
          if (event.shiftKey && (
            document.activeElement === first
            || !dialogRef.current?.contains(document.activeElement)
          )) {
            event.preventDefault();
            last.focus();
          } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault();
            first.focus();
          }
        }}
        ref={dialogRef}
        role="dialog"
      >
        <div className="command-search">
          <span aria-hidden>⌕</span>
          <input
            aria-activedescendant={
              options[activeIndex] ? optionId(activeIndex) : undefined
            }
            aria-autocomplete="list"
            aria-controls="worker-command-results"
            aria-expanded="true"
            aria-label="Search Worker"
            onChange={(event) => {
              setQuery(event.target.value);
              setActiveIndex(0);
            }}
            onKeyDown={(event) => {
              if (event.nativeEvent.isComposing || event.keyCode === 229) return;
              // Escape is handled by the dialog this bubbles to, so it closes
              // from the input and from a focused option alike.
              if (event.key === "ArrowDown") {
                event.preventDefault();
                if (options.length > 0) {
                  setActiveIndex((current) => Math.min(options.length - 1, current + 1));
                }
              } else if (event.key === "ArrowUp") {
                event.preventDefault();
                if (options.length > 0) {
                  setActiveIndex((current) => Math.max(0, current - 1));
                }
              } else if (event.key === "Home") {
                event.preventDefault();
                if (options.length > 0) setActiveIndex(0);
              } else if (event.key === "End") {
                event.preventDefault();
                if (options.length > 0) setActiveIndex(options.length - 1);
              } else if (event.key === "Enter" && options[activeIndex]) {
                event.preventDefault();
                choose(options[activeIndex]);
              }
            }}
            placeholder="Search commands and scoped content…"
            ref={inputRef}
            role="combobox"
            value={query}
          />
          <kbd>Esc</kbd>
        </div>
        {searchState.kind === "loading" && (
          <p className="command-api-state">Searching governed content…</p>
        )}
        {searchState.kind === "unavailable" && (
          <p className="command-api-state error" role="alert">
            Content search is unavailable. Navigation commands still work.
          </p>
        )}
        <div
          aria-label="Worker command results"
          className="command-results"
          id="worker-command-results"
          role="listbox"
        >
          {visibleCommands.length > 0 && (
            <section
              aria-label="Navigation commands"
              className="command-group"
              role="group"
            >
              <p className="command-group-heading">Commands</p>
              {visibleCommands.map((command) => {
                const key = `command:${command.route}${command.routeId ? `:${command.routeId}` : ""}`;
                const index = optionIndexes.get(key) ?? 0;
                const option = options[index];
                return (
                  <button
                    aria-selected={index === activeIndex}
                    className={index === activeIndex ? "command-row active" : "command-row"}
                    id={optionId(index)}
                    key={key}
                    onClick={() => choose(option)}
                    onMouseEnter={() => setActiveIndex(index)}
                    role="option"
                    type="button"
                  >
                    <span><strong>{command.label}</strong><small>{command.description}</small></span>
                    <span aria-hidden>↵</span>
                  </button>
                );
              })}
            </section>
          )}
          {contentGroups.map((group) => (
            <section
              aria-label={`${SOURCE_LABELS[group.source.source]} search results`}
              className="command-group command-source-group"
              key={group.source.source}
              role="group"
            >
              <div className="command-group-heading">
                <span>{SOURCE_LABELS[group.source.source]}</span>
                <small className={`command-source-state ${group.source.status}`}>
                  {sourceStatusCopy(group.source)}
                </small>
              </div>
              {group.hits.map(({ key, hit }) => {
                const index = optionIndexes.get(key) ?? 0;
                const option = options[index];
                return (
                  <button
                    aria-selected={index === activeIndex}
                    className={index === activeIndex
                      ? "command-row command-content-row active"
                      : "command-row command-content-row"}
                    id={optionId(index)}
                    key={key}
                    onClick={() => choose(option)}
                    onMouseEnter={() => setActiveIndex(index)}
                    role="option"
                    type="button"
                  >
                    <span>
                      <strong>{hit.title}</strong>
                      <small>{hit.preview || contentDestinationCopy(hit)}</small>
                    </span>
                    <span className="command-result-source">
                      {SOURCE_LABELS[hit.source]} <span aria-hidden>↵</span>
                    </span>
                  </button>
                );
              })}
            </section>
          ))}
          {options.length === 0 && searchState.kind !== "loading" && (
            <p className="command-empty" role="presentation">
              No matching commands or scoped content.
            </p>
          )}
        </div>
        <p
          aria-atomic="true"
          aria-live="polite"
          className="command-status"
          role="status"
        >
          {announcement(options.length, searchState)}
        </p>
        <p className="command-hint">
          Commands stay local. Content results are scope-filtered by Boltrig and may be partial by source.
        </p>
      </section>
    </div>
  );
}

function groupContentResults(response: FederatedSearchResponse): ContentGroup[] {
  const indexed = response.results.map((hit, index) => ({
    key: `content:${hit.source}:${hit.id}:${index}`,
    hit,
  }));
  return response.sources.map((source) => ({
    source,
    hits: indexed.filter(({ hit }) => hit.source === source.source),
  }));
}

function boundedRouteId(value: string | null): string | null {
  return value && value.length <= 256 ? value : null;
}

function sourceStatusCopy(source: FederatedSearchSourceResult): string {
  if (source.status === "denied") return "Restricted";
  if (source.status === "unavailable") return "Unavailable";
  const count = `${source.count} ${source.count === 1 ? "result" : "results"}`;
  return source.truncated ? `${count} · more available` : count;
}

function contentDestinationCopy(hit: FederatedSearchHit): string {
  return hit.route_id ? `Open in ${SOURCE_LABELS[hit.source]}` : `Open ${hit.route}`;
}

function announcement(optionCount: number, searchState: SearchState): string {
  const resultCopy = `${optionCount} ${optionCount === 1 ? "result" : "results"} available.`;
  if (searchState.kind === "loading") return `${resultCopy} Searching governed content.`;
  if (searchState.kind === "unavailable") {
    return `${resultCopy} Content search is unavailable; navigation commands still work.`;
  }
  if (searchState.kind !== "ready") return resultCopy;
  const degraded = searchState.response.sources.filter(
    (source) => source.status !== "ok",
  );
  if (degraded.length === 0) return resultCopy;
  return `${resultCopy} ${degraded.map((source) => (
    `${SOURCE_LABELS[source.source]} ${source.status === "denied" ? "restricted" : "unavailable"}`
  )).join(", ")}.`;
}

function focusableElements(container: HTMLElement): HTMLElement[] {
  return Array.from(container.querySelectorAll<HTMLElement>(
    'input, button:not([disabled]), a[href], select, textarea, [tabindex]:not([tabindex="-1"])',
  )).filter((element) => !element.hasAttribute("hidden"));
}
