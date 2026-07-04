import { useState } from "react";

import { api } from "../../api/client";
import type { MemoryFactView } from "../../api/types";
import { useFetch } from "../../useFetch";
import { errText } from "../shared";
import { FetchError, Field, InfoCallout, Select } from "../ux";
import { denialText, isDenied, KIND_FILTER_OPTIONS } from "./helpers";
import { FactCard } from "./FactCard";

type BrowseFilterProps = {
  kind: string;
  setKind: (v: string) => void;
  onRefresh: () => void;
  scopes: string[];
  forgetMsg: string | null;
  forgetError: string | null;
};

function BrowseFilter(props: BrowseFilterProps) {
  const { kind, setKind, onRefresh, scopes, forgetMsg, forgetError } = props;
  return (
    <div className="form">
      <div className="form__title">Browse facts</div>
      <p className="muted">
        The facts you may see, with provenance. Scope-filtered server-side, so
        another user's or department's memory never appears here.
      </p>
      <div className="form__actions">
        <Field label="Show only" hint="Filter to one type of fact.">
          <Select
            value={kind}
            ariaLabel="Filter by type"
            onChange={setKind}
            options={KIND_FILTER_OPTIONS}
          />
        </Field>
        <button className="btn" onClick={onRefresh}>
          Refresh
        </button>
      </div>
      {scopes.length > 0 && (
        <p className="muted">
          scopes:{" "}
          {scopes.map((s) => (
            <code className="tag" key={s}>
              {s}
            </code>
          ))}
        </p>
      )}
      {forgetMsg && <p className="ok">{forgetMsg}</p>}
      {forgetError && <p className="error">{forgetError}</p>}
    </div>
  );
}

type BrowseResultsProps = {
  list: MemoryFactView[];
  loading: boolean;
  hasData: boolean;
  error: string | null;
  errorStatus: number | null;
  onRetry: () => void;
  forgetting: string | null;
  onForget: (id: string) => void;
};

function BrowseResults(props: BrowseResultsProps) {
  const { list, loading, hasData, error, errorStatus, onRetry, forgetting, onForget } = props;
  return (
    <div className="list-card">
      <div className="list-card__head">
        <h3>Facts</h3>
        <span className="muted">{list.length}</span>
      </div>
      <div className="list-card__body">
        {loading && !hasData && <p className="muted">Loading...</p>}
        {error &&
          (/binding_not_found/.test(error) ? (
            <InfoCallout tone="warn">Memory is not enabled for your org.</InfoCallout>
          ) : (
            <FetchError error={error} status={errorStatus} onRetry={onRetry} />
          ))}
        {!loading && !error && list.length === 0 && (
          <p className="muted">
            No facts in your scope yet. Add one in the Remember tab, or load a
            source in Ingest.
          </p>
        )}
        {list.length > 0 && (
          <div className="mem-facts">
            {list.map((f) => (
              <FactCard
                fact={f}
                key={f.id}
                footer={
                  <button
                    className="btn btn--danger"
                    disabled={forgetting === f.id}
                    title="Erase this fact and its links - permanent."
                    onClick={() => onForget(f.id)}
                  >
                    {forgetting === f.id ? "Forgetting..." : "Forget"}
                  </button>
                }
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export function BrowseTab() {
  const [kind, setKind] = useState("");
  const facts = useFetch(
    () => api.memoryFacts({ kind: kind.trim() || undefined }),
    [kind],
  );

  const [forgetting, setForgetting] = useState<string | null>(null);
  const [forgetError, setForgetError] = useState<string | null>(null);
  const [forgetMsg, setForgetMsg] = useState<string | null>(null);

  async function forget(id: string) {
    if (!window.confirm(`Forget fact ${id}? This erases it and its edges.`)) {
      return;
    }
    setForgetting(id);
    setForgetError(null);
    setForgetMsg(null);
    try {
      const res = await api.memoryForget({ target: id });
      if (isDenied(res)) {
        setForgetError(denialText(res.reason));
        return;
      }
      setForgetMsg(
        `Forgot ${id}: ${res.facts_removed ?? 0} fact(s) removed.`,
      );
      facts.reload();
    } catch (err) {
      setForgetError(errText(err));
    } finally {
      setForgetting(null);
    }
  }

  const list: MemoryFactView[] = facts.data?.facts ?? [];
  const scopes: string[] = facts.data?.scopes ?? [];

  return (
    <div className="stack">
      <BrowseFilter
        kind={kind}
        setKind={setKind}
        onRefresh={facts.reload}
        scopes={scopes}
        forgetMsg={forgetMsg}
        forgetError={forgetError}
      />
      <BrowseResults
        list={list}
        loading={facts.loading}
        hasData={!!facts.data}
        error={facts.error}
        errorStatus={facts.errorStatus}
        onRetry={facts.reload}
        forgetting={forgetting}
        onForget={forget}
      />
    </div>
  );
}
