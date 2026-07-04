import { useState } from "react";

import { api } from "@/api/client";
import type { CapabilitiesResponse, InvokeRequest, InvokeResult } from "@/api/types";
import type { FetchState } from "@/useFetch";
import { CodeBlock, RunLink, errText, parseJson } from "@/panels/shared";
import {
  CONSEQUENCE,
  EmptyState,
  Field,
  Hint,
  InfoCallout,
  Select,
  StatusBadge,
} from "@/panels/ux";
import { SchemaFormV2 } from "@/panels/uxForm";
import { runIdOf, safeObj, schemaKeys, skeletonFromSchema } from "./pure";

export function useInvoke(caps: FetchState<CapabilitiesResponse>) {
  const verbs = caps.data?.verbs ?? [];

  const [noun, setNoun] = useState("");
  const [verb, setVerb] = useState("");
  const [params, setParams] = useState("{}");
  const [invRun, setInvRun] = useState("");
  const [invContext, setInvContext] = useState("");
  const [manual, setManual] = useState(false);
  const [invBusy, setInvBusy] = useState(false);
  const [invError, setInvError] = useState<string | null>(null);
  const [invResult, setInvResult] = useState<InvokeResult | null>(null);

  const selectedVerb = verbs.find((v) => v.id === verb);
  const keys = schemaKeys(selectedVerb?.input_schema);

  function pickVerb(verbId: string) {
    const v = verbs.find((x) => x.id === verbId);
    if (v) {
      setNoun(v.noun);
      setVerb(v.id);
      // prefill the params box from the verb's schema unless the user has typed.
      if (params.trim() === "" || params.trim() === "{}") {
        setParams(skeletonFromSchema(v.input_schema));
      }
    }
  }

  async function invoke() {
    if (!noun.trim() || !verb.trim()) {
      setInvError("Pick a verb first.");
      return;
    }
    let p: Record<string, unknown>;
    let ctx: Record<string, unknown>;
    try {
      p = parseJson<Record<string, unknown>>(params, {});
    } catch (err) {
      setInvError(`params: ${errText(err)}`);
      return;
    }
    try {
      ctx = parseJson<Record<string, unknown>>(invContext, {});
    } catch (err) {
      setInvError(`context: ${errText(err)}`);
      return;
    }
    const rid = invRun.trim();
    if (rid) ctx = { ...ctx, run_id: rid };
    setInvBusy(true);
    setInvError(null);
    setInvResult(null);
    try {
      const req: InvokeRequest = { noun: noun.trim(), verb: verb.trim(), params: p };
      if (Object.keys(ctx).length > 0) req.context = ctx;
      const res = await api.invoke(req);
      setInvResult(res);
    } catch (err) {
      setInvError(errText(err));
    } finally {
      setInvBusy(false);
    }
  }

  return {
    caps,
    verbs,
    noun,
    setNoun,
    verb,
    setVerb,
    params,
    setParams,
    invRun,
    setInvRun,
    invContext,
    setInvContext,
    manual,
    setManual,
    invBusy,
    invError,
    invResult,
    selectedVerb,
    keys,
    pickVerb,
    invoke,
  };
}

function InvokeResultView({ result }: { result: InvokeResult }) {
  const runId = runIdOf(result);
  return (
    <div className="stack">
      <div className="row-line">
        <span className="badge">{result.status}</span>
        {runId && <RunLink runId={runId} />}
      </div>
      {result.status === "ok" && <CodeBlock value={result.output} />}
      {result.status === "degraded" && (
        <>
          <p className="notice warn">
            Adapter degraded; the output below is best-effort.
          </p>
          <CodeBlock value={result.output} />
        </>
      )}
      {result.status === "pending_human" && (
        <p className="notice">
          Paused for a human (HITL request{" "}
          <code>{result.hitl_request_id}</code>). Resolve it in Approvals.
        </p>
      )}
      {result.status === "denied" && <p className="error">denied: {result.reason}</p>}
      {result.status === "error" && <p className="error">error: {result.reason}</p>}
    </div>
  );
}

export function InvokeSection({ caps }: { caps: FetchState<CapabilitiesResponse> }) {
  const {
    verbs,
    noun,
    setNoun,
    verb,
    setVerb,
    params,
    setParams,
    invRun,
    setInvRun,
    invContext,
    setInvContext,
    manual,
    setManual,
    invBusy,
    invError,
    invResult,
    selectedVerb,
    keys,
    pickVerb,
    invoke,
  } = useInvoke(caps);

  const verbOptions = [
    { value: "", label: caps.loading ? "Loading verbs..." : "Choose a verb..." },
    ...verbs.map((v) => ({ value: v.id, label: `${v.noun} / ${v.id}` })),
  ];

  return (
    <div className="form">
      <div className="form__title">Invoke a verb</div>

      {caps.error ? (
        <p className="error">Could not load the verb registry: {caps.error}</p>
      ) : verbs.length === 0 && !caps.loading ? (
        <EmptyState
          title="No verbs are available to you"
          body="Your grants decide which verbs appear here. Switch identity in the sidebar, or ask an admin to widen your scope."
        />
      ) : null}

      <Field
        label="Verb"
        hint="Choose an action from the capabilities you are allowed to call."
      >
        <Select value="" ariaLabel="Pick a verb" onChange={pickVerb} options={verbOptions} />
      </Field>

      {selectedVerb && (
        <div className="row-line" style={{ borderBottom: "none", paddingBottom: 0 }}>
          <span className="ux-hint">
            Selected: <code className="mono">{verb}</code> on{" "}
            <code className="mono">{noun}</code>
          </span>
          <StatusBadge value={selectedVerb.consequence} glossary={CONSEQUENCE} />
        </div>
      )}
      {selectedVerb?.consequence === "high" && (
        <InfoCallout tone="consequence" title="High-consequence verb">
          This performs a real, possibly irreversible action (it changes state,
          sends, or spends). It may pause for human approval before running.
        </InfoCallout>
      )}

      {selectedVerb && (keys.required.length || keys.optional.length) ? (
        <>
          <div className="form__title" style={{ fontSize: "var(--fs-sm)" }}>
            Arguments
          </div>
          <Hint>The values this verb expects. They are data the kernel passes in, never executed.</Hint>
          <SchemaFormV2
            schema={selectedVerb.input_schema}
            value={safeObj(params)}
            onChange={(o) => setParams(JSON.stringify(o, null, 2))}
          />
          <details>
            <summary className="ux-hint" style={{ cursor: "pointer" }}>
              Edit as JSON / show schema
            </summary>
            <textarea
              className="code"
              value={params}
              onChange={(e) => setParams(e.target.value)}
            />
            <CodeBlock value={selectedVerb.input_schema} />
          </details>
        </>
      ) : (
        <Field
          label="Arguments"
          hint={
            selectedVerb
              ? "This verb takes no arguments."
              : "Pick a verb to see the arguments it expects. Arguments are JSON the kernel passes to the verb - they are data, never executed."
          }
        >
          <textarea
            className="code"
            value={params}
            onChange={(e) => setParams(e.target.value)}
          />
        </Field>
      )}

      <details open={manual} onToggle={(e) => setManual((e.target as HTMLDetailsElement).open)}>
        <summary className="ux-hint" style={{ cursor: "pointer" }}>
          Advanced: run id, context, manual verb entry
        </summary>
        <div className="form__grid" style={{ marginTop: 10 }}>
          <Field
            label="Run id"
            hint="Attach this call to an existing run for audit threading. Leave blank to start fresh."
          >
            <input value={invRun} onChange={(e) => setInvRun(e.target.value)} />
          </Field>
          <Field label="Noun" hint="Set automatically from the verb you pick.">
            <input value={noun} onChange={(e) => setNoun(e.target.value)} />
          </Field>
          <Field label="Verb id" hint="Set automatically from the picker.">
            <input value={verb} onChange={(e) => setVerb(e.target.value)} />
          </Field>
        </div>
        <Field
          label="Extra context (JSON)"
          hint="Extra execution context for the kernel. Most calls leave this empty."
          example='{"idempotency_key": "..."}'
        >
          <textarea
            className="code"
            value={invContext}
            onChange={(e) => setInvContext(e.target.value)}
          />
        </Field>
      </details>

      <div className="form__actions">
        <button
          className="btn btn--primary"
          disabled={invBusy || !verb}
          onClick={invoke}
        >
          {invBusy ? "Running..." : "Run verb"}
        </button>
        {invError && <span className="error">{invError}</span>}
      </div>
      {invResult && <InvokeResultView result={invResult} />}
    </div>
  );
}
