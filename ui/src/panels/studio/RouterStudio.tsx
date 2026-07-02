import { useState } from "react";

import { api } from "../../api/client";
import type { StatusAck, TargetTypeValue } from "../../api/types";
import { useFetch } from "../../useFetch";
import { errText, parseJson } from "../shared";
import { Field, Hint, Select } from "../ux";
import { SegmentedV2 } from "../uxForm";
import { AckLine } from "./AckLine";

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
  const [id, setId] = useState("");
  const [nounId, setNounId] = useState("");
  const [inputSchema, setInputSchema] = useState("{}");
  const [outputSchema, setOutputSchema] = useState("{}");
  const [consequence, setConsequence] = useState<"low" | "high">("low");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ack, setAck] = useState<StatusAck | null>(null);

  async function submit() {
    if (!id.trim() || !nounId.trim()) {
      setError("Verb id and noun_id are required.");
      return;
    }
    let inSchema: Record<string, unknown>;
    let outSchema: Record<string, unknown>;
    try {
      inSchema = parseJson<Record<string, unknown>>(inputSchema, {});
      outSchema = parseJson<Record<string, unknown>>(outputSchema, {});
    } catch (err) {
      setError(`schema: ${errText(err)}`);
      return;
    }
    setBusy(true);
    setError(null);
    setAck(null);
    try {
      setAck(
        await api.upsertVerb({
          id: id.trim(),
          noun_id: nounId.trim(),
          input_schema: inSchema,
          output_schema: outSchema,
          consequence,
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
      <div className="form__title">Add verb</div>
      <div className="form__grid">
        <label className="field">
          <span>id</span>
          <input value={id} onChange={(e) => setId(e.target.value)} />
        </label>
        <label className="field">
          <span>noun_id</span>
          <input value={nounId} onChange={(e) => setNounId(e.target.value)} />
        </label>
        <label className="field">
          <span>consequence</span>
          <select
            value={consequence}
            onChange={(e) =>
              setConsequence(e.target.value === "high" ? "high" : "low")
            }
          >
            <option value="low">low</option>
            <option value="high">high</option>
          </select>
        </label>
      </div>
      <label className="field">
        <span>input_schema (JSON)</span>
        <textarea
          className="code"
          value={inputSchema}
          onChange={(e) => setInputSchema(e.target.value)}
        />
      </label>
      <label className="field">
        <span>output_schema (JSON)</span>
        <textarea
          className="code"
          value={outputSchema}
          onChange={(e) => setOutputSchema(e.target.value)}
        />
      </label>
      <div className="form__actions">
        <button className="btn btn--primary" disabled={busy} onClick={submit}>
          {busy ? "..." : "Save verb"}
        </button>
        <AckLine ack={ack} />
        {error && <span className="error">{error}</span>}
      </div>
    </div>
  );
}

function BindingForm() {
  const caps = useFetch(() => api.capabilities(), []);
  const adapters = useFetch(() => api.adapters(), []);
  const [verbId, setVerbId] = useState("");
  const [targetType, setTargetType] = useState<TargetTypeValue>("adapter");
  const [targetRef, setTargetRef] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ack, setAck] = useState<StatusAck | null>(null);

  async function submit() {
    if (!verbId.trim() || !targetRef.trim()) {
      setError("Pick a verb and what should run it.");
      return;
    }
    setBusy(true);
    setError(null);
    setAck(null);
    try {
      setAck(
        await api.setBinding(verbId.trim(), {
          target_type: targetType,
          target_ref: targetRef.trim(),
        }),
      );
    } catch (err) {
      setError(errText(err));
    } finally {
      setBusy(false);
    }
  }

  const verbOptions = [
    { value: "", label: "Choose a verb..." },
    ...(caps.data?.verbs ?? []).map((v) => ({ value: v.id, label: v.id })),
  ];
  const adapterOptions = [
    { value: "", label: "Choose an adapter..." },
    ...(adapters.data?.adapters ?? []).map((a) => ({ value: a.id, label: a.id })),
  ];

  return (
    <div className="form">
      <div className="form__title">Set binding</div>
      <Hint>Wire a verb to what actually runs it - an adapter, or an agent.</Hint>
      <div className="form__grid">
        <Field label="Verb" hint="The action to wire up.">
          <Select value={verbId} ariaLabel="Verb" onChange={setVerbId} options={verbOptions} />
        </Field>
        <Field label="Runs via" hint="An adapter (a service) or an agent (a reasoning model).">
          <SegmentedV2
            value={targetType}
            ariaLabel="Target type"
            onChange={(v) => {
              setTargetType(v === "agent" ? "agent" : "adapter");
              setTargetRef("");
            }}
            options={[
              { value: "adapter", label: "An adapter" },
              { value: "agent", label: "An agent" },
            ]}
          />
        </Field>
        <Field
          label={targetType === "adapter" ? "Which adapter" : "Which agent"}
          hint={
            targetType === "adapter"
              ? "The registered adapter that fulfils this verb."
              : "The agent id that fulfils this verb."
          }
        >
          {targetType === "adapter" ? (
            <Select value={targetRef} ariaLabel="Adapter" onChange={setTargetRef} options={adapterOptions} />
          ) : (
            <input value={targetRef} onChange={(e) => setTargetRef(e.target.value)} />
          )}
        </Field>
      </div>
      <div className="form__actions">
        <button className="btn btn--primary" disabled={busy} onClick={submit}>
          {busy ? "Saving..." : "Set binding"}
        </button>
        <AckLine ack={ack} />
        {error && <span className="error">{error}</span>}
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
