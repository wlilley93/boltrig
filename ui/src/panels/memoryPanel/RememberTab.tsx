import { useState } from "react";

import { api } from "@/api/client";
import type { MemoryRememberResponse } from "@/api/types";
import { errText } from "@/panels/shared";
import { Field, InfoCallout, Select } from "@/panels/ux";
import { denialText, isDenied, KIND_OPTIONS } from "@/panels/memoryPanel/helpers";
import { ChipPicker } from "@/panels/uxForm";

type RememberFormProps = {
  content: string;
  setContent: (v: string) => void;
  kind: string;
  setKind: (v: string) => void;
  dataClass: "standard" | "sensitive";
  setDataClass: (v: "standard" | "sensitive") => void;
  ownerScope: string;
  setOwnerScope: (v: string) => void;
  sourceKind: string;
  setSourceKind: (v: string) => void;
  sourceRef: string;
  setSourceRef: (v: string) => void;
  relatesTo: string[];
  setRelatesTo: (v: string[]) => void;
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
    ownerScope,
    setOwnerScope,
    sourceKind,
    setSourceKind,
    sourceRef,
    setSourceRef,
    relatesTo,
    setRelatesTo,
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
        htmlFor="memory-content"
        hint="A single fact, in plain language. It is screened before it is saved, and lands in your own scope."
        example="Priya is the account owner for Acme."
      >
        <textarea
          id="memory-content"
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
      <details className="form__advanced">
        <summary>Scope and provenance</summary>
        <p className="muted">
          Optional trace fields make this fact explainable and allow exact source erasure later.
          The server still enforces which owner scopes you may write.
        </p>
        <div className="form__grid">
          <Field label="Owner scope" htmlFor="memory-owner-scope" hint="Leave empty for your default user scope." example="user:alice">
            <input id="memory-owner-scope" value={ownerScope} onChange={(event) => setOwnerScope(event.target.value)} />
          </Field>
          <Field label="Source type" htmlFor="memory-source-kind" hint="Where this fact originated.">
            <Select
              id="memory-source-kind"
              value={sourceKind}
              ariaLabel="Source type"
              onChange={setSourceKind}
              options={[
                { value: "verb_result", label: "Tool or verb result" },
                { value: "conversation", label: "Conversation" },
                { value: "document", label: "Document" },
                { value: "feedback", label: "Feedback" },
              ]}
            />
          </Field>
          <Field label="Source reference" htmlFor="memory-source-ref" hint="An exact stable identifier used for provenance and source erasure." example="conversation:conv-42">
            <input id="memory-source-ref" value={sourceRef} onChange={(event) => setSourceRef(event.target.value)} />
          </Field>
          <Field label="Related facts" hint="Existing fact IDs this fact may link to. Cross-scope links are dropped server-side.">
            <ChipPicker
              value={relatesTo}
              onChange={setRelatesTo}
              allowFree
              mono
              ariaLabel="Related fact IDs"
              placeholder="Add a fact ID"
              validate={(value) => value.trim() ? null : "Fact ID cannot be empty"}
            />
          </Field>
        </div>
      </details>
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
  const [ownerScope, setOwnerScope] = useState("");
  const [sourceKind, setSourceKind] = useState("verb_result");
  const [sourceRef, setSourceRef] = useState("");
  const [relatesTo, setRelatesTo] = useState<string[]>([]);
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
        owner_scope: ownerScope.trim() || undefined,
        source_kind: sourceKind,
        source_ref: sourceRef.trim() || undefined,
        relates_to: relatesTo,
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
        ownerScope={ownerScope}
        setOwnerScope={setOwnerScope}
        sourceKind={sourceKind}
        setSourceKind={setSourceKind}
        sourceRef={sourceRef}
        setSourceRef={setSourceRef}
        relatesTo={relatesTo}
        setRelatesTo={setRelatesTo}
        busy={busy}
        error={error}
        onSubmit={remember}
      />
      {result && <RememberResult result={result} />}
    </div>
  );
}
