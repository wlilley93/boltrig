import type { StatusAck, WorkflowSourceValue } from "@/api/types";

interface MetaFormProps {
  meta: {
    wfId: string;
    setWfId: (v: string) => void;
    version: string;
    setVersion: (v: string) => void;
    source: WorkflowSourceValue;
    tags: string;
    setTags: (v: string) => void;
    saveBusy: boolean;
    runBusy: boolean;
    ack: StatusAck | null;
    saveError: string | null;
    runError: string | null;
    viewRunId: string;
    setViewRunId: (v: string) => void;
  };
  api: {
    save: () => void | Promise<void>;
    run: () => void | Promise<void>;
    openRunCanvas: () => void;
  };
  clearCanvas: () => void;
}

export function MetaForm({ meta, api, clearCanvas }: MetaFormProps) {
  return (
    <div className="form">
      <div className="form__title">Workflow</div>
      <div className="form__grid">
        <label className="field">
          <span>id</span>
          <input
            value={meta.wfId}
            onChange={(e) => meta.setWfId(e.target.value)}
          />
        </label>
        <label className="field">
          <span>version</span>
          <input
            value={meta.version}
            onChange={(e) => meta.setVersion(e.target.value)}
          />
        </label>
        <div className="field">
          <span>source</span>
          <strong>{meta.source}</strong>
          <small>Assigned by Boltrig</small>
        </div>
      </div>
      <label className="field">
        <span>intent_tags (comma list)</span>
        <input
          value={meta.tags}
          onChange={(e) => meta.setTags(e.target.value)}
        />
      </label>
      <div className="form__actions">
        <button
          className="btn btn--primary"
          disabled={meta.saveBusy}
          onClick={api.save}
        >
          {meta.saveBusy ? "..." : "Save"}
        </button>
        <button className="btn" disabled={meta.runBusy} onClick={api.run}>
          {meta.runBusy ? "..." : "Run"}
        </button>
        <button className="btn btn--ghost" onClick={clearCanvas}>
          Clear
        </button>
      </div>
      {meta.ack &&
        (meta.ack.status === "ok" ? (
          <p className="ok">
            Saved{" "}
            {[meta.ack.id, meta.ack.version ? `v${meta.ack.version}` : null]
              .filter(Boolean)
              .join(" ") || "ok"}
            .
          </p>
        ) : (
          <p className="error">
            {meta.ack.status}: {meta.ack.reason ?? "request rejected"}
          </p>
        ))}
      {meta.saveError && <p className="error">{meta.saveError}</p>}
      {meta.runError && <p className="error">{meta.runError}</p>}
      <div className="kv">
        <input
          placeholder="existing run id"
          value={meta.viewRunId}
          onChange={(e) => meta.setViewRunId(e.target.value)}
        />
        <button className="btn" onClick={api.openRunCanvas}>
          View run
        </button>
      </div>
    </div>
  );
}
