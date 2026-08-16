import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
  type MutableRefObject,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
  type Ref,
} from "react";

import { FamiliarBadge } from "../familiar/FamiliarBadge";
import {
  type TaskInspectorActivity,
  type TaskInspectorOutput,
  type TaskInspectorSource,
  type TaskInspectorStatus,
  type TaskInspectorSubagent,
  type TaskInspectorViewModel,
} from "./TaskInspectorModel";
import "./TaskInspector.css";

const DEFAULT_WIDTH = 316;
const DEFAULT_MIN_WIDTH = 272;
const DEFAULT_MAX_WIDTH = 520;
const KEYBOARD_RESIZE_STEP = 8;

interface TaskInspectorCommonProps {
  model: TaskInspectorViewModel;
  className?: string;
  panelRef?: Ref<HTMLElement>;
  width?: number;
  defaultWidth?: number;
  minWidth?: number;
  maxWidth?: number;
  onWidthChange?(width: number): void;
  onCreateOutput?(): void;
  onSelectOutput?(output: TaskInspectorOutput): void;
  materializedOutputIds?: ReadonlySet<string>;
  onOpenOutput?(output: TaskInspectorOutput): void;
  onRevealOutput?(output: TaskInspectorOutput): void;
  hasMoreOutputs?: boolean;
  outputsLoading?: boolean;
  outputError?: string;
  onLoadMoreOutputs?(): void;
  onOpenSubagents?(): void;
  onSelectActivity?(activity: TaskInspectorActivity): void;
  onSelectSource?(source: TaskInspectorSource): void;
  onManageSources?(): void;
  onInspectRun?(): void;
  /** Optional explicit return target for a dismissible inspector. */
  returnFocusRef?: { readonly current: HTMLElement | null };
}
type TaskInspectorModeProps =
  | { mode?: "rail"; open?: boolean; onClose?(): void }
  | { mode: "overlay"; open: boolean; onClose(): void }
  | { mode: "sheet"; open: boolean; onClose(): void };

export type TaskInspectorProps = TaskInspectorCommonProps & TaskInspectorModeProps;

export function TaskInspector(props: TaskInspectorProps) {
  const {
    model,
    className,
    panelRef,
    width,
    defaultWidth = DEFAULT_WIDTH,
    minWidth = DEFAULT_MIN_WIDTH,
    maxWidth = DEFAULT_MAX_WIDTH,
    onWidthChange,
    onCreateOutput,
    onSelectOutput,
    materializedOutputIds,
    onOpenOutput,
    onRevealOutput,
    hasMoreOutputs = false,
    outputsLoading = false,
    outputError = "",
    onLoadMoreOutputs,
    onOpenSubagents,
    onSelectActivity,
    onSelectSource,
    onManageSources,
    onInspectRun,
    returnFocusRef,
  } = props;
  const mode = props.mode ?? "rail";
  const open = props.open ?? true;
  const onClose = props.onClose;
  const safeMinWidth = Math.min(minWidth, maxWidth);
  const safeMaxWidth = Math.max(minWidth, maxWidth);
  const [uncontrolledWidth, setUncontrolledWidth] = useState(() => (
    clamp(defaultWidth, safeMinWidth, safeMaxWidth)
  ));
  const resolvedWidth = clamp(width ?? uncontrolledWidth, safeMinWidth, safeMaxWidth);
  const currentWidthRef = useRef(resolvedWidth);
  const panelNodeRef = useRef<HTMLElement | null>(null);
  const scrimNodeRef = useRef<HTMLButtonElement | null>(null);
  const closeButtonRef = useRef<HTMLButtonElement | null>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);
  const resizeCleanupRef = useRef<(() => void) | null>(null);
  const [resizing, setResizing] = useState(false);
  const titleId = `task-inspector-${useId().replaceAll(":", "")}`;

  currentWidthRef.current = resolvedWidth;

  const setPanelRef = useCallback((node: HTMLElement | null) => {
    panelNodeRef.current = node;
    assignRef(panelRef, node);
  }, [panelRef]);

  const updateWidth = useCallback((nextWidth: number) => {
    const next = clamp(Math.round(nextWidth), safeMinWidth, safeMaxWidth);
    currentWidthRef.current = next;
    if (width === undefined) setUncontrolledWidth(next);
    onWidthChange?.(next);
  }, [onWidthChange, safeMaxWidth, safeMinWidth, width]);

  useEffect(() => {
    if (width !== undefined) return;
    setUncontrolledWidth((current) => clamp(current, safeMinWidth, safeMaxWidth));
  }, [safeMaxWidth, safeMinWidth, width]);

  useEffect(() => () => resizeCleanupRef.current?.(), []);

  useEffect(() => {
    if (mode !== "sheet" || !open) return;
    previousFocusRef.current = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null;
    const restoreBackground = isolateBackgroundBranches([
      panelNodeRef.current,
      scrimNodeRef.current,
    ]);
    const priorOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    closeButtonRef.current?.focus();

    return () => {
      document.body.style.overflow = priorOverflow;
      restoreBackground();
      restoreFocus(returnFocusRef, previousFocusRef.current);
      previousFocusRef.current = null;
    };
  }, [mode, open, returnFocusRef]);

  useEffect(() => {
    if (mode === "rail" || !open) return;
    const handleDocumentKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.defaultPrevented) return;
      const panel = panelNodeRef.current;
      if (!panel) return;
      if (event.key === "Escape") {
        event.preventDefault();
        onClose?.();
        return;
      }
      if (event.key !== "Tab" || mode !== "sheet") return;
      const focusable = focusableElements(panel);
      if (focusable.length === 0) {
        event.preventDefault();
        panel.focus();
        return;
      }
      const first = focusable[0]!;
      const last = focusable.at(-1)!;
      const active = document.activeElement;
      if (!panel.contains(active)) {
        event.preventDefault();
        (event.shiftKey ? last : first).focus();
      } else if (event.shiftKey && active === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && active === last) {
        event.preventDefault();
        first.focus();
      }
    };
    window.addEventListener("keydown", handleDocumentKeyDown);
    return () => window.removeEventListener("keydown", handleDocumentKeyDown);
  }, [mode, onClose, open]);

  // Outputs is the stable first section even when empty. Keeping the inspector
  // mounted avoids a layout jump and truthfully distinguishes "No outputs"
  // from an unavailable/failed task-details surface.
  const visible = true;
  if (!visible) return null;

  function beginResize(event: ReactPointerEvent<HTMLDivElement>) {
    if (mode !== "rail" || event.button !== 0) return;
    event.preventDefault();
    resizeCleanupRef.current?.();
    const pointerId = event.pointerId;
    const startX = event.clientX;
    const startWidth = currentWidthRef.current;
    event.currentTarget.setPointerCapture?.(pointerId);
    setResizing(true);

    const move = (moveEvent: PointerEvent) => {
      if (moveEvent.pointerId !== pointerId) return;
      updateWidth(startWidth + startX - moveEvent.clientX);
    };
    const finish = (upEvent: PointerEvent) => {
      if (upEvent.pointerId !== pointerId) return;
      cleanup();
    };
    const cleanup = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", finish);
      window.removeEventListener("pointercancel", finish);
      resizeCleanupRef.current = null;
      setResizing(false);
    };
    resizeCleanupRef.current = cleanup;
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", finish);
    window.addEventListener("pointercancel", finish);
  }

  function resizeFromKeyboard(event: KeyboardEvent<HTMLDivElement>) {
    const step = event.shiftKey ? KEYBOARD_RESIZE_STEP * 4 : KEYBOARD_RESIZE_STEP;
    let next: number | null = null;
    if (event.key === "ArrowLeft") next = currentWidthRef.current + step;
    if (event.key === "ArrowRight") next = currentWidthRef.current - step;
    if (event.key === "Home") next = safeMinWidth;
    if (event.key === "End") next = safeMaxWidth;
    if (next === null) return;
    event.preventDefault();
    updateWidth(next);
  }

  function handleSheetKeyDown(event: KeyboardEvent<HTMLElement>) {
    if (mode !== "sheet" || !open) return;
    if (event.key === "Escape") {
      event.preventDefault();
      onClose?.();
      return;
    }
    if (event.key !== "Tab") return;
    const panel = panelNodeRef.current;
    if (!panel) return;
    const focusable = focusableElements(panel);
    if (focusable.length === 0) {
      event.preventDefault();
      panel.focus();
      return;
    }
    const first = focusable[0]!;
    const last = focusable.at(-1)!;
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  const aside = (
    <aside
      {...(mode !== "rail" && !open ? { inert: "" } : {})}
      aria-hidden={mode !== "rail" && !open ? true : undefined}
      aria-label={mode === "sheet" ? undefined : "Task details"}
      aria-labelledby={mode === "sheet" ? titleId : undefined}
      aria-modal={mode === "sheet" ? true : undefined}
      className={[
        "task-inspector right-rail",
        `task-inspector--${mode}`,
        mode === "sheet" ? "task-details-sheet" : "",
        open ? "task-inspector--open" : "",
        resizing ? "task-inspector--resizing" : "",
        className ?? "",
      ].filter(Boolean).join(" ")}
      data-testid="task-inspector"
      id="worker-task-details"
      onKeyDown={handleSheetKeyDown}
      ref={setPanelRef}
      role={mode === "sheet" ? "dialog" : undefined}
      style={{ "--task-inspector-width": `${resolvedWidth}px` } as CSSProperties}
      tabIndex={mode === "sheet" ? -1 : undefined}
    >
      {mode === "rail" && (
        <div
          aria-label="Resize task details"
          aria-orientation="vertical"
          aria-valuemax={safeMaxWidth}
          aria-valuemin={safeMinWidth}
          aria-valuenow={resolvedWidth}
          aria-valuetext={`${resolvedWidth} pixels wide`}
          className="task-inspector__resize-handle"
          onDoubleClick={() => updateWidth(defaultWidth)}
          onKeyDown={resizeFromKeyboard}
          onPointerDown={beginResize}
          role="separator"
          tabIndex={0}
        />
      )}

      {mode === "sheet" && (
        <header className="task-inspector__sheet-header">
          <h2 id={titleId}>Task details</h2>
          <button
            aria-label="Close task details"
            className="task-inspector__close"
            data-task-details-close
            onClick={onClose}
            ref={closeButtonRef}
            type="button"
          >
            <CloseIcon />
          </button>
        </header>
      )}

      <div className="task-inspector__surface rail-card chat-rail-glass">
        <InspectorGroup
          action={onCreateOutput ? "+" : undefined}
          actionLabel={onCreateOutput ? "Create output" : undefined}
          onAction={onCreateOutput}
          title="Outputs"
        >
            {model.outputs.length === 0 && (
              <InspectorRow
                label={onCreateOutput ? "Create a file or site" : "No outputs"}
                onClick={onCreateOutput}
                quiet
              />
            )}
            {model.outputs.map((output) => (
              <div className="task-inspector__output" key={output.id}>
                <InspectorRow
                  label={output.name}
                  mark={<OutputIcon />}
                  meta={outputMetadata(output)}
                  onClick={onSelectOutput ? () => onSelectOutput(output) : undefined}
                />
                {materializedOutputIds?.has(output.id) && (onOpenOutput || onRevealOutput) && (
                  <span className="task-inspector__output-actions">
                    {onOpenOutput && (
                      <button onClick={() => onOpenOutput(output)} type="button">Open</button>
                    )}
                    {onRevealOutput && (
                      <button onClick={() => onRevealOutput(output)} type="button">Reveal</button>
                    )}
                  </span>
                )}
              </div>
            ))}
            {hasMoreOutputs && onLoadMoreOutputs && (
              <button
                aria-label={outputsLoading ? "Loading more outputs" : "Load more outputs"}
                className="task-inspector__load-more"
                disabled={outputsLoading}
                onClick={onLoadMoreOutputs}
                type="button"
              >
                {outputsLoading ? "Loading…" : "Load more"}
              </button>
            )}
            {outputError && <p className="task-inspector__error" role="alert">{outputError}</p>}
        </InspectorGroup>

        {model.subagents.length > 0 && (
          <InspectorGroup title="Subagents">
            <InspectorRow
              label={subagentSummary(model.subagents)}
              mark={<SubagentStack subagents={model.subagents} />}
              markWide
              onClick={onOpenSubagents}
              quiet
            />
          </InspectorGroup>
        )}

        {model.backgroundProcesses.length > 0 && (
          <InspectorGroup title="Background processes">
            {model.backgroundProcesses.map((activity) => (
              <ActivityRow activity={activity} key={activity.id} onSelect={onSelectActivity} />
            ))}
          </InspectorGroup>
        )}

        {model.computerUse.length > 0 && (
          <InspectorGroup title="Computer Use">
            {model.computerUse.map((activity) => (
              <ActivityRow activity={activity} key={activity.id} onSelect={onSelectActivity} />
            ))}
          </InspectorGroup>
        )}

        {model.sources.length > 0 && (
          <InspectorGroup
            action={onManageSources ? "+" : undefined}
            actionLabel={onManageSources ? "Manage sources" : undefined}
            onAction={onManageSources}
            title="Sources"
          >
            {model.sources.map((source) => (
              <InspectorRow
                key={source.id}
                label={source.name}
                mark={<SourceIcon source={source} />}
                meta={source.kind === "attachment" && source.size !== undefined
                  ? formatBytes(source.size)
                  : undefined}
                onClick={onSelectSource ? () => onSelectSource(source) : undefined}
              />
            ))}
            {onManageSources && (
              <InspectorRow
                label="View all"
                mark={<LinkIcon />}
                onClick={onManageSources}
                quiet
              />
            )}
          </InspectorGroup>
        )}

        {model.runActivity.length > 0 && (
          <InspectorGroup
            action={onInspectRun ? "Open" : undefined}
            actionLabel={onInspectRun ? "Open run activity" : undefined}
            onAction={onInspectRun}
            title="Run activity"
          >
            {model.runActivity.map((activity) => (
              <ActivityRow activity={activity} key={`${activity.kind}:${activity.id}`} onSelect={onSelectActivity} />
            ))}
          </InspectorGroup>
        )}
      </div>
    </aside>
  );

  if (mode !== "sheet") return aside;
  return (
    <>
      {open && (
        <button
          aria-label="Dismiss task details"
          className="task-inspector__scrim"
          onClick={onClose}
          ref={scrimNodeRef}
          type="button"
        />
      )}
      {aside}
    </>
  );
}

function InspectorGroup({
  title,
  action,
  actionLabel,
  onAction,
  children,
}: {
  title: string;
  action?: string;
  actionLabel?: string;
  onAction?(): void;
  children: ReactNode;
}) {
  return (
    <section aria-label={title} className="task-inspector__group rail-group">
      <div className="task-inspector__group-header rail-group-head">
        <span>{title}</span>
        {action !== undefined && onAction && (
          <button
            aria-label={actionLabel}
            className="task-inspector__group-action"
            onClick={onAction}
            type="button"
          >
            {action}
          </button>
        )}
      </div>
      <div className="task-inspector__group-body rail-body">{children}</div>
    </section>
  );
}

function InspectorRow({
  mark,
  label,
  meta,
  quiet = false,
  status,
  onClick,
  markWide = false,
}: {
  mark?: ReactNode;
  markWide?: boolean;
  label: string;
  meta?: string;
  quiet?: boolean;
  status?: TaskInspectorStatus;
  onClick?(): void;
}) {
  const contents = (
    <>
      {mark && <span className={[
        "task-inspector__mark rail-mark",
        markWide ? "task-inspector__mark--wide" : "",
      ].filter(Boolean).join(" ")}>{mark}</span>}
      <span className="task-inspector__label rail-label" data-quiet={quiet || undefined}>{label}</span>
      {meta && <span className="task-inspector__meta rail-meta">{meta}</span>}
      {status && <StatusDot status={status} />}
    </>
  );
  if (!onClick) return <div className="task-inspector__row rail-row">{contents}</div>;
  return (
    <button className="task-inspector__row task-inspector__row--interactive rail-row" data-interactive="true" onClick={onClick} type="button">
      {contents}
    </button>
  );
}

function ActivityRow({
  activity,
  onSelect,
}: {
  activity: TaskInspectorActivity;
  onSelect?(activity: TaskInspectorActivity): void;
}) {
  return (
    <InspectorRow
      label={activity.label}
      mark={<ActivityIcon kind={activity.kind} status={activity.status} />}
      meta={activity.status === "done" ? undefined : statusLabel(activity.status)}
      onClick={onSelect ? () => onSelect(activity) : undefined}
      status={activity.status}
    />
  );
}

function SubagentStack({ subagents }: { subagents: TaskInspectorSubagent[] }) {
  return (
    <span
      aria-label={subagents.map((subagent) => subagent.name).join(", ")}
      className="task-inspector__agent-stack rail-agent-stack"
      role="img"
    >
      {subagents.slice(0, 3).map((subagent) => (
        <FamiliarBadge
          decorative
          genotype={subagent.familiarGenotype}
          key={subagent.id}
          label={subagent.name}
          size={18}
          state={["running", "waiting"].includes(subagent.status) ? "working" : "ready"}
        />
      ))}
    </span>
  );
}

function StatusDot({ status }: { status: TaskInspectorStatus }) {
  return (
    <span
      aria-label={statusLabel(status)}
      className="task-inspector__status"
      data-status={status}
      role="img"
    />
  );
}

function OutputIcon() {
  return (
    <svg aria-hidden className="task-inspector__icon" fill="none" viewBox="0 0 24 24">
      <path d="M6 3.5h8l4 4V20.5H6z" />
      <path d="M14 3.5v4h4M9 12h6M9 15.5h4.5" />
    </svg>
  );
}

function ActivityIcon({
  kind,
  status,
}: {
  kind: TaskInspectorActivity["kind"];
  status: TaskInspectorStatus;
}) {
  const className = "task-inspector__icon rail-tool-mark";
  const tone = statusTone(status);
  if (kind === "background") {
    return (
      <svg aria-hidden className={className} data-kind="background" data-tone={tone} fill="none" viewBox="0 0 24 24">
        <rect height="16" rx="2.5" width="18" x="3" y="4" />
        <path d="m7.5 9 2.5 2.5L7.5 14M13 14h3.5" />
      </svg>
    );
  }
  if (kind === "computer") {
    return (
      <svg aria-hidden className={className} data-kind="computer" data-tone={tone} fill="none" viewBox="0 0 24 24">
        <rect height="11" rx="1.5" width="14" x="2.5" y="5" />
        <rect height="11" rx="1.5" width="14" x="7.5" y="8" />
      </svg>
    );
  }
  return (
    <svg aria-hidden className={className} data-kind={kind} data-tone={tone} fill="none" viewBox="0 0 24 24">
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 7.5v5l3 2" />
    </svg>
  );
}

function SourceIcon({ source }: { source: TaskInspectorSource }) {
  if (source.kind === "integration" && source.integrationId.toLowerCase() === "figma") {
    return (
      <svg
        aria-hidden
        className="task-inspector__figma rail-integration-mark"
        data-integration="figma"
        viewBox="0 0 24 24"
      >
        <path d="M8.5 2H12v7H8.5a3.5 3.5 0 1 1 0-7Z" fill="#f24e1e" />
        <path d="M12 2h3.5a3.5 3.5 0 0 1 0 7H12Z" fill="#ff7262" />
        <path d="M8.5 9H12v7H8.5a3.5 3.5 0 1 1 0-7Z" fill="#a259ff" />
        <circle cx="15.5" cy="12.5" fill="#1abcfe" r="3.5" />
        <path d="M8.5 16H12v3.5A3.5 3.5 0 1 1 8.5 16Z" fill="#0acf83" />
      </svg>
    );
  }
  const label = source.kind === "integration"
    ? source.name.slice(0, 1).toUpperCase()
    : source.mediaType.startsWith("image/") ? "▦" : "≡";
  return (
    <span
      aria-hidden
      className={source.kind === "integration"
        ? "task-inspector__source-glyph rail-integration-mark"
        : "task-inspector__source-glyph"}
      data-integration={source.kind === "integration" ? source.integrationId : undefined}
    >
      {label}
    </span>
  );
}

function LinkIcon() {
  return (
    <svg aria-hidden className="task-inspector__icon" fill="none" viewBox="0 0 24 24">
      <path d="m9.5 14.5 5-5M7.2 17.8l-1.1 1.1a3.5 3.5 0 0 1-5-5l3.2-3.2a3.5 3.5 0 0 1 5 0M16.8 6.2l1.1-1.1a3.5 3.5 0 0 1 5 5l-3.2 3.2a3.5 3.5 0 0 1-5 0" />
    </svg>
  );
}

function CloseIcon() {
  return (
    <svg aria-hidden fill="none" viewBox="0 0 24 24">
      <path d="m7 7 10 10M17 7 7 17" />
    </svg>
  );
}

function outputMetadata(output: TaskInspectorOutput): string {
  return `${output.mediaType} · rev ${output.revision}`;
}

function statusLabel(status: TaskInspectorStatus): string {
  if (status === "running") return "Running";
  if (status === "waiting") return "waiting for approval";
  if (status === "done") return "Done";
  if (status === "paused") return "Paused";
  if (status === "degraded") return "Degraded";
  if (status === "skipped") return "Skipped";
  if (status === "failed") return "did not complete";
  return "Status unknown";
}

function statusTone(status: TaskInspectorStatus): "green" | "amber" | "red" | "neutral" | "unknown" {
  if (status === "running" || status === "done") return "green";
  if (status === "waiting" || status === "paused" || status === "degraded") return "amber";
  if (status === "skipped") return "neutral";
  if (status === "failed") return "red";
  return "unknown";
}

function subagentSummary(subagents: TaskInspectorSubagent[]): string {
  const order: TaskInspectorStatus[] = [
    "done",
    "running",
    "waiting",
    "degraded",
    "skipped",
    "failed",
    "paused",
    "unknown",
  ];
  return order.flatMap((status) => {
    const count = subagents.filter((subagent) => subagent.status === status).length;
    if (count === 0) return [];
    const label = status === "running" ? "working" : status === "unknown" ? "status unknown" : status;
    return [`${count} ${label}`];
  }).join(" · ");
}

function formatBytes(value: number): string {
  if (value < 1_024) return `${value} B`;
  if (value < 1_048_576) return `${Math.ceil(value / 1_024)} KB`;
  return `${(value / 1_048_576).toFixed(1)} MB`;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function assignRef<T>(ref: Ref<T> | undefined, value: T | null) {
  if (typeof ref === "function") ref(value);
  else if (ref) (ref as MutableRefObject<T | null>).current = value;
}

function restoreFocus(
  returnFocusRef: TaskInspectorCommonProps["returnFocusRef"],
  fallback: HTMLElement | null,
) {
  const target = returnFocusRef?.current ?? fallback;
  if (target?.isConnected) target.focus();
}

function focusableElements(container: HTMLElement): HTMLElement[] {
  return [...container.querySelectorAll<HTMLElement>(
    "a[href], button:not([disabled]), input:not([disabled]), "
    + "select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])",
  )].filter((element) => (
    element.getAttribute("aria-hidden") !== "true"
    && !element.hasAttribute("inert")
  ));
}

interface BackgroundSnapshot {
  element: HTMLElement;
  inert: boolean;
  inertAttribute: string | null;
  ariaHidden: string | null;
}

/**
 * Isolate every sibling branch between an inline modal and <body>. Unlike a
 * portal, the task sheet can be nested inside ChatView, so isolating only its
 * immediate siblings would leave the shell and route controls exposed. The
 * scrim and dialog are both protected branches, and all prior states are
 * restored exactly for nested-modal safety.
 */
function isolateBackgroundBranches(
  protectedNodes: Array<HTMLElement | null>,
): () => void {
  const nodes = protectedNodes.filter((node): node is HTMLElement => node !== null);
  if (nodes.length === 0) return () => undefined;

  const parents = new Set<HTMLElement>();
  for (const node of nodes) {
    let current: HTMLElement | null = node;
    while (current?.parentElement) {
      const parent: HTMLElement = current.parentElement;
      parents.add(parent);
      if (parent === document.body) break;
      current = parent;
    }
  }

  const snapshots: BackgroundSnapshot[] = [];
  for (const parent of parents) {
    for (const child of parent.children) {
      if (!(child instanceof HTMLElement)) continue;
      if (nodes.some((node) => child === node || child.contains(node))) continue;
      snapshots.push({
        element: child,
        inert: child.inert,
        inertAttribute: child.getAttribute("inert"),
        ariaHidden: child.getAttribute("aria-hidden"),
      });
      child.inert = true;
      child.setAttribute("aria-hidden", "true");
    }
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
