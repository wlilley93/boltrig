import { useEffect, useMemo, useRef, useState } from "react";
import type {
  FederatedSearchHit,
  FederatedSearchResponse,
  FederatedSearchSource,
  FederatedSearchSourceResult,
} from "@wlilley93/boltrig-web-sdk";

import { client } from "../client";
import type { WorkerRoute } from "../routes";
import "./CommandPalette.css";

interface Command {
  route: WorkerRoute;
  /** Sub-surface within the route (e.g. a Build tab), passed as the route id. */
  routeId?: string;
  label: string;
  description: string;
  keywords: string;
  /** Quiet destination word at the far edge of the decided palette row. */
  hint?: string;
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
  // The first four entries mirror the console rail. Deeper operational
  // destinations remain searchable below them rather than displacing the
  // task-first vocabulary at the top of an empty palette.
  { route: "chat", label: "New chat", description: "Start something new", keywords: "new task chat codex voice call", hint: "Go" },
  { route: "agents", label: "Agents", description: "Configure governed Codex worker profiles", keywords: "subagents profiles familiar runtime" },
  { route: "integrations", label: "Plugins", description: "Manage provider connections", keywords: "integrations connectors oauth external plugin" },
  { route: "automations", label: "Routines", description: "Author workflows, DAGs, triggers, and schedules", keywords: "automations hatchet workflow cron webhook routine" },

  // Every settings destination in the downloaded target is directly
  // addressable by the current hash router, so the palette exposes the same
  // one-search-away catalogue without inventing controls or state.
  { route: "settings", routeId: "you", label: "You settings", description: "Appearance, voice and personal preferences", keywords: "theme identity profile", hint: "Settings" },
  { route: "settings", routeId: "autonomy", label: "Autonomy settings", description: "Review what stops and governs work", keywords: "approval permissions posture", hint: "Settings" },
  { route: "settings", routeId: "spend", label: "Spending settings", description: "Review cost and budget ceilings", keywords: "budget cost money", hint: "Settings" },
  { route: "settings", routeId: "shortcuts", label: "Keyboard shortcuts settings", description: "See the shortcuts this build actually binds", keywords: "keys commands keyboard", hint: "Settings" },
  { route: "settings", routeId: "knowledge", label: "Knowledge settings", description: "Review governed sources and storage", keywords: "files citations storage", hint: "Settings" },
  { route: "settings", routeId: "overnight", label: "Overnight settings", description: "Inspect overnight practice and gates", keywords: "practice improve nightly", hint: "Settings" },
  { route: "settings", routeId: "health", label: "Health settings", description: "See what is working and what is bounded", keywords: "status checks readiness", hint: "Settings" },
  { route: "settings", routeId: "organisation", label: "Organisation settings", description: "Review workspace people and policy", keywords: "members roles audit", hint: "Settings" },
  { route: "settings", routeId: "advanced", label: "Advanced settings", description: "Device and developer controls", keywords: "technical desktop device", hint: "Settings" },
  { route: "settings", routeId: "archived", label: "Archived chats settings", description: "Bring a closed conversation back", keywords: "archive restore conversations", hint: "Settings" },

  { route: "chat", label: "Approve what is waiting", description: "Return to the originating conversation", keywords: "approval decide pending hitl", hint: "Chat" },
  { route: "settings", routeId: "autonomy", label: "Change what needs approving", description: "Open autonomy settings", keywords: "approval policy posture", hint: "Autonomy" },
  { route: "integrations", label: "Add a plugin", description: "Browse provider connections", keywords: "connect integration oauth", hint: "Plugins" },
  { route: "settings", routeId: "organisation", label: "Verify the record", description: "Open organisation and audit settings", keywords: "audit verify receipts", hint: "Organisation" },
  { route: "settings", routeId: "you", label: "Switch theme", description: "Open appearance settings", keywords: "light dark system appearance", hint: "You" },

  { route: "home", label: "Home", description: "See workspace activity and operational status", keywords: "overview dashboard" },
  { route: "work", label: "Work", description: "Browse canonical work and project dependencies", keywords: "tasks projects queue dag" },
  { route: "runs", label: "Runs", description: "Inspect execution, cost, and subagent topology", keywords: "history audit subagents codex" },
  { route: "evaluations", label: "Evaluations", description: "Test governed agent behavior", keywords: "eval fixtures regression" },
  { route: "knowledge", label: "Knowledge", description: "Search and manage governed sources", keywords: "documents rag files citations" },
  { route: "memory", label: "Memory", description: "Browse, recall, and improve durable memory", keywords: "facts remember ingest kernel" },
  { route: "channels", label: "Channels", description: "Connect external message and event channels", keywords: "webhook messaging pairing" },
  { route: "build", label: "Build", description: "Author capabilities and model endpoints", keywords: "skills mcp models tools" },
  { route: "build", routeId: "skills", label: "Skills", description: "What the agents know how to do, and where it came from", keywords: "build capabilities know-how provenance" },
  { route: "integrations", label: "Plugins and sources", description: "Choose connected context for a task", keywords: "slash context sources plugins integrations", hint: "Plugins" },
  { route: "build", routeId: "actions", label: "Actions", description: "Every governed verb an agent can reach", keywords: "build verbs registry approval" },
  { route: "account", label: "Account", description: "Manage your profile, security, and automation", keywords: "identity auth devices keys" },
  { route: "organisation", label: "Organisation", description: "Manage workspace members and policy", keywords: "team roles directory workspace" },
  { route: "settings", label: "Operations", routeId: "operations", description: "Review runtime posture, audit and budget evidence", keywords: "operate operations health audit budgets status" },
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
  const backdropRef = useRef<HTMLDivElement>(null);
  const dialogRef = useRef<HTMLElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const resultsRef = useRef<HTMLDivElement>(null);
  const requestSequence = useRef(0);
  const visibleCommands = useMemo(() => {
    const term = query.trim().toLowerCase();
    const matches = !term ? workerCommands : workerCommands.filter((command) => (
      `${command.label} ${command.description} ${command.keywords}`
        .toLowerCase()
        .includes(term)
    ));
    return matches.slice(0, 8);
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
      key: commandKey(command),
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
    if (!open || options.length === 0) return;
    const active = resultsRef.current?.querySelector<HTMLElement>(
      `[id="${optionId(activeIndex)}"]`,
    );
    active?.scrollIntoView?.({ block: "nearest" });
  }, [activeIndex, open, options.length]);

  useEffect(() => {
    if (!open) return;
    const opener = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null;
    const restoreBackground = isolateBackgroundSiblings(backdropRef.current);
    inputRef.current?.focus();
    return () => {
      restoreBackground();
      if (opener?.isConnected) opener.focus();
    };
  }, [open]);

  if (!open) return null;

  function choose(option: PaletteOption) {
    if (option.kind === "command") {
      onNavigate(option.command.route, option.command.routeId ?? null);
    } else {
      const destination = contentDestination(option.hit);
      onNavigate(destination.route, destination.routeId);
    }
    onClose();
  }

  return (
    <div
      className="command-backdrop"
      data-command-surface=""
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
      ref={backdropRef}
    >
      <section
        aria-label="Worker commands"
        aria-modal="true"
        className="command-palette"
        data-screen-label="Command palette"
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
          <svg
            aria-hidden
            fill="none"
            height="16"
            stroke="currentColor"
            strokeLinecap="round"
            strokeWidth="1.9"
            viewBox="0 0 24 24"
            width="16"
          >
            <circle cx="11" cy="11" r="7" />
            <path d="m16.5 16.5 4.5 4.5" />
          </svg>
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
            placeholder="Go anywhere, change anything"
            ref={inputRef}
            role="combobox"
            value={query}
          />
          <kbd>esc</kbd>
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
          ref={resultsRef}
          role="listbox"
        >
          {visibleCommands.length > 0 && (
            <section
              aria-label="Navigation commands"
              className="command-group"
              role="group"
            >
              {visibleCommands.map((command) => {
                const key = commandKey(command);
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
                    <CommandIcon command={command} />
                    <span className="command-row-label">{command.label}</span>
                    <span className="command-row-hint">{command.hint ?? "Go"}</span>
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
                    <SearchResultIcon source={hit.source} />
                    <span className="command-row-label">{hit.title}</span>
                    <span className="command-result-source">
                      {SOURCE_LABELS[hit.source]}
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

function commandKey(command: Command): string {
  return `command:${command.route}:${command.routeId ?? ""}:${command.label}`;
}

function contentDestination(hit: FederatedSearchHit): {
  route: WorkerRoute;
  routeId: string | null;
} {
  if (hit.route === "operate") {
    return { route: "settings", routeId: "operations" };
  }
  return { route: hit.route, routeId: boundedRouteId(hit.route_id) };
}

function sourceStatusCopy(source: FederatedSearchSourceResult): string {
  if (source.status === "denied") return "Restricted";
  if (source.status === "unavailable") return "Unavailable";
  const count = `${source.count} ${source.count === 1 ? "result" : "results"}`;
  return source.truncated ? `${count} · more available` : count;
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

const COMMAND_ICON_PATHS: Record<string, string[]> = {
  chat: ["M12 5v14", "M5 12h14"],
  agents: [
    "M12 3.4a2.6 2.6 0 1 1 0 5.2 2.6 2.6 0 0 1 0-5.2z",
    "M5 20.4a2.4 2.4 0 1 1 0-4.8 2.4 2.4 0 0 1 0 4.8zM19 20.4a2.4 2.4 0 1 1 0-4.8 2.4 2.4 0 0 1 0 4.8z",
    "M12 8.6v3.2M5 15.6c0-1.9 1.6-3.5 3.5-3.5h7c1.9 0 3.5 1.6 3.5 3.5",
  ],
  integrations: ["M8 3v5M16 3v5", "M5.5 8h13v3a6.5 6.5 0 0 1-13 0z", "M12 17.5V21"],
  automations: ["M4.5 5.5h5v4h-5zM14.5 5.5h5v4h-5zM9.5 14.5h5v4h-5z", "M7 9.5v2.5h10V9.5M12 12v2.5"],
  "settings:you": ["M12 4.6a3.4 3.4 0 1 1 0 6.8 3.4 3.4 0 0 1 0-6.8z", "M5 20c0-3.6 3.1-6 7-6s7 2.4 7 6"],
  "settings:autonomy": ["M12 3l7 3v5.5c0 4.6-3 7.2-7 8.5-4-1.3-7-3.9-7-8.5V6z"],
  "settings:spend": ["M12 3.5a8.5 8.5 0 1 0 8.5 8.5", "M12 12l4.5-3.5"],
  "settings:shortcuts": ["M3.5 6.5h17v11h-17z", "M7 10h.01M11 10h.01M15 10h.01M8 14h8"],
  "settings:knowledge": ["M4.5 4.5h6a3 3 0 0 1 3 3v12a2.5 2.5 0 0 0-2.5-2.5h-6.5z", "M19.5 4.5h-6a3 3 0 0 0-3 3v12a2.5 2.5 0 0 1 2.5-2.5h6.5z"],
  "settings:overnight": ["M20 14.5A8.2 8.2 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5z"],
  "settings:health": ["M3 12h4l2-5 4 10 2-5h6"],
  "settings:organisation": ["M6.5 7.5v9", "M6.5 7.5a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM6.5 20.5a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM17.5 7.5a2 2 0 1 0 0-4 2 2 0 0 0 0 4z", "M17.5 7.5v2.5a3 3 0 0 1-3 3h-8"],
  "settings:advanced": ["M8.5 7.5L4 12l4.5 4.5M15.5 7.5L20 12l-4.5 4.5"],
  "settings:archived": ["M3.5 4.5h17v4h-17z", "M5 8.5v11h14v-11M10 12.5h4"],
  settings: ["M12 9.2a2.8 2.8 0 1 1 0 5.6 2.8 2.8 0 0 1 0-5.6z", "M4.5 12h2M17.5 12h2M12 4.5v2M12 17.5v2M6.7 6.7l1.4 1.4M15.9 15.9l1.4 1.4M17.3 6.7l-1.4 1.4M8.1 15.9l-1.4 1.4"],
  default: ["M5 4.5h14a1.5 1.5 0 0 1 1.5 1.5v8a1.5 1.5 0 0 1-1.5 1.5H9l-4.5 4V6A1.5 1.5 0 0 1 5 4.5z"],
};

function CommandIcon({ command }: { command: Command }) {
  const iconKey = command.routeId
    ? `${command.route}:${command.routeId}`
    : command.route;
  const paths = COMMAND_ICON_PATHS[iconKey]
    ?? COMMAND_ICON_PATHS[command.route]
    ?? COMMAND_ICON_PATHS.default!;
  return (
    <span aria-hidden className="command-row-icon">
      <svg fill="none" height="16" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.7" viewBox="0 0 24 24" width="16">
        {paths.map((path) => <path d={path} key={path} />)}
      </svg>
    </span>
  );
}

function SearchResultIcon({ source }: { source: FederatedSearchSource }) {
  return (
    <span aria-hidden className="command-row-icon" data-source={source}>
      <svg fill="none" height="16" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" viewBox="0 0 24 24" width="16">
        <circle cx="11" cy="11" r="6.5" />
        <path d="M15.8 15.8 20 20" />
      </svg>
    </span>
  );
}

function focusableElements(container: HTMLElement): HTMLElement[] {
  return Array.from(container.querySelectorAll<HTMLElement>(
    'input, button:not([disabled]), a[href], select, textarea, [tabindex]:not([tabindex="-1"])',
  )).filter((element) => !element.hasAttribute("hidden"));
}

function isolateBackgroundSiblings(surface: HTMLElement | null): () => void {
  const parent = surface?.parentElement;
  if (!surface || !parent) return () => undefined;
  const siblings = Array.from(parent.children).filter(
    (element): element is HTMLElement => (
      element instanceof HTMLElement && element !== surface
    ),
  );
  const snapshots = siblings.map((element) => ({
    element,
    inert: element.inert,
    inertAttribute: element.getAttribute("inert"),
    ariaHidden: element.getAttribute("aria-hidden"),
  }));
  for (const { element } of snapshots) {
    element.inert = true;
    element.setAttribute("aria-hidden", "true");
  }
  return () => {
    for (const snapshot of snapshots) {
      snapshot.element.inert = snapshot.inert;
      if (snapshot.inertAttribute === null) {
        snapshot.element.removeAttribute("inert");
      } else {
        snapshot.element.setAttribute("inert", snapshot.inertAttribute);
      }
      if (snapshot.ariaHidden === null) {
        snapshot.element.removeAttribute("aria-hidden");
      } else {
        snapshot.element.setAttribute("aria-hidden", snapshot.ariaHidden);
      }
    }
  };
}
