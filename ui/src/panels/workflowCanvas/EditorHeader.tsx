// Editor header bar for the automations canvas (design brief sec 22.2).
// Full-width row above the canvas: back arrow + workflow name + version +
// undo/redo + step count + high-consequence warning + Save/Run. Replaces the
// old MetaForm inside WorkflowCanvas. Filled geometric SVG icons (no Lucide).

import type { StatusAck } from "@/api/types";
import { isStepNode } from "./graph";
import type { CanvasNode } from "./types";

export interface EditorHeaderMeta {
  wfId: string;
  setWfId: (v: string) => void;
  version: string;
  saveBusy: boolean;
  saveError: string | null;
  ack: StatusAck | null;
  runBusy: boolean;
  runError: string | null;
}

export interface EditorHeaderGraph {
  previewSteps: unknown[];
  nodes: CanvasNode[];
}

export interface EditorHeaderApi {
  save: () => void | Promise<void>;
  run: () => void | Promise<void>;
}

export interface EditorHeaderProps {
  meta: EditorHeaderMeta;
  graph: EditorHeaderGraph;
  api: EditorHeaderApi;
  onBack?: () => void;
  canUndo: boolean;
  canRedo: boolean;
  onUndo: () => void;
  onRedo: () => void;
  // Chat-first authoring: the canvas is read-only, so the header drops the
  // editing affordances (name input, undo/redo, Save). Run stays - triggering
  // is not editing. Mutation happens in the chat lane via governed verbs.
  readOnly?: boolean;
}

export function EditorHeader(props: EditorHeaderProps) {
  const { meta, graph, api } = props;
  const stepCount = graph.previewSteps.length;
  const highConsequence = graph.nodes.some(
    (n) => isStepNode(n) && n.data.consequence === "high",
  );
  const ackOk = meta.ack && meta.ack.status === "ok";

  return (
    <header className="wf3-header">
      <div className="wf3-header__left">
        {props.onBack && (
          <button
            type="button"
            className="wf3-header__iconbtn"
            title="Back to automations"
            aria-label="Back to automations"
            onClick={props.onBack}
          >
            <BackIcon />
          </button>
        )}
        {props.readOnly ? (
          <span className="wf3-header__name" title="workflow id">
            {meta.wfId || "Untitled workflow"}
          </span>
        ) : (
          <input
            className="wf3-header__name"
            value={meta.wfId}
            placeholder="Untitled workflow"
            onChange={(e) => meta.setWfId(e.target.value)}
            spellCheck={false}
          />
        )}
        <span className="wf3-header__version" title="workflow version">
          v{meta.version}
        </span>
      </div>

      <div className="wf3-header__right">
        {!props.readOnly && (
          <div className="wf3-header__group">
            <button
              type="button"
              className="wf3-header__iconbtn"
              title="Undo"
              aria-label="Undo"
              disabled={!props.canUndo}
              onClick={props.onUndo}
            >
              <UndoIcon />
            </button>
            <button
              type="button"
              className="wf3-header__iconbtn"
              title="Redo"
              aria-label="Redo"
              disabled={!props.canRedo}
              onClick={props.onRedo}
            >
              <RedoIcon />
            </button>
          </div>
        )}

        <span className="wf3-header__count">{stepCount} steps</span>

        {highConsequence && (
          <span
            className="wf3-header__conseq"
            title="This workflow contains high-consequence steps that may pause for human approval"
          >
            <ShieldIcon />
            <span className="wf3-header__conseq-text">High-consequence</span>
          </span>
        )}

        <div className="wf3-header__group">
          {!props.readOnly && (
            <button
              type="button"
              className="btn btn--primary wf3-header__action"
              disabled={meta.saveBusy}
              onClick={() => void api.save()}
            >
              {meta.saveBusy ? <Spinner /> : <SaveIcon />}
              <span>Save</span>
            </button>
          )}
          <button
            type="button"
            className="btn wf3-header__action"
            disabled={meta.runBusy}
            onClick={() => void api.run()}
          >
            {meta.runBusy ? <Spinner /> : <PlayIcon />}
            <span>Run</span>
          </button>
        </div>
      </div>

      {(ackOk || meta.saveError || meta.runError) && (
        <div className="wf3-header__notes">
          {ackOk && (
            <span className="wf3-header__ok">
              Saved{" "}
              {[meta.ack?.id, meta.ack?.version ? `v${meta.ack.version}` : null]
                .filter(Boolean)
                .join(" ") || "ok"}
            </span>
          )}
          {meta.saveError && (
            <span className="wf3-header__err">{meta.saveError}</span>
          )}
          {meta.runError && (
            <span className="wf3-header__err">{meta.runError}</span>
          )}
        </div>
      )}
    </header>
  );
}

type IconProps = { size?: number };

function BackIcon({ size = 18 }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">
      <path
        fill="currentColor"
        d="M16 4 8 12l8 8 2.2-2.2L12.4 12l5.8-5.8z"
      />
    </svg>
  );
}

function UndoIcon({ size = 16 }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">
      <path fill="currentColor" d="M20 11H9V6L2 12l7 6v-5h11z" />
    </svg>
  );
}

function RedoIcon({ size = 16 }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">
      <path fill="currentColor" d="M4 11h11V6l7 6-7 6v-5H4z" />
    </svg>
  );
}

function ShieldIcon({ size = 15 }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">
      <path
        fill="currentColor"
        d="M12 2 4 5v6c0 4.6 3.4 8.6 8 10 4.6-1.4 8-5.4 8-10V5z"
      />
    </svg>
  );
}

function SaveIcon({ size = 15 }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">
      <path
        fill="currentColor"
        d="M5 3h11l4 4v13a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1Zm2 2v5h8V5Zm5 9a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7Z"
      />
    </svg>
  );
}

function PlayIcon({ size = 15 }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">
      <path fill="currentColor" d="M6 4 20 12 6 20z" />
    </svg>
  );
}

function Spinner() {
  return <span className="wf3-header__spinner" aria-hidden="true" />;
}
