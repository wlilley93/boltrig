import { useState } from "react";

import { api } from "@/api/client";
import type { StatusAck } from "@/api/types";
import { AckLine } from "@/panels/studio/AckLine";
import { csvToList, errText, parseJson } from "@/panels/shared";

interface UpsertWorkflowValues {
  id: string;
  version: string;
  definition: string;
  tags: string;
}

interface UpsertWorkflowChangeHandlers {
  setId: (v: string) => void;
  setVersion: (v: string) => void;
  setDefinition: (v: string) => void;
  setTags: (v: string) => void;
}

interface UpsertWorkflowFieldsProps {
  values: UpsertWorkflowValues;
  onChange: UpsertWorkflowChangeHandlers;
  busy: boolean;
  onSave: () => void;
  status: { ack: StatusAck | null; error: string | null };
}

function UpsertWorkflowFields({
  values,
  onChange,
  busy,
  onSave,
  status,
}: UpsertWorkflowFieldsProps) {
  const { id, version, definition, tags } = values;
  const { setId, setVersion, setDefinition, setTags } = onChange;
  const { ack, error } = status;

  return (
    <div className="form">
      <div className="form__title">Upsert workflow</div>
      <div className="form__grid">
        <label className="field">
          <span>id</span>
          <input value={id} onChange={(e) => setId(e.target.value)} />
        </label>
        <label className="field">
          <span>version</span>
          <input value={version} onChange={(e) => setVersion(e.target.value)} />
        </label>
        <div className="field">
          <span>source</span>
          <strong>precreated</strong>
          <small>Assigned by Boltrig</small>
        </div>
      </div>
      <label className="field">
        <span>definition / steps (JSON)</span>
        <textarea
          className="code"
          value={definition}
          onChange={(e) => setDefinition(e.target.value)}
        />
      </label>
      <label className="field">
        <span>intent_tags (comma list)</span>
        <input value={tags} onChange={(e) => setTags(e.target.value)} />
      </label>
      <div className="form__actions">
        <button className="btn btn--primary" disabled={busy} onClick={onSave}>
          {busy ? "..." : "Save workflow"}
        </button>
        <AckLine ack={ack} />
        {error && <span className="error">{error}</span>}
      </div>
    </div>
  );
}

export function UpsertWorkflowForm({ onSaved }: { onSaved: () => void }) {
  const [id, setId] = useState("");
  const [version, setVersion] = useState("1.0.0");
  const [definition, setDefinition] = useState("{}");
  const [tags, setTags] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ack, setAck] = useState<StatusAck | null>(null);

  async function upsert() {
    if (!id.trim()) {
      setError("Workflow id is required.");
      return;
    }
    let def: Record<string, unknown>;
    try {
      def = parseJson<Record<string, unknown>>(definition, {});
    } catch (err) {
      setError(`definition: ${errText(err)}`);
      return;
    }
    setBusy(true);
    setError(null);
    setAck(null);
    try {
      const res = await api.upsertWorkflow({
        id: id.trim(),
        version: version.trim() || "1.0.0",
        definition: def,
        intent_tags: csvToList(tags),
      });
      setAck(res);
      if (res.status === "ok") onSaved();
    } catch (err) {
      setError(errText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <UpsertWorkflowFields
      values={{ id, version, definition, tags }}
      onChange={{
        setId,
        setVersion,
        setDefinition,
        setTags,
      }}
      busy={busy}
      onSave={upsert}
      status={{ ack, error }}
    />
  );
}
