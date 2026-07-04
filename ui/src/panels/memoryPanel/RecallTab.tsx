import { useState } from "react";

import { api } from "../../api/client";
import type { MemoryFactView, RecallMode } from "../../api/types";
import { errText } from "../shared";
import { EmptyState, Field, Select } from "../ux";
import { denialText, isDenied, RECALL_MODE_OPTIONS } from "./helpers";
import { FactCard } from "./FactCard";

type RecallFormFieldsProps = {
  query: string;
  setQuery: (v: string) => void;
  mode: RecallMode;
  setMode: (v: RecallMode) => void;
  limit: string;
  setLimit: (v: string) => void;
  busy: boolean;
  error: string | null;
  onSubmit: () => void;
};

function RecallFormFields(props: RecallFormFieldsProps) {
  const { query, setQuery, mode, setMode, limit, setLimit, busy, error, onSubmit } = props;
  return (
    <div className="form">
      <div className="form__title">Search your memory</div>
      <Field
        label="What are you looking for?"
        hint="A plain-language question or keywords. You only ever see memory you're allowed to (your scope, your departments, the org)."
        example="what does Priya own?"
      >
        <input value={query} onChange={(e) => setQuery(e.target.value)} />
      </Field>
      <div className="form__grid">
        <Field
          label="How to search"
          hint="Connections starts from matching facts and follows links to related ones (showing the path). Similarity just finds facts that read like your query."
        >
          <Select
            value={mode}
            ariaLabel="Search mode"
            onChange={(v) => setMode(v === "similarity" ? "similarity" : "graph_completion")}
            options={RECALL_MODE_OPTIONS}
          />
        </Field>
        <Field label="Max results">
          <input
            value={limit}
            inputMode="numeric"
            onChange={(e) => setLimit(e.target.value)}
          />
        </Field>
      </div>
      <div className="form__actions">
        <button className="btn btn--primary" disabled={busy} onClick={onSubmit}>
          {busy ? "Searching..." : "Search"}
        </button>
        {error && <span className="error">{error}</span>}
      </div>
    </div>
  );
}

type RecallResultsProps = {
  facts: MemoryFactView[];
  count: number;
};

function RecallResults({ facts, count }: RecallResultsProps) {
  return (
    <div className="list-card">
      <div className="list-card__head">
        <h3>Results</h3>
        <span className="muted">{count}</span>
      </div>
      <div className="list-card__body">
        {facts.length === 0 ? (
          <p className="muted">
            No facts in scope match this query. Try different words, or
            remember a fact first.
          </p>
        ) : (
          <div className="mem-facts">
            {facts.map((f) => (
              <FactCard fact={f} key={f.id} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export function RecallTab() {
  const [query, setQuery] = useState("");
  const [mode, setMode] = useState<RecallMode>("graph_completion");
  const [limit, setLimit] = useState("20");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [facts, setFacts] = useState<MemoryFactView[] | null>(null);
  const [count, setCount] = useState(0);

  async function recall() {
    if (!query.trim()) {
      setError("A query is required.");
      return;
    }
    const parsedLimit = Number.parseInt(limit, 10);
    setBusy(true);
    setError(null);
    setFacts(null);
    try {
      const res = await api.memoryRecall({
        query: query.trim(),
        mode,
        limit: Number.isFinite(parsedLimit) ? parsedLimit : undefined,
      });
      if (isDenied(res)) {
        setError(denialText(res.reason));
        return;
      }
      setFacts(res.facts ?? []);
      setCount(res.count ?? (res.facts ?? []).length);
    } catch (err) {
      setError(errText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="stack">
      <RecallFormFields
        query={query}
        setQuery={setQuery}
        mode={mode}
        setMode={setMode}
        limit={limit}
        setLimit={setLimit}
        busy={busy}
        error={error}
        onSubmit={recall}
      />
      {facts ? (
        <RecallResults facts={facts} count={count} />
      ) : (
        <EmptyState title="Search your memory" body="Ask a question above to see what the assistant remembers." />
      )}
    </div>
  );
}
