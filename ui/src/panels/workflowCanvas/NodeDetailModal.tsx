// Centred node detail modal (design brief sec 22.8). Opens when a step node is
// selected. Shows the node icon + label + kind, the action verb, editable
// parameters (mono), description, a run-status badge, and Edit/Delete actions.
// Backdrop click dismisses. Reuses the existing inspector hook for edits.

import type { VerbInfo } from "@/api/types";
import { Select } from "@/panels/ux";
import { SchemaFormV2 } from "@/panels/uxForm";
import { MeshCanvas } from "../chat/MeshCanvas";
import { findKind } from "./nodeTaxonomy";
import { NodeIcon } from "./nodeIcons";
import type { RunNodeStatus, StepNode } from "./types";

interface NodeDetailModalProps {
  selectedNode?: StepNode;
  verbs: VerbInfo[];
  verbsById: Map<string, VerbInfo>;
  inspector: {
    editId: string;
    setEditId: (v: string) => void;
    editParams: string;
    setEditParams: (v: string) => void;
    editDesc: string;
    setEditDesc: (v: string) => void;
    editError: string | null;
    applyParams: () => boolean;
  };
  onSwap: (verbId: string) => void;
  onRename: () => void;
  onDelete: () => void;
  onClose: () => void;
}

function safeObj(text: string): Record<string, unknown> {
  try {
    const v = JSON.parse(text || "{}");
    return v && typeof v === "object" && !Array.isArray(v)
      ? (v as Record<string, unknown>)
      : {};
  } catch {
    return {};
  }
}

const STATUS_LABEL: Record<RunNodeStatus, string> = {
  pending: "Pending",
  running: "Running",
  ok: "OK",
  failed: "Failed",
  error: "Error",
  skipped: "Skipped",
};

export function NodeDetailModal({
  selectedNode,
  verbs,
  verbsById,
  inspector,
  onSwap,
  onRename,
  onDelete,
  onClose,
}: NodeDetailModalProps) {
  if (!selectedNode) return null;
  const d = selectedNode.data;
  const meta = findKind(d.nodeKind);
  const verb = verbsById.get(d.action);
  const schemaProps = (
    verb?.input_schema as { properties?: object } | undefined
  )?.properties;
  const hasSchema = schemaProps && Object.keys(schemaProps).length > 0;

  return (
    <div className="wf3-modal-backdrop" onClick={onClose}>
      <MeshCanvas active />
      <div
        className="wf3-modal"
        role="dialog"
        aria-modal="true"
        aria-label="Node detail"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="wf3-modal__head">
          <span
            className="wf3-modal__icon"
            style={{ color: meta?.color ?? "#7E95B0", background: "rgba(255,255,255,0.05)" }}
          >
            <NodeIcon name={meta?.icon ?? "agent"} size={20} />
          </span>
          <div className="wf3-modal__titles">
            <div className="wf3-modal__name">{d.label}</div>
            <div className="wf3-modal__kind muted">
              {meta?.name ?? d.nodeKind ?? "Node"}
            </div>
          </div>
          {d.runStatus && (
            <span className={`wf3-modal__status wf3-modal__status--${d.runStatus}`}>
              {STATUS_LABEL[d.runStatus] ?? d.runStatus}
            </span>
          )}
        </header>

        <label className="wf3-modal__field">
          <span>id</span>
          <input value={inspector.editId} onChange={(e) => inspector.setEditId(e.target.value)} />
        </label>

        <label className="wf3-modal__field">
          <span>action (verb)</span>
          <Select
            value={d.action}
            ariaLabel="Action verb"
            onChange={onSwap}
            options={verbs.map((v) => ({ value: v.id, label: v.id }))}
          />
        </label>

        <label className="wf3-modal__field">
          <span>description</span>
          <input
            value={inspector.editDesc}
            onChange={(e) => inspector.setEditDesc(e.target.value)}
          />
        </label>

        <div className="wf3-modal__field">
          <span>parameters</span>
          {hasSchema ? (
            <SchemaFormV2
              schema={verb!.input_schema}
              value={safeObj(inspector.editParams)}
              onChange={(o) => inspector.setEditParams(JSON.stringify(o, null, 2))}
            />
          ) : (
            <textarea
              className="wf3-modal__code code"
              value={inspector.editParams}
              onChange={(e) => inspector.setEditParams(e.target.value)}
              rows={5}
            />
          )}
        </div>

        {inspector.editError && <p className="wf3-modal__error error">{inspector.editError}</p>}

        <footer className="wf3-modal__actions">
          <button type="button" className="btn btn--primary" onClick={inspector.applyParams}>
            Apply
          </button>
          <button type="button" className="btn" onClick={onRename}>
            Rename
          </button>
          <button type="button" className="btn btn--ghost" onClick={onDelete}>
            Delete
          </button>
        </footer>
      </div>
    </div>
  );
}
