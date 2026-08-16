import {
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";
import type {
  AgentCapabilityAuthorInfo,
  ModelEndpointInfo,
  PermanentFleetApplyResponse,
  PermanentFleetHead,
  PermanentFleetHierarchy,
  PermanentFleetResponse,
} from "@wlilley93/boltrig-web-sdk";

import { client } from "../client";
import {
  ExactApprovalFinalizer,
  governedResultReason,
  useExactApprovalFinalizer,
} from "./ExactApprovalFinalizer";
import { FamiliarBadge } from "./familiar/FamiliarBadge";

import "./PermanentFleetTopology.css";

function blankHead(chief: boolean, index = 1): PermanentFleetHead {
  return {
    name: chief ? "chief-of-staff" : `department-head-${index}`,
    routing_id: chief ? "cos" : `department-${index}`,
    purpose: chief
      ? "Route work across departments"
      : `Own department ${index} work`,
    brief: "",
    runtime: "codex",
    model_endpoint: null,
    supported_skills: ["*"],
    max_depth: chief ? 4 : 3,
    cost_tier: "standard",
    budget: null,
  };
}

const blankHierarchy = (): PermanentFleetHierarchy => ({
  chief: blankHead(true),
  departments: [blankHead(false)],
});

type FleetNodeKind = "chief" | "department" | "profile";

type FleetNode = {
  id: string;
  name: string;
  kind: FleetNodeKind;
  parentId: string | null;
  children: FleetNode[];
  head?: PermanentFleetHead;
  profile?: AgentCapabilityAuthorInfo;
};

type PositionedFleetNode = {
  node: FleetNode;
  x: number;
  y: number;
};

type FleetLayout = {
  nodes: PositionedFleetNode[];
  width: number;
  height: number;
};

type PermanentFleetTopologyProps = {
  profiles?: AgentCapabilityAuthorInfo[];
  askingActors?: ReadonlySet<string> | null;
  lifecycleBusy?: string;
  onCreateProfile?(parentName: string | null): void;
  onEditProfile?(profile: AgentCapabilityAuthorInfo): void;
  onLifecycle?(profile: AgentCapabilityAuthorInfo): void;
};

const AUTHORITY_CHANNELS = [
  ["read", "read"],
  ["write", "write"],
  ["send", "send"],
  ["spend", "spend"],
  ["delegate", "delegate"],
] as const;

const FLEET_NODE_WIDTH = 196;
const FLEET_PLANE_GUTTER = 1;

const FLEET_MODAL_FOCUSABLE = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "[contenteditable='true']",
  "[tabindex]:not([tabindex='-1'])",
].join(",");

function modalOwnedRoots(dialog: HTMLElement): HTMLElement[] {
  return (dialog.getAttribute("aria-owns") ?? "")
    .split(/\s+/)
    .filter(Boolean)
    .map((id) => document.getElementById(id))
    .filter((element): element is HTMLElement => Boolean(element));
}

function modalFocusableElements(dialog: HTMLElement): HTMLElement[] {
  return [dialog, ...modalOwnedRoots(dialog)]
    .flatMap((root) => [...root.querySelectorAll<HTMLElement>(FLEET_MODAL_FOCUSABLE)])
    .filter((element) => (
      !element.hidden
      && element.getAttribute("aria-hidden") !== "true"
      && !element.closest("[inert]")
    ));
}

function modalContains(dialog: HTMLElement, element: Element | null): boolean {
  return Boolean(element) && (
    dialog.contains(element)
    || modalOwnedRoots(dialog).some((root) => root.contains(element))
  );
}

function useFleetModal({
  active,
  onClose,
  opener,
}: {
  active: boolean;
  onClose(): void;
  opener: HTMLElement | null;
}) {
  const dialogRef = useRef<HTMLElement | null>(null);
  const openerRef = useRef<HTMLElement | null>(opener);
  const activatedRef = useRef(false);

  useLayoutEffect(() => {
    if (!active) return;
    if (!openerRef.current && document.activeElement instanceof HTMLElement) {
      openerRef.current = document.activeElement;
    }
    if (activatedRef.current) return;
    activatedRef.current = true;
    const dialog = dialogRef.current;
    const initial = dialog?.querySelector<HTMLElement>("[data-fleet-modal-initial]:not(:disabled)")
      ?? dialog?.querySelector<HTMLElement>("[data-fleet-modal-close]:not(:disabled)")
      ?? (dialog ? modalFocusableElements(dialog)[0] : null)
      ?? dialog;
    initial?.focus();
  }, [active]);

  useEffect(() => {
    if (!active) return;
    const handleKeyDown = (event: globalThis.KeyboardEvent) => {
      const dialog = dialogRef.current;
      if (!dialog) return;
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        onClose();
        return;
      }
      if (event.key !== "Tab") return;
      const focusable = modalFocusableElements(dialog);
      if (focusable.length === 0) {
        event.preventDefault();
        dialog.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const focused = document.activeElement;
      if (event.shiftKey && (focused === first || !modalContains(dialog, focused))) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (focused === last || !modalContains(dialog, focused))) {
        event.preventDefault();
        first.focus();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [active, onClose]);

  // Passive cleanup runs after the inert background (or underlying modal) has
  // been restored, so the exact trigger can receive focus again.
  useEffect(() => () => {
    if (openerRef.current?.isConnected) openerRef.current.focus();
  }, []);

  return dialogRef;
}

function FleetModalShell({
  active = true,
  ariaLabel,
  cardClassName,
  children,
  onClose,
  opener,
  ownedContent,
  ownedId,
  scrimClassName = "",
}: {
  active?: boolean;
  ariaLabel: string;
  cardClassName: string;
  children: ReactNode;
  onClose(): void;
  opener: HTMLElement | null;
  ownedContent?: ReactNode;
  ownedId?: string;
  scrimClassName?: string;
}) {
  const dialogRef = useFleetModal({ active, onClose, opener });
  return (
    <div
      aria-hidden={active ? undefined : "true"}
      className={`fleet-scrim${scrimClassName ? ` ${scrimClassName}` : ""}`}
      onClickCapture={active ? undefined : (event) => {
        event.preventDefault();
        event.stopPropagation();
      }}
      onMouseDown={(event) => {
        if (active && event.target === event.currentTarget) onClose();
      }}
      role="presentation"
      {...(active ? {} : { inert: "" })}
    >
      <section
        aria-label={ariaLabel}
        aria-modal={active ? "true" : undefined}
        aria-owns={active ? ownedId : undefined}
        className={cardClassName}
        ref={dialogRef}
        role="dialog"
        tabIndex={-1}
      >
        {children}
      </section>
      {ownedContent}
    </div>
  );
}

function buildFleetForest(
  hierarchy: PermanentFleetHierarchy | null | undefined,
  profiles: AgentCapabilityAuthorInfo[],
): FleetNode[] {
  const profileByName = new Map(
    profiles.map((profile) => [profile.name.trim().toLowerCase(), profile]),
  );
  const matchingProfile = (head: PermanentFleetHead) => (
    profileByName.get(head.name.trim().toLowerCase())
    ?? profileByName.get(head.routing_id.trim().toLowerCase())
  );
  const placedProfiles = new Set<string>();
  const roots: FleetNode[] = [];

  if (hierarchy) {
    const chiefProfile = matchingProfile(hierarchy.chief);
    if (chiefProfile) placedProfiles.add(chiefProfile.name);
    const chief: FleetNode = {
      id: `head:${hierarchy.chief.name}`,
      name: hierarchy.chief.name,
      kind: "chief",
      parentId: null,
      children: [],
      head: hierarchy.chief,
      profile: chiefProfile,
    };
    hierarchy.departments.forEach((head) => {
      const profile = matchingProfile(head);
      if (profile) placedProfiles.add(profile.name);
      chief.children.push({
        id: `head:${head.name}`,
        name: head.name,
        kind: "department",
        parentId: chief.id,
        children: [],
        head,
        profile,
      });
    });
    roots.push(chief);
  }

  profiles
    .filter((profile) => !placedProfiles.has(profile.name))
    .slice()
    .sort((left, right) => left.name.localeCompare(right.name))
    .forEach((profile) => {
      roots.push({
        id: `profile:${profile.name}`,
        name: profile.name,
        kind: "profile",
        parentId: null,
        children: [],
        profile,
      });
    });

  return roots;
}

function layoutFleet(roots: FleetNode[]): FleetLayout {
  const nodes: PositionedFleetNode[] = [];
  let nextLeaf = 0;
  let maxDepth = 0;

  function place(node: FleetNode, depth: number): number {
    maxDepth = Math.max(maxDepth, depth);
    const childXs = node.children.map((child) => place(child, depth + 1));
    const x = childXs.length > 0
      ? (childXs[0] + childXs[childXs.length - 1]) / 2
      : FLEET_NODE_WIDTH / 2 + nextLeaf++ * FLEET_NODE_WIDTH;
    nodes.push({ node, x, y: 46 + depth * 98 });
    return x;
  }

  roots.forEach((root) => place(root, 0));
  const width = Math.max(
    760,
    Math.max(nextLeaf, 1) * FLEET_NODE_WIDTH + FLEET_PLANE_GUTTER * 2,
  );
  const left = nodes.length > 0 ? Math.min(...nodes.map((position) => position.x)) : 0;
  const right = nodes.length > 0 ? Math.max(...nodes.map((position) => position.x)) : 0;
  const offset = width / 2 - (left + right) / 2;
  return {
    // The decided fleet canvas positions the authored forest around its centre.
    // A six-head authored row is exactly six fixed-width cards. Keep that
    // truthful row intact, with a one-pixel pan gutter on either edge, then
    // centre smaller forests within the same deterministic plane.
    nodes: nodes.map((position) => ({ ...position, x: position.x + offset })),
    width,
    height: Math.max(260, 46 + maxDepth * 98 + 88),
  };
}

function nodeRole(node: FleetNode): string {
  if (node.kind === "chief") return "Chief of Staff";
  if (node.kind === "department") return "Department head";
  return node.profile?.is_ephemeral ? "Ephemeral profile" : "Persistent profile";
}

function topologyStateLabel(state: PermanentFleetResponse | null): string {
  if (state?.apply_state === "startup_applied_liveness_unknown") {
    return "startup applied · liveness unknown";
  }
  if (state?.apply_state === "restart_required") return "restart required";
  return "not configured";
}

function headStateLabel(state: PermanentFleetResponse | null): string {
  if (state?.apply_state === "startup_applied_liveness_unknown") {
    return "policy constructed · liveness unknown";
  }
  if (state?.apply_state === "restart_required") return "desired · restart required";
  return "desired · not configured";
}

function profileStateLabel(
  profile: AgentCapabilityAuthorInfo,
  askingActors: ReadonlySet<string> | null,
): string {
  if (askingActors?.has(profile.name) && profile.is_active) return "asking";
  return profile.status;
}

function profileTone(
  profile: AgentCapabilityAuthorInfo | undefined,
  askingActors: ReadonlySet<string> | null,
  state: PermanentFleetResponse | null,
): "asking" | "warning" | "quiet" | "unknown" {
  if (profile && askingActors?.has(profile.name) && profile.is_active) return "asking";
  if (state?.apply_state === "restart_required") return "warning";
  if (profile?.status === "retired") return "quiet";
  return "unknown";
}

function authorityArcPath(index: number, size: number): string {
  const radius = size / 2 - 2.2;
  const centre = size / 2;
  const gap = 0.17;
  const start = -Math.PI / 2 + (index / 5) * Math.PI * 2 + gap;
  const end = -Math.PI / 2 + ((index + 1) / 5) * Math.PI * 2 - gap;
  const x0 = (centre + Math.cos(start) * radius).toFixed(2);
  const y0 = (centre + Math.sin(start) * radius).toFixed(2);
  const x1 = (centre + Math.cos(end) * radius).toFixed(2);
  const y1 = (centre + Math.sin(end) * radius).toFixed(2);
  return `M${x0} ${y0}A${radius} ${radius} 0 0 1 ${x1} ${y1}`;
}

type PermanentFleetMutation = {
  hierarchy: PermanentFleetHierarchy;
  referenceGeneration: string | null;
  referenceRevision: number | null;
};

function sameRouteInput(left: unknown, right: unknown): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}

export function PermanentFleetTopology({
  profiles = [],
  askingActors = null,
  lifecycleBusy = "",
  onCreateProfile,
  onEditProfile,
  onLifecycle,
}: PermanentFleetTopologyProps = {}) {
  const [state, setState] = useState<PermanentFleetResponse | null>(null);
  const [draft, setDraft] = useState<PermanentFleetHierarchy>(blankHierarchy);
  const [endpoints, setEndpoints] = useState<ModelEndpointInfo[]>([]);
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [childParent, setChildParent] = useState<FleetNode | null>(null);
  const canvasRef = useRef<HTMLDivElement | null>(null);
  const inspectorOpenerRef = useRef<HTMLElement | null>(null);
  const childOpenerRef = useRef<HTMLElement | null>(null);
  const editorOpenerRef = useRef<HTMLElement | null>(null);

  const finalizer = useExactApprovalFinalizer<
    PermanentFleetMutation,
    PermanentFleetApplyResponse
  >({
    isCurrent: (input) => (
      sameRouteInput(input.hierarchy, draft)
      && input.referenceGeneration === (state?.generation ?? null)
      && input.referenceRevision === (state?.revision ?? null)
    ),
    replay: (input, approvalId) => (
      client.applyPermanentFleet(input.hierarchy, approvalId)
    ),
    onApplied: async () => {
      setEditing(false);
      await refresh(false);
      setMessage(
        "Desired hierarchy saved. No running worker was mutated; restart the fleet worker to apply it.",
      );
    },
    onRefused: (result) => {
      setMessage(governedResultReason(
        result,
        "The approved hierarchy change was refused.",
      ));
    },
    onUncertain: async () => {
      await refresh(false);
      setMessage(
        "Canonical fleet state was refreshed; no hierarchy change is inferred.",
      );
    },
  });

  async function refresh(invalidate = true) {
    if (invalidate) finalizer.invalidate();
    try {
      const result = await client.permanentFleet();
      setState(result);
      setDraft(result.hierarchy ?? blankHierarchy());
    } catch {
      setMessage("Permanent fleet desired/observed state is unavailable.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void refresh(false);
    void client.modelEndpoints()
      .then((result) => setEndpoints(result.endpoints))
      .catch(() => setEndpoints([]));
  }, []);

  async function apply() {
    setBusy(true);
    setMessage("");
    const input: PermanentFleetMutation = {
      hierarchy: draft,
      referenceGeneration: state?.generation ?? null,
      referenceRevision: state?.revision ?? null,
    };
    try {
      const result = await client.applyPermanentFleet(input.hierarchy);
      if (finalizer.begin(input, result, "Permanent fleet hierarchy change")) {
        setMessage("The hierarchy change is waiting for approval in the originating chat.");
      } else if (result.status === "ok") {
        setMessage(
          "Desired hierarchy saved. No running worker was mutated; restart the fleet worker to apply it.",
        );
        setEditing(false);
        await refresh(false);
      } else {
        setMessage(governedResultReason(result, "The hierarchy was not changed."));
      }
    } catch {
      setMessage("The hierarchy was not changed.");
    } finally {
      setBusy(false);
    }
  }

  const hierarchy = state?.hierarchy;
  const forest = useMemo(
    () => buildFleetForest(hierarchy, profiles),
    [hierarchy, profiles],
  );
  const layout = useMemo(() => layoutFleet(forest), [forest]);
  const positions = useMemo(
    () => new Map(layout.nodes.map((position) => [position.node.id, position])),
    [layout],
  );
  const selected = selectedId ? positions.get(selectedId)?.node ?? null : null;
  const hasOverlay = Boolean(selected || childParent || editing);
  const governanceMessages = (
    <div className="fleet-governance-messages" id="fleet-governance-messages">
      {message && <p className="notice" role="status">{message}</p>}
      <ExactApprovalFinalizer controller={finalizer} />
    </div>
  );
  const waitingCount = askingActors === null
    ? null
    : profiles.filter((profile) => profile.is_active && askingActors.has(profile.name)).length;
  const authoredHeadCount = hierarchy ? hierarchy.departments.length + 1 : 0;

  useLayoutEffect(() => {
    if (loading || layout.nodes.length === 0) return;
    const canvas = canvasRef.current;
    if (!canvas) return;
    // The tree is centred inside its deterministic plane. Centre that plane
    // inside the scroll viewport too; otherwise a wide real fleet opens at
    // scrollLeft=0 and clips only its right branch despite correct node maths.
    canvas.scrollLeft = Math.max(0, (canvas.scrollWidth - canvas.clientWidth) / 2);
  }, [loading, layout.height, layout.nodes.length, layout.width]);

  function openInspector(nodeId: string, opener: HTMLElement) {
    inspectorOpenerRef.current = opener;
    setSelectedId(nodeId);
  }

  function openChildHandoff(node: FleetNode, opener: HTMLElement) {
    childOpenerRef.current = opener;
    setChildParent(node);
  }

  function openTopologyEditor(opener: HTMLElement) {
    editorOpenerRef.current = opener;
    setEditing(true);
  }

  return (
    <section className="permanent-fleet" aria-label="Permanent fleet topology">
      <div
        aria-hidden={hasOverlay ? "true" : undefined}
        className="fleet-surface"
        onClickCapture={hasOverlay ? (event) => {
          event.preventDefault();
          event.stopPropagation();
        } : undefined}
        {...(hasOverlay ? { inert: "" } : {})}
      >
      <div className="fleet-summary">
        <div className="fleet-spend-summary">
          <strong>Spend unavailable</strong>
          <span>No windowed fleet usage is returned</span>
        </div>
        <span
          aria-label="Fleet spend meter unavailable"
          className="fleet-spend-meter"
          role="img"
        >
          <span />
        </span>
        <div className="fleet-summary-facts">
          <span><i data-tone="quiet" />{profiles.length || authoredHeadCount} agents</span>
          <span><i data-tone="quiet" />working unknown</span>
          <span><i data-tone={waitingCount && waitingCount > 0 ? "asking" : "quiet"} />
            {waitingCount === null ? "waiting unknown" : `${waitingCount} waiting on you`}
          </span>
        </div>
        {!hierarchy && <div className="fleet-summary-actions">
          <span className="fleet-apply-state">{topologyStateLabel(state)}</span>
          <button className="secondary-button" type="button" onClick={() => void refresh()}>
            Refresh
          </button>
          <button className="secondary-button" type="button" onClick={(event) => { finalizer.invalidate(); openTopologyEditor(event.currentTarget); }}>
            {hierarchy ? "Edit topology" : "Configure topology"}
          </button>
        </div>}
      </div>

      <div className="fleet-authority-key" aria-label="Authority legend">
        <span>The ring is what it may do</span>
        <span className="fleet-visually-hidden">Authority is not exposed by this fleet response</span>
        {AUTHORITY_CHANNELS.map(([id, label], index) => (
          <span className="fleet-authority-key-item" key={id}>
            <AuthorityIcon index={index} size={16} />
            {label}
          </span>
        ))}
      </div>

      {state?.apply_state === "startup_applied_liveness_unknown" && (
        <>
          <span className="fleet-visually-hidden">{topologyStateLabel(state)}</span>
          <p className="fleet-visually-hidden">
            Startup construction is recorded; current worker liveness is unknown,
            and endpoint/model liveness is also unproven.
          </p>
        </>
      )}

      <div
        className="fleet-canvas"
        data-loading={loading ? "true" : undefined}
        ref={canvasRef}
      >
        {loading && <div className="fleet-empty">Loading the authored fleet and visible profiles…</div>}
        {!loading && layout.nodes.length === 0 && (
          <div className="fleet-empty">
            <h2>No agent profiles visible</h2>
            <span>No authored fleet entries are visible. Configure the permanent hierarchy or create a profile.</span>
          </div>
        )}
        {!loading && layout.nodes.length > 0 && (
          <div
            className="fleet-plane"
            style={{ width: layout.width, height: layout.height }}
          >
            <svg
              aria-hidden="true"
              className="fleet-connectors"
              height={layout.height}
              viewBox={`0 0 ${layout.width} ${layout.height}`}
              width={layout.width}
            >
              {layout.nodes.flatMap((parent) => parent.node.children.map((child) => {
                const childPosition = positions.get(child.id);
                if (!childPosition) return [];
                const startY = parent.y + 29;
                const endY = childPosition.y - 29;
                const middle = (startY + endY) / 2;
                return [(
                  <path
                    d={`M${parent.x} ${startY} C${parent.x} ${middle} ${childPosition.x} ${middle} ${childPosition.x} ${endY}`}
                    key={`${parent.node.id}:${child.id}`}
                  />
                )];
              }))}
            </svg>
            {layout.nodes.map(({ node, x, y }) => (
              <FleetNodeCard
                askingActors={askingActors}
                isSelected={selectedId === node.id}
                key={node.id}
                node={node}
                onCreateChild={onCreateProfile && node.head && node.head.max_depth > 1
                  ? (opener) => openChildHandoff(node, opener)
                  : undefined}
                onSelect={(opener) => openInspector(node.id, opener)}
                state={state}
                style={{ left: x, top: y }}
              />
            ))}
          </div>
        )}
        {profiles.some((profile) => !hierarchy
          || ![hierarchy.chief, ...hierarchy.departments].some((head) => (
            profile.name.trim().toLowerCase() === head.name.trim().toLowerCase()
            || profile.name.trim().toLowerCase() === head.routing_id.trim().toLowerCase()
          ))) && (
          <span className="fleet-standalone-note">
            Standalone profiles are shown without a connector because this response exposes no permanent parent edge for them.
          </span>
        )}
      </div>

      {!editing && governanceMessages}
      </div>

      {selected && (
        <FleetInspector
          active={!childParent && !editing}
          askingActors={askingActors}
          lifecycleBusy={lifecycleBusy}
          node={selected}
          onClose={() => setSelectedId(null)}
          onCreateChild={onCreateProfile && selected.head && selected.head.max_depth > 1
            ? (opener) => openChildHandoff(selected, opener)
            : undefined}
          onEditProfile={onEditProfile}
          onEditTopology={selected.head ? (opener) => openTopologyEditor(opener) : undefined}
          onRefresh={() => void refresh()}
          onLifecycle={onLifecycle}
          opener={inspectorOpenerRef.current}
          parent={selected.parentId ? positions.get(selected.parentId)?.node ?? null : null}
          state={state}
        />
      )}

      {childParent && onCreateProfile && (
        <FleetModalShell
          ariaLabel={`Create a profile from ${childParent.name}`}
          cardClassName="fleet-handoff-card"
          onClose={() => setChildParent(null)}
          opener={childOpenerRef.current}
        >
            <div className="fleet-dialog-heading">
              <h2>New agent under {childParent.name}</h2>
              <button aria-label="Close child profile handoff" className="icon-button" data-fleet-modal-close="true" onClick={() => setChildParent(null)} type="button">×</button>
            </div>
            <p>
              It can only ever hold authority the parent can delegate. The profile API does not store a parent edge,
              so that relationship must still be authored separately in the permanent hierarchy.
            </p>
            <div className="fleet-new-identity">
              <FleetMark node={childParent} />
              <input aria-label="Agent name" disabled placeholder="Give it a name in the profile author" />
            </div>
            <div className="fleet-new-section">
              <span>What kind</span>
              <div className="fleet-new-roles" aria-label="Agent kind is selected in the profile editor">
                {["researcher", "writer", "operator", "analyst", "engineer", "coordinator"].map((role) => (
                  <button disabled key={role} type="button">{role}</button>
                ))}
              </div>
            </div>
            <div className="fleet-new-section">
              <span>What it may do</span>
              <div className="fleet-new-authority">
                {AUTHORITY_CHANNELS.map(([id, label], index) => (
                  <div key={id}>
                    <AuthorityIcon index={index} size={18} />
                    <span><strong>{label}</strong><small>Set in the profile and hierarchy editors</small></span>
                    <em>not available here</em>
                  </div>
                ))}
              </div>
            </div>
            <div className="inline-actions">
              <button className="primary-button" data-fleet-modal-initial="true" onClick={() => { onCreateProfile(childParent.name); setChildParent(null); }} type="button">
                Open profile author
              </button>
              <button className="secondary-button" onClick={() => setChildParent(null)} type="button">Cancel</button>
            </div>
        </FleetModalShell>
      )}

      {editing && (
        <FleetModalShell
          ariaLabel="Permanent fleet topology editor"
          cardClassName="fleet-editor-card"
          onClose={() => { finalizer.invalidate(); setEditing(false); }}
          opener={editorOpenerRef.current}
          ownedContent={governanceMessages}
          ownedId="fleet-governance-messages"
          scrimClassName="fleet-editor-scrim"
        >
            <div className="fleet-dialog-heading">
              <div>
                <p className="eyebrow">Permanent fleet · desired / observed</p>
                <h2>Chief of Staff and department heads</h2>
              </div>
              <button className="secondary-button" data-fleet-modal-close="true" type="button" onClick={() => { finalizer.invalidate(); setEditing(false); }}>Close editor</button>
            </div>
            <p>
              This is the authored org chart. A persistent capability profile is not a live head.
              A saved change is desired state, is not hot-applied, and requires a fleet-worker restart.
            </p>
            {state?.generation && (
              <p className="muted small">
                Desired generation <code>{state.generation}</code>. Hot application: no. Persistent profiles:{" "}
                {state.profiles_reconciled ? "projected" : "awaiting manifest apply or redeploy"}.
              </p>
            )}
            <form onSubmit={(event) => { event.preventDefault(); void apply(); }}>
              <HeadEditor
                head={draft.chief}
                role="Chief of Staff"
                endpoints={endpoints}
                onChange={(chief) => { finalizer.invalidate(); setDraft({ ...draft, chief }); }}
              />
              {draft.departments.map((head, index) => (
                <div className="detail-section" key={index}>
                  <HeadEditor
                    head={head}
                    role={`Department head ${index + 1}`}
                    endpoints={endpoints}
                    onChange={(department) => {
                      finalizer.invalidate();
                      setDraft({
                        ...draft,
                        departments: draft.departments.map((item, itemIndex) => (
                          itemIndex === index ? department : item
                        )),
                      });
                    }}
                  />
                  {draft.departments.length > 1 && (
                    <button className="danger-button" type="button" onClick={() => {
                      finalizer.invalidate();
                      setDraft({
                        ...draft,
                        departments: draft.departments.filter((_, itemIndex) => itemIndex !== index),
                      });
                    }}>Remove department</button>
                  )}
                </div>
              ))}
              <div className="inline-actions fleet-editor-actions">
                <button className="secondary-button" type="button" onClick={() => void refresh()}>
                  Refresh
                </button>
                <button className="secondary-button" type="button" onClick={() => {
                  finalizer.invalidate();
                  setDraft({
                    ...draft,
                    departments: [
                      ...draft.departments,
                      blankHead(false, draft.departments.length + 1),
                    ],
                  });
                }}>Add department</button>
                <button className="primary-button" data-fleet-modal-initial="true" disabled={busy || finalizer.busy}>
                  {busy ? "Requesting…" : "Request hierarchy change"}
                </button>
              </div>
            </form>
        </FleetModalShell>
      )}
    </section>
  );
}

function AuthorityIcon({ index, size }: { index: number; size: number }) {
  return (
    <svg aria-hidden="true" className="fleet-authority-icon" height={size} viewBox={`0 0 ${size} ${size}`} width={size}>
      {AUTHORITY_CHANNELS.map((channel, channelIndex) => (
        <path
          className={channelIndex === index ? "keyed" : undefined}
          d={authorityArcPath(channelIndex, size)}
          key={channel[0]}
        />
      ))}
    </svg>
  );
}

function FleetMark({ node }: { node: FleetNode }) {
  const genotype = node.profile?.familiar_genotype;
  const hasIdentity = genotype?.source === "agent_capability.name.v1";
  return (
    <span className="fleet-agent-mark">
      <svg aria-hidden="true" className="fleet-agent-collar" height="40" viewBox="0 0 40 40" width="40">
        {AUTHORITY_CHANNELS.map((channel, index) => (
          <path d={authorityArcPath(index, 40)} key={channel[0]} />
        ))}
      </svg>
      <span
        aria-label={hasIdentity
          ? `${node.name} profile Familiar`
          : `${node.name} profile identity unavailable`}
        className="fleet-familiar"
        data-genotype-source={hasIdentity ? genotype.source : "unavailable"}
        role="img"
      >
        <span aria-hidden="true" className="fleet-familiar-renderer">
          <FamiliarBadge
            decorative
            genotype={genotype}
            label={node.name}
            size={32}
            state="ready"
          />
        </span>
      </span>
    </span>
  );
}

function FleetNodeCard({
  askingActors,
  isSelected,
  node,
  onCreateChild,
  onSelect,
  state,
  style,
}: {
  askingActors: ReadonlySet<string> | null;
  isSelected: boolean;
  node: FleetNode;
  onCreateChild?: (opener: HTMLElement) => void;
  onSelect(opener: HTMLElement): void;
  state: PermanentFleetResponse | null;
  style: CSSProperties;
}) {
  const label = node.head
    ? headStateLabel(state)
    : node.profile
      ? profileStateLabel(node.profile, askingActors)
      : "unknown";
  return (
    <div className="fleet-node-wrap" style={style}>
      <button
        aria-label={`Inspect ${node.name}`}
        aria-pressed={isSelected}
        className="fleet-node-card"
        data-selected={isSelected ? "true" : undefined}
        onClick={(event) => onSelect(event.currentTarget)}
        type="button"
      >
        <FleetMark node={node} />
        <span className="fleet-node-copy">
          <span className="fleet-node-name">{node.name}</span>
          <span className="fleet-node-meta">
            <span>{nodeRole(node)}</span>
            <span className="fleet-visually-hidden" data-tone={profileTone(node.profile, askingActors, state)}>{label}</span>
          </span>
        </span>
        <span aria-label="Windowed spend is not exposed" className="fleet-node-usage" title="Windowed spend is not exposed">—</span>
        <span className="fleet-node-meter" />
        {node.head && (
          <span className="fleet-visually-hidden">
          Purpose, brief, runtime, model, skills, depth and cost policy are consumed
          when a worker constructs this generation. Runtime admission happens only
          when the head reasons; this card does not claim that a model is live.
          </span>
        )}
      </button>
      {onCreateChild && (
        <button
          aria-label={`Start child profile handoff from ${node.name}`}
          className="fleet-node-add"
          onClick={(event) => onCreateChild(event.currentTarget)}
          title="Create a bounded profile; parent edges are authored separately"
          type="button"
        >+</button>
      )}
    </div>
  );
}

function FleetInspector({
  active,
  askingActors,
  lifecycleBusy,
  node,
  onClose,
  onCreateChild,
  onEditProfile,
  onEditTopology,
  onLifecycle,
  opener,
  onRefresh,
  parent,
  state,
}: {
  active: boolean;
  askingActors: ReadonlySet<string> | null;
  lifecycleBusy: string;
  node: FleetNode;
  onClose(): void;
  onCreateChild?: (opener: HTMLElement) => void;
  onEditProfile?: (profile: AgentCapabilityAuthorInfo) => void;
  onEditTopology?: (opener: HTMLElement) => void;
  onLifecycle?: (profile: AgentCapabilityAuthorInfo) => void;
  opener: HTMLElement | null;
  onRefresh(): void;
  parent: FleetNode | null;
  state: PermanentFleetResponse | null;
}) {
  const profile = node.profile;
  const head = node.head;
  const skills = profile?.supported_skills ?? head?.supported_skills ?? [];
  const status = head
    ? headStateLabel(state)
    : profile
      ? profileStateLabel(profile, askingActors)
      : "unknown";
  const maxDepth = profile?.max_depth ?? head?.max_depth;
  const runtime = profile?.runtime ?? head?.runtime ?? "unknown";
  const model = profile?.model_endpoint ?? head?.model_endpoint ?? "automatic / process-pinned";
  const tier = profile?.cost_tier ?? head?.cost_tier ?? "unknown";
  const budget = head?.budget;
  const budgetCopy = !head
    ? "No permanent budget policy is exposed for this standalone profile."
    : !budget
      ? "No budget policy is authored for this permanent head."
      : budget.cost_limit_micros === null
        ? `A ${budget.window} policy is authored; no cost cap is set.`
        : `${budget.cost_limit_micros.toLocaleString()} cost micros per ${budget.window} is authored; usage is unavailable.`;

  return (
    <FleetModalShell
      active={active}
      ariaLabel={`${node.name} fleet inspector`}
      cardClassName="fleet-inspector"
      onClose={onClose}
      opener={opener}
    >
        <div className="fleet-inspector-head">
          <FleetMark node={node} />
          <div>
            <div className="fleet-inspector-title">
              <h2>{node.name}</h2>
              <span className="console-tech">{runtime}</span>
              <span className="fleet-state-pill" data-tone={profileTone(profile, askingActors, state)}>{status}</span>
            </div>
            <p>{head?.purpose ?? "A capability profile. Profile state does not prove that a worker is live."}</p>
            <p className="fleet-chain">
              {parent ? `Authored parent: ${parent.name}` : node.kind === "profile"
                ? "No permanent hierarchy edge is exposed"
                : "Top of the authored permanent hierarchy"}
              {node.children.length > 0 ? ` · ${node.children.length} authored ${node.children.length === 1 ? "child" : "children"}` : ""}
            </p>
          </div>
          <button aria-label="Close fleet inspector" className="icon-button" data-fleet-modal-close="true" onClick={onClose} type="button">×</button>
        </div>

        <div className="fleet-inspector-section">
          <div className="fleet-section-label"><span>Authority</span><span>not exposed by this response</span></div>
          <div className="fleet-authority-grid">
            {AUTHORITY_CHANNELS.map(([id, label]) => (
              <div className="fleet-authority-cell" key={id}>
                <span>{label}</span>
                <small>unknown</small>
              </div>
            ))}
          </div>
          <p className="fleet-section-note">
            Skill patterns and delegation depth do not prove read, write, send, spend or delegate authority.
          </p>
        </div>

        <div className="fleet-spend-panel">
          <div className="fleet-section-label"><span>Spend</span><span>usage unavailable</span></div>
          <strong>Windowed spend unavailable</strong>
          <span className="fleet-inspector-meter"><i /></span>
          <small>{budgetCopy}</small>
        </div>

        <div className="fleet-inspector-section">
          <div className="fleet-section-label"><span>What it can reach</span><span>{skills.length} skill {skills.length === 1 ? "pattern" : "patterns"}</span></div>
          {skills.length > 0
            ? <div className="fleet-skill-list">{skills.map((skill) => <span key={skill}>{skill}</span>)}</div>
            : <p className="fleet-section-note">No named skill patterns are exposed.</p>}
          <p className="fleet-section-note">Actions, knowledge and plugins are not included in the fleet/profile responses.</p>
          <dl className="fleet-facts">
            <div><dt>Model</dt><dd>{model}</dd></div>
            <div><dt>Maximum depth</dt><dd>{maxDepth ?? "unknown"}</dd></div>
            <div><dt>Cost tier</dt><dd>{tier}</dd></div>
            <div><dt>Relationship</dt><dd>{parent ? "authored" : node.kind === "profile" ? "unavailable" : "root"}</dd></div>
            <div><dt>Mood</dt><dd>unavailable</dd></div>
            <div><dt>Kit</dt><dd>unavailable</dd></div>
          </dl>
        </div>

        <div className="fleet-inspector-actions">
          {profile && onEditProfile && <button className="primary-button" data-fleet-modal-initial="true" onClick={() => onEditProfile(profile)} type="button">Edit profile</button>}
          {profile && onLifecycle && (
            <button className="secondary-button" disabled={lifecycleBusy === profile.name} onClick={() => onLifecycle(profile)} type="button">
              {lifecycleBusy === profile.name ? "Requesting…" : profile.is_active ? "Retire profile" : "Restore profile"}
            </button>
          )}
          <button className="secondary-button" onClick={onRefresh} type="button">Refresh</button>
          {onEditTopology && <button className="secondary-button" onClick={(event) => onEditTopology(event.currentTarget)} type="button">Edit topology</button>}
          {onCreateChild && <button className="secondary-button" onClick={(event) => onCreateChild(event.currentTarget)} type="button">Start child profile handoff</button>}
          <span />
          <button className="secondary-button" onClick={onClose} type="button">Close</button>
        </div>
    </FleetModalShell>
  );
}

function HeadEditor({
  head,
  role,
  endpoints,
  onChange,
}: {
  head: PermanentFleetHead;
  role: string;
  endpoints: ModelEndpointInfo[];
  onChange(head: PermanentFleetHead): void;
}) {
  return (
    <fieldset className="admin-form compact">
      <legend>{role}</legend>
      <div className="author-grid">
        <label><span>Profile name</span><input className="field-control" required pattern="[a-z0-9][a-z0-9-]{1,62}" value={head.name} onChange={(event) => onChange({ ...head, name: event.target.value.toLowerCase() })} /></label>
        <label><span>Routing identity</span><input className="field-control" required disabled={role === "Chief of Staff"} value={head.routing_id} onChange={(event) => onChange({ ...head, routing_id: event.target.value.toLowerCase() })} /></label>
        <label><span>Runtime profile</span><select className="field-control" value={head.runtime} onChange={(event) => onChange({ ...head, runtime: event.target.value as PermanentFleetHead["runtime"] })}><option value="codex">Codex</option><option value="script">Deterministic script</option></select></label>
        <label><span>Model endpoint profile</span><select className="field-control" value={head.model_endpoint ?? ""} onChange={(event) => onChange({ ...head, model_endpoint: event.target.value || null })}><option value="">Automatic profile</option>{endpoints.filter((endpoint) => endpoint.is_active || endpoint.id === head.model_endpoint).map((endpoint) => <option value={endpoint.id} disabled={!endpoint.is_active} key={endpoint.id}>{endpoint.id} · {endpoint.model}{endpoint.is_active ? "" : " (retired)"}</option>)}</select></label>
        <label><span>Maximum delegation depth</span><input className="field-control" type="number" min="1" max="5" value={head.max_depth} onChange={(event) => onChange({ ...head, max_depth: Number(event.target.value) })} /></label>
        <label><span>Cost tier profile</span><select className="field-control" value={head.cost_tier} onChange={(event) => onChange({ ...head, cost_tier: event.target.value as PermanentFleetHead["cost_tier"] })}><option value="cheap">Cheap</option><option value="standard">Standard</option><option value="expensive">Expensive</option></select></label>
      </div>
      <label><span>Purpose</span><input className="field-control" required maxLength={500} value={head.purpose} onChange={(event) => onChange({ ...head, purpose: event.target.value })} /></label>
      <label><span>Supported skill patterns</span><textarea className="field-control code-field" rows={2} value={head.supported_skills.join(", ")} onChange={(event) => onChange({ ...head, supported_skills: event.target.value.split(/[,\n]/).map((item) => item.trim()).filter(Boolean) })} /><small>Only concrete department skills are consumed by the permanent head; wildcard patterns remain profile metadata.</small></label>
      <label className="checkbox-row">
        <input
          type="checkbox"
          checked={head.budget !== null}
          onChange={(event) => onChange({
            ...head,
            budget: event.target.checked
              ? {
                  token_limit: null,
                  cost_limit_micros: null,
                  hard_stop: true,
                  window: "monthly",
                }
              : null,
          })}
        />
        <span>Author budget policy for this scope</span>
      </label>
      {head.budget && (
        <div className="author-grid">
          <label><span>Token limit</span><input className="field-control" type="number" min="0" value={head.budget.token_limit ?? ""} onChange={(event) => onChange({ ...head, budget: { ...head.budget!, token_limit: event.target.value === "" ? null : Number(event.target.value) } })} /></label>
          <label><span>Cost limit (micros)</span><input className="field-control" type="number" min="0" value={head.budget.cost_limit_micros ?? ""} onChange={(event) => onChange({ ...head, budget: { ...head.budget!, cost_limit_micros: event.target.value === "" ? null : Number(event.target.value) } })} /></label>
          <label><span>Automatic budget window</span><select className="field-control" value={head.budget.window} onChange={(event) => onChange({ ...head, budget: { ...head.budget!, window: event.target.value as NonNullable<PermanentFleetHead["budget"]>["window"] } })}><option value="run">Per run</option><option value="daily">Daily · UTC</option><option value="monthly">Monthly · UTC</option></select></label>
          <label className="checkbox-row"><input type="checkbox" checked={head.budget.hard_stop} onChange={(event) => onChange({ ...head, budget: { ...head.budget!, hard_stop: event.target.checked } })} /><span>Hard stop</span></label>
        </div>
      )}
      <label><span>Agent brief</span><textarea className="field-control" rows={3} maxLength={8000} value={head.brief} onChange={(event) => onChange({ ...head, brief: event.target.value })} /><small>Stored and versioned. After restart it becomes prompt policy whenever this permanent profile passes runtime admission; deterministic fallback remains available.</small></label>
    </fieldset>
  );
}
