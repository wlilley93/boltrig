import { useState } from "react";

import { api } from "../../api/client";
import type { StatusAck } from "../../api/types";
import { errText, parseJson } from "../shared";
import { Hint } from "../ux";
import { AckLine } from "./AckLine";
import { BindingTargetFields } from "./routerStudio/BindingTargetFields";
import { useBindingForm } from "./routerStudio/useBindingForm";
import { useVerbForm } from "./routerStudio/useVerbForm";
import { VerbSchemaFields } from "./routerStudio/VerbSchemaFields";

function NounForm() {
  const [id, setId] = useState("");
  const [description, setDescription] = useState("");
  const [schema, setSchema] = useState("{}");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ack, setAck] = useState<StatusAck | null>(null);

  async function submit() {
    if (!id.trim()) {
      setError("Noun id is required.");
      return;
    }
    let parsed: Record<string, unknown>;
    try {
      parsed = parseJson<Record<string, unknown>>(schema, {});
    } catch (err) {
      setError(`schema: ${errText(err)}`);
      return;
    }
    setBusy(true);
    setError(null);
    setAck(null);
    try {
      setAck(
        await api.upsertNoun({
          id: id.trim(),
          description,
          schema: parsed,
        }),
      );
    } catch (err) {
      setError(errText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="form">
      <div className="form__title">Add noun</div>
      <div className="form__grid">
        <label className="field">
          <span>id</span>
          <input value={id} onChange={(e) => setId(e.target.value)} />
        </label>
        <label className="field">
          <span>description</span>
          <input
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </label>
      </div>
      <label className="field">
        <span>schema (JSON)</span>
        <textarea
          className="code"
          value={schema}
          onChange={(e) => setSchema(e.target.value)}
        />
      </label>
      <div className="form__actions">
        <button className="btn btn--primary" disabled={busy} onClick={submit}>
          {busy ? "..." : "Save noun"}
        </button>
        <AckLine ack={ack} />
        {error && <span className="error">{error}</span>}
      </div>
    </div>
  );
}

function VerbForm() {
  const s = useVerbForm();

  return (
    <div className="form">
      <div className="form__title">Add verb</div>
      <div className="form__grid">
        <label className="field">
          <span>id</span>
          <input value={s.id} onChange={(e) => s.setId(e.target.value)} />
        </label>
        <label className="field">
          <span>noun_id</span>
          <input value={s.nounId} onChange={(e) => s.setNounId(e.target.value)} />
        </label>
        <label className="field">
          <span>consequence</span>
          <select
            value={s.consequence}
            onChange={(e) =>
              s.setConsequence(e.target.value === "high" ? "high" : "low")
            }
          >
            <option value="low">low</option>
            <option value="high">high</option>
          </select>
        </label>
      </div>
      <VerbSchemaFields s={s} />
      <div className="form__actions">
        <button className="btn btn--primary" disabled={s.busy} onClick={s.submit}>
          {s.busy ? "..." : "Save verb"}
        </button>
        <AckLine ack={s.ack} />
        {s.error && <span className="error">{s.error}</span>}
      </div>
    </div>
  );
}

function BindingForm() {
  const s = useBindingForm();

  return (
    <div className="form">
      <div className="form__title">Set binding</div>
      <Hint>Wire a verb to what actually runs it - an adapter, or an agent.</Hint>
      <BindingTargetFields s={s} />
      <div className="form__actions">
        <button className="btn btn--primary" disabled={s.busy} onClick={s.submit}>
          {s.busy ? "Saving..." : "Set binding"}
        </button>
        <AckLine ack={s.ack} />
        {s.error && <span className="error">{s.error}</span>}
      </div>
    </div>
  );
}

export function RouterStudio() {
  return (
    <div className="cols">
      <NounForm />
      <VerbForm />
      <BindingForm />
    </div>
  );
}
