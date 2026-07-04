import type { VerbInfo } from "@/api/types";
import { Select } from "@/panels/ux";
import { SchemaFormV2 } from "@/panels/uxForm";
import type { StepNode } from "./types";

interface StepInspectorProps {
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

export function StepInspector({
  selectedNode,
  verbs,
  verbsById,
  inspector,
  onSwap,
  onRename,
  onDelete,
}: StepInspectorProps) {
  if (!selectedNode) {
    return (
      <div className="form">
        <div className="form__title">Step inspector</div>
        <p className="muted">Select a step node to edit its id and params.</p>
      </div>
    );
  }

  const sv = verbsById.get(selectedNode.data.action);
  const props = (
    sv?.input_schema as { properties?: object } | undefined
  )?.properties;
  const hasSchema = props && Object.keys(props).length > 0;

  return (
    <div className="form">
      <div className="form__title">Step inspector</div>
      <div className="form__grid">
        <label className="field">
          <span>id</span>
          <input
            value={inspector.editId}
            onChange={(e) => inspector.setEditId(e.target.value)}
          />
        </label>
        <label className="field">
          <span>action (verb)</span>
          <Select
            value={selectedNode.data.action}
            ariaLabel="Action verb"
            onChange={onSwap}
            options={verbs.map((v) => ({ value: v.id, label: v.id }))}
          />
        </label>
        <label className="field">
          <span>kind</span>
          <input value={selectedNode.data.kind} readOnly />
        </label>
      </div>
      <label className="field">
        <span>description</span>
        <input
          value={inspector.editDesc}
          onChange={(e) => inspector.setEditDesc(e.target.value)}
        />
      </label>
      {hasSchema ? (
        <>
          <span className="field">
            <span>parameters</span>
          </span>
          <SchemaFormV2
            schema={sv!.input_schema}
            value={safeObj(inspector.editParams)}
            onChange={(o) =>
              inspector.setEditParams(JSON.stringify(o, null, 2))
            }
          />
          <details>
            <summary className="ux-hint" style={{ cursor: "pointer" }}>
              Edit as JSON
            </summary>
            <textarea
              className="code"
              value={inspector.editParams}
              onChange={(e) => inspector.setEditParams(e.target.value)}
            />
          </details>
        </>
      ) : (
        <label className="field">
          <span>params (JSON)</span>
          <textarea
            className="code"
            value={inspector.editParams}
            onChange={(e) => inspector.setEditParams(e.target.value)}
          />
        </label>
      )}
      <div className="form__actions">
        <button
          className="btn btn--primary"
          onClick={inspector.applyParams}
        >
          Apply
        </button>
        <button className="btn" onClick={onRename}>
          Rename id
        </button>
        <button className="btn btn--ghost" onClick={onDelete}>
          Delete
        </button>
        {inspector.editError && (
          <span className="error">{inspector.editError}</span>
        )}
      </div>
    </div>
  );
}
