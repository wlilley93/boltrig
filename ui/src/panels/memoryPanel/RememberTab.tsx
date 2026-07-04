import { useState } from "react";

import { api } from "../../api/client";
import type { MemoryRememberResponse } from "../../api/types";
import { errText } from "../shared";
import { Field, InfoCallout, Select } from "../ux";
import { denialText, isDenied, KIND_OPTIONS } from "./helpers";

type RememberFormProps = {
  content: string;
  setContent: (v: string) => void;
  kind: string;
  setKind: (v: string) => void;
  dataClass: "standard" | "sensitive";
  setDataClass: (v: "standard" | "sensitive") => void;
  busy: boolean;
  error: string | null;
  onSubmit: () => void;
};

function RememberForm(props: RememberFormProps) {
  const {
    content,
    setContent,
    kind,
    setKind,
    dataClass,
    setDataClass,
    busy,
    error,
    onSubmit,
  } = props;
  return (
    <div className="form">
      <div className="form__title">Remember</div>
      <p className="muted">
        Commit a fact to memory. It is screened before it persists and lands
        in your own scope. Sensitive content is held to a local-only endpoint
        (SEC-43).
      </p>
      <Field
        label="What should the assistant remember?"
        hint="A single fact, in plain language. It is screened before it is saved, and lands in your own scope."
        example="Priya is the account owner for Acme."
      >
        <textarea
          className="code"
          value={content}
          onChange={(e) => setContent(e.target.value)}
        />
      </Field>
      <div className="form__grid">
        <Field label="Type" hint="What kind of fact this is.">
          <Select
            value={kind || "entity"}
            ariaLabel="Fact type"
            onChange={setKind}
            options={KIND_OPTIONS}
          />
        </Field>
        <Field
          label="Sensitivity"
          hint="Sensitive facts never leave this deployment (SEC-43) - choose this for personal or confidential content."
        >
          <Select
            value={dataClass}
            ariaLabel="Sensitivity"
            onChange={(v) => setDataClass(v === "sensitive" ? "sensitive" : "standard")}
            options={[
              { value: "standard", label: "Standard" },
              { value: "sensitive", label: "Sensitive (kept local-only)" },
            ]}
          />
        </Field>
      </div>
      {dataClass === "sensitive" && (
        <InfoCallout tone="warn">
          Sensitive content is held to a local-only endpoint and never sent to
          an external model.
        </InfoCallout>
      )}
      <div className="form__actions">
        <button
          className="btn btn--primary"
          disabled={busy}
          onClick={onSubmit}
        >
          {busy ? "..." : "Remember"}
        </button>
        {error && <span className="error">{error}</span>}
      </div>
    </div>
  );
}

type RememberResultProps = {
  result: MemoryRememberResponse;
};

function RememberResult({ result }: RememberResultProps) {
  return (
    <div className="stack">
      <p className="ok">
        Saved to scope <code>{result.owner_scope ?? "?"}</code>.
      </p>
      <div className="row-line">
        <span className="muted">fact id(s)</span>
        <span className="kv">
          {(result.fact_ids ?? []).map((id) => (
            <code className="tag" key={id}>
              {id}
            </code>
          ))}
        </span>
      </div>
    </div>
  );
}

export function RememberTab() {
  const [content, setContent] = useState("");
  const [kind, setKind] = useState("");
  const [dataClass, setDataClass] = useState<"standard" | "sensitive">(
    "standard",
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<MemoryRememberResponse | null>(null);

  async function remember() {
    if (!content.trim()) {
      setError("Content is required.");
      return;
    }
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const res = await api.memoryRemember({
        content: content.trim(),
        kind: kind.trim() || undefined,
        data_class: dataClass,
      });
      if (isDenied(res)) {
        setError(denialText(res.reason));
        return;
      }
      setResult(res);
    } catch (err) {
      setError(errText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="stack">
      <RememberForm
        content={content}
        setContent={setContent}
        kind={kind}
        setKind={setKind}
        dataClass={dataClass}
        setDataClass={setDataClass}
        busy={busy}
        error={error}
        onSubmit={remember}
      />
      {result && <RememberResult result={result} />}
    </div>
  );
}
