import { useState } from "react";

import { api } from "@/api/client";
import type { MemoryFactView } from "@/api/types";
import { useFetch } from "@/useFetch";
import { FetchError, Field, InfoCallout, Select } from "@/panels/ux";
import { denialText, isDenied, KIND_FILTER_OPTIONS } from "@/panels/memoryPanel/helpers";
import { FactCard } from "@/panels/memoryPanel/FactCard";
import { ArmConfirm } from "@/panels/uxFlow";

type BrowseFilterProps = {
  kind: string;
  setKind: (v: string) => void;
  onRefresh: () => void;
  scopes: string[];
  forgetMsg: string | null;
  sourceRef: string;
  setSourceRef: (value: string) => void;
  onForgetSource: () => Promise<void>;
};

function BrowseFilter(props: BrowseFilterProps) {
  const { kind, setKind, onRefresh, scopes, forgetMsg, sourceRef, setSourceRef, onForgetSource } = props;
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
      <div className="form__grid">
        <Field
          label="Erase by source"
          htmlFor="memory-forget-source"
          hint="Remove every fact derived from one exact source reference, including derived edges."
          example="document:launch-plan-v3"
        >
          <input
            id="memory-forget-source"
            value={sourceRef}
            onChange={(event) => setSourceRef(event.target.value)}
            placeholder="Exact source_ref"
          />
        </Field>
        <div className="form__actions">
          <ArmConfirm
            label="Forget source"
            armLabel={<>Erase all memory derived from <code>{sourceRef.trim()}</code>? This is permanent and audited.</>}
            confirmLabel="Erase source memory"
            busyLabel="Erasing..."
            tone="danger"
            disabled={!sourceRef.trim()}
            onConfirm={onForgetSource}
          />
        </div>
      </div>
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
  onForget: (id: string) => Promise<void>;
};

function BrowseResults(props: BrowseResultsProps) {
  const { list, loading, hasData, error, errorStatus, onRetry, onForget } = props;
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
                  <ArmConfirm
                    label="Forget"
                    armLabel={<>Erase fact <code>{f.id}</code> and its edges? This is permanent and audited.</>}
                    confirmLabel={`Erase fact ${f.id}`}
                    busyLabel="Erasing..."
                    tone="danger"
                    onConfirm={() => onForget(f.id)}
                  />
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

  const [forgetMsg, setForgetMsg] = useState<string | null>(null);
  const [sourceRef, setSourceRef] = useState("");

  async function forget(id: string) {
    setForgetMsg(null);
    const res = await api.memoryForget({ target: id });
    if (isDenied(res)) {
      throw new Error(denialText(res.reason));
    }
    setForgetMsg(`Forgot ${id}: ${res.facts_removed ?? 0} fact(s) removed.`);
    facts.reload();
  }

  async function forgetSource() {
    const exact = sourceRef.trim();
    if (!exact) return;
    setForgetMsg(null);
    const res = await api.memoryForget({ source_ref: exact });
    if (isDenied(res)) throw new Error(denialText(res.reason));
    setForgetMsg(`Forgot source ${exact}: ${res.facts_removed ?? 0} fact(s) removed.`);
    setSourceRef("");
    facts.reload();
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
        sourceRef={sourceRef}
        setSourceRef={setSourceRef}
        onForgetSource={forgetSource}
      />
      <BrowseResults
        list={list}
        loading={facts.loading}
        hasData={!!facts.data}
        error={facts.error}
        errorStatus={facts.errorStatus}
        onRetry={facts.reload}
        onForget={forget}
      />
    </div>
  );
}
