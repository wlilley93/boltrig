import { useEffect, useMemo, useRef, useState } from "react";
import {
  BoltrigApiError,
  buildCapabilityParams,
  compileCapabilityForm,
  projectCapabilityOutput,
  type CapabilityFormField,
  type InvokeRequest,
  type InvokeResult,
  type VerbInfo,
} from "@wlilley93/boltrig-web-sdk";

import { client } from "../../client";

type DiscoveryState =
  | { status: "loading" }
  | { status: "ready" }
  | { status: "denied"; reason: string }
  | { status: "unavailable"; reason: string };

interface PendingInvocation {
  request: InvokeRequest;
  approvalId: string;
  verbKey: string;
  verb: VerbInfo;
  invalidated: boolean;
}

interface InvocationReceiptState {
  result: InvokeResult;
  verb: VerbInfo;
}

interface RetryInvocation {
  request: InvokeRequest;
  verb: VerbInfo;
}

type FinalizationState =
  | "waiting"
  | "checking"
  | "invalidated"
  | "rejected"
  | "expired"
  | "consumed"
  | "unavailable"
  | null;

function capabilityKey(verb: VerbInfo): string {
  return JSON.stringify([verb.noun, verb.id]);
}

function reasonFrom(error: unknown, fallback: string): string {
  if (error instanceof BoltrigApiError) {
    const body = error.body;
    if (body !== null && typeof body === "object" && !Array.isArray(body)) {
      const reason = (body as Record<string, unknown>).reason;
      const detail = (body as Record<string, unknown>).detail;
      if (typeof reason === "string") return reason;
      if (typeof detail === "string") return detail;
    }
    return error.message;
  }
  return error instanceof Error ? error.message : fallback;
}

function verbLabel(verb: VerbInfo): string {
  return verb.id.startsWith(`${verb.noun}.`) ? verb.id : `${verb.noun} · ${verb.id}`;
}

function inputType(field: CapabilityFormField): string {
  if (field.kind === "integer" || field.kind === "number") return "number";
  if (field.format === "email") return "email";
  if (field.format === "uri") return "url";
  if (field.format === "date") return "date";
  return "text";
}

function InvocationField({
  field,
  value,
  error,
  onChange,
}: {
  field: CapabilityFormField;
  value: string;
  error?: string;
  onChange: (value: string) => void;
}) {
  const describedBy = [
    field.description ? `${field.id}-description` : "",
    error ? `${field.id}-error` : "",
  ].filter(Boolean).join(" ") || undefined;
  const label = `${field.label}${field.required ? " (required)" : ""}`;
  return (
    <label className="capability-field">
      <span>{label}</span>
      {field.enum ? (
        <select
          aria-label={label}
          aria-describedby={describedBy}
          aria-invalid={Boolean(error)}
          value={value}
          onChange={(event) => onChange(event.target.value)}
        >
          <option value="">Select…</option>
          {field.enum.map((item) => (
            <option value={String(item)} key={`${typeof item}:${String(item)}`}>
              {String(item)}
            </option>
          ))}
        </select>
      ) : field.kind === "boolean" ? (
        <select
          aria-label={label}
          aria-describedby={describedBy}
          aria-invalid={Boolean(error)}
          value={value}
          onChange={(event) => onChange(event.target.value)}
        >
          <option value="">Not set</option>
          <option value="true">True</option>
          <option value="false">False</option>
        </select>
      ) : field.kind.endsWith("_array") ? (
        <textarea
          aria-label={label}
          aria-describedby={describedBy}
          aria-invalid={Boolean(error)}
          value={value}
          rows={4}
          placeholder="One value per line"
          onChange={(event) => onChange(event.target.value)}
        />
      ) : (
        <input
          aria-label={label}
          aria-describedby={describedBy}
          aria-invalid={Boolean(error)}
          type={inputType(field)}
          step={field.kind === "integer" ? "1" : field.kind === "number" ? "any" : undefined}
          min={field.minimum}
          max={field.maximum}
          minLength={field.min_length}
          maxLength={field.max_length}
          value={value}
          onChange={(event) => onChange(event.target.value)}
        />
      )}
      {field.description && <small id={`${field.id}-description`}>{field.description}</small>}
      {field.kind.endsWith("_array") && !field.description && <small>Enter one value per line.</small>}
      {error && <small className="field-error" id={`${field.id}-error`}>{error}</small>}
    </label>
  );
}

function InvocationReceipt({
  receipt,
  verb,
}: {
  receipt: InvokeResult;
  verb: VerbInfo;
}) {
  if (receipt.status === "pending_human") {
    return (
      <section className="invocation-receipt pending" aria-label="Pending human receipt">
        <p className="eyebrow">Pending human</p>
        <h3>Waiting for approval in the originating chat</h3>
        <p>The kernel paused this exact invocation. It has not been reported as completed.</p>
        <code>{receipt.hitl_request_id}</code>
      </section>
    );
  }
  if (receipt.status === "denied") {
    return (
      <section className="invocation-receipt denied" aria-label="Denied receipt">
        <p className="eyebrow">Denied</p>
        <h3>The kernel refused this invocation</h3>
        <p>{receipt.reason}</p>
      </section>
    );
  }
  if (receipt.status === "unavailable") {
    return (
      <section className="invocation-receipt unavailable" aria-label="Unavailable receipt">
        <p className="eyebrow">Unavailable</p>
        <h3>The invocation service is unavailable</h3>
        <p>{receipt.reason}</p>
      </section>
    );
  }
  if (receipt.status === "error") {
    return (
      <section className="invocation-receipt error" aria-label="Error receipt">
        <p className="eyebrow">Error</p>
        <h3>The invocation did not complete</h3>
        <p>{receipt.reason}</p>
      </section>
    );
  }
  const projection = projectCapabilityOutput(verb.output_schema, receipt.output);
  return (
    <section
      className={`invocation-receipt ${receipt.status}`}
      aria-label={`${receipt.status === "ok" ? "Completed" : "Degraded"} receipt`}
    >
      <p className="eyebrow">{receipt.status === "ok" ? "Completed" : "Degraded"}</p>
      <h3>
        {receipt.status === "ok"
          ? "The kernel completed this invocation"
          : "The capability returned a degraded result"}
      </h3>
      {projection.status === "visible" ? (
        <>
          <p>Only fields declared by the capability output schema are shown.</p>
          <pre>{JSON.stringify(projection.value, null, 2)}</pre>
        </>
      ) : (
        <p>Result payload hidden: {projection.reason}</p>
      )}
    </section>
  );
}

function FinalizationReceipt({
  state,
  canCheck,
  running,
  onCheck,
}: {
  state: FinalizationState;
  canCheck: boolean;
  running: boolean;
  onCheck: () => void;
}) {
  if (state === null) return null;
  const detail = {
    invalidated: [
      "Pending invocation changed",
      "The selected capability or generated inputs changed. This surface will not apply the old approval to a different request.",
    ],
    rejected: [
      "Approval rejected",
      "An independent human rejected this invocation. Nothing was executed.",
    ],
    expired: [
      "Approval expired",
      "The approval can no longer authorize execution. Nothing is reported as completed.",
    ],
    consumed: [
      "Approval already consumed",
      "The approval was spent, but this capability does not support a cacheable result replay. Inspect the target resource before starting another invocation.",
    ],
    unavailable: [
      "Approval status unavailable",
      "The approval record could not be checked. No execution is inferred.",
    ],
  } as const;
  const settled = state in detail;
  const copy = settled ? detail[state as keyof typeof detail] : null;
  return (
    <section
      className={`invocation-receipt approval-${state}`}
      aria-label={`${state} approval receipt`}
    >
      <p className="eyebrow">Approval finalization</p>
      <h3>{copy?.[0] ?? (state === "checking" ? "Checking approval…" : "Waiting for a decision")}</h3>
      <p>
        {copy?.[1]
          ?? "After an independent decision in the originating chat, check again to execute the exact component-held request."}
      </p>
      {(state === "waiting" || state === "unavailable") && (
        <button className="secondary-button" disabled={!canCheck || running} onClick={onCheck}>
          Check approval and continue
        </button>
      )}
    </section>
  );
}

export function CapabilityRunner() {
  const [verbs, setVerbs] = useState<VerbInfo[]>([]);
  const [selectedKey, setSelectedKey] = useState("");
  const [discovery, setDiscovery] = useState<DiscoveryState>({ status: "loading" });
  const [values, setValues] = useState<Record<string, string>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [receipt, setReceipt] = useState<InvocationReceiptState | null>(null);
  const [retryRequest, setRetryRequest] = useState<RetryInvocation | null>(null);
  const [pendingInvocation, setPendingInvocation] = useState<PendingInvocation | null>(null);
  const [finalization, setFinalization] = useState<FinalizationState>(null);
  const [running, setRunning] = useState(false);
  const requestGeneration = useRef(0);

  function invalidateRequestPresentation() {
    requestGeneration.current += 1;
    setRunning(false);
  }

  function refresh() {
    invalidateRequestPresentation();
    setDiscovery({ status: "loading" });
    setReceipt(null);
    setRetryRequest(null);
    setPendingInvocation((current) => (
      current === null ? null : { ...current, invalidated: true }
    ));
    setFinalization((current) => (
      current === "waiting" || current === "checking" ? "invalidated" : current
    ));
    void client.capabilities()
      .then((result) => {
        const scoped = result.verbs.filter(
          (verb) => typeof verb.id === "string" && typeof verb.noun === "string",
        );
        setVerbs(scoped);
        setSelectedKey((current) => (
          scoped.some((verb) => capabilityKey(verb) === current)
            ? current
            : scoped[0] ? capabilityKey(scoped[0]) : ""
        ));
        setDiscovery({ status: "ready" });
      })
      .catch((error: unknown) => {
        setVerbs([]);
        if (error instanceof BoltrigApiError && (error.status === 401 || error.status === 403)) {
          setDiscovery({
            status: "denied",
            reason: reasonFrom(error, "Capability discovery was denied."),
          });
        } else {
          setDiscovery({
            status: "unavailable",
            reason: reasonFrom(error, "Capability discovery is unavailable."),
          });
        }
      });
  }

  useEffect(refresh, []);

  const selected = useMemo(
    () => verbs.find((verb) => capabilityKey(verb) === selectedKey) ?? null,
    [selectedKey, verbs],
  );
  const contract = useMemo(
    () => compileCapabilityForm(selected?.input_schema ?? null),
    [selected],
  );
  const blocker = selected === null
    ? "Select a caller-visible capability."
    : !selected.binding
      ? "This capability has no execution binding."
      : selected.health === "down"
        ? "The capability binding is currently down."
        : contract.status === "unavailable"
          ? contract.reason
          : null;

  function selectCapability(key: string) {
    invalidateRequestPresentation();
    setSelectedKey(key);
    setValues({});
    setErrors({});
    setReceipt(null);
    setRetryRequest(null);
    setPendingInvocation((current) => (
      current === null ? null : { ...current, invalidated: true }
    ));
    setFinalization((current) => (
      current === "waiting" || current === "checking" ? "invalidated" : current
    ));
  }

  async function sendRequest(request: InvokeRequest, verb: VerbInfo) {
    const generation = ++requestGeneration.current;
    setReceipt(null);
    setRunning(true);
    try {
      const result = await client.invoke(request);
      if (requestGeneration.current !== generation) return;
      setReceipt({ result, verb });
      if (result.status === "pending_human") {
        const { approval_id: _approvalId, ...baseRequest } = request;
        setPendingInvocation({
          request: baseRequest,
          approvalId: result.hitl_request_id,
          verbKey: JSON.stringify([request.noun, request.verb]),
          verb,
          invalidated: false,
        });
        setFinalization("waiting");
      } else if (
        request.approval_id === undefined
        || !["unavailable", "error"].includes(result.status)
      ) {
        setPendingInvocation(null);
        setFinalization(null);
      } else {
        setFinalization("unavailable");
      }
      setRetryRequest(
        request.idempotency_key !== undefined
        && (result.status === "unavailable" || result.status === "error")
          ? { request, verb }
          : null,
      );
    } catch (error) {
      if (requestGeneration.current !== generation) return;
      setReceipt({
        result: {
          status: "unavailable",
          reason: reasonFrom(error, "Invocation is unavailable."),
        },
        verb,
      });
      setRetryRequest(
        request.idempotency_key !== undefined ? { request, verb } : null,
      );
      if (request.approval_id !== undefined) setFinalization("unavailable");
    } finally {
      if (requestGeneration.current === generation) setRunning(false);
    }
  }

  async function invoke() {
    if (selected === null || blocker !== null || contract.status !== "ready") return;
    const built = buildCapabilityParams(contract, values);
    if (built.status === "invalid") {
      setErrors(built.field_errors);
      return;
    }
    setErrors({});
    const request: InvokeRequest = {
      noun: selected.noun,
      verb: selected.id,
      params: built.params,
      ...(selected.idempotency_mode === "cacheable"
        ? { idempotency_key: crypto.randomUUID() }
        : {}),
    };
    await sendRequest(request, selected);
  }

  async function finalizePending() {
    const pending = pendingInvocation;
    if (
      pending === null
      || pending.invalidated
      || selected === null
      || capabilityKey(selected) !== pending.verbKey
    ) {
      setFinalization("invalidated");
      return;
    }
    const generation = ++requestGeneration.current;
    setFinalization("checking");
    try {
      const state = await client.invokeApprovalState(pending.approvalId);
      if (requestGeneration.current !== generation) return;
      if (state.status === "pending") {
        setFinalization("waiting");
        return;
      }
      if (state.status === "rejected" || state.status === "expired") {
        setReceipt(null);
        setRetryRequest(null);
        setFinalization(state.status);
        return;
      }
      if (
        state.status === "consumed"
        && pending.request.idempotency_key === undefined
      ) {
        setReceipt(null);
        setRetryRequest(null);
        setFinalization("consumed");
        return;
      }
      await sendRequest({
        ...pending.request,
        approval_id: pending.approvalId,
      }, pending.verb);
    } catch {
      if (requestGeneration.current === generation) {
        setFinalization("unavailable");
      }
    }
  }

  return (
    <section className="capability-runner">
      <div className="settings-card">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Caller-scoped registry</p>
            <h2>Run a capability</h2>
          </div>
          <button className="secondary-button" onClick={refresh} disabled={discovery.status === "loading"}>
            Refresh
          </button>
        </div>
        <p>
          Choose only from capabilities the kernel exposed to this identity. Inputs are generated
          from a closed safe subset of the registered schema; there is no raw parameter, context,
          approval or credential field.
        </p>
        {discovery.status === "loading" && <p className="notice" role="status">Loading caller-visible capabilities…</p>}
        {discovery.status === "denied" && (
          <p className="notice" role="alert">Capability discovery denied: {discovery.reason}</p>
        )}
        {discovery.status === "unavailable" && (
          <p className="notice" role="status">Capability discovery unavailable: {discovery.reason}</p>
        )}
        {discovery.status === "ready" && verbs.length === 0 && (
          <p className="notice" role="status">No invokable capabilities are visible to this identity.</p>
        )}
        {verbs.length > 0 && (
          <label className="field-control capability-picker">
            <span>Capability</span>
            <select
              aria-label="Capability"
              value={selectedKey}
              onChange={(event) => selectCapability(event.target.value)}
            >
              {verbs.map((verb) => (
                <option value={capabilityKey(verb)} key={capabilityKey(verb)}>
                  {verbLabel(verb)}
                </option>
              ))}
            </select>
          </label>
        )}
        {selected && (
          <div className="capability-summary">
            <span>{selected.consequence === "high" ? "High consequence" : "Low consequence"}</span>
            <span>
              {selected.binding
                ? `${selected.binding.target_type} · ${selected.binding.target_ref}`
                : "Unbound"}
            </span>
            <span>Health · {selected.health ?? "not reported"}</span>
            <span>Retry · {selected.idempotency_mode ?? "not reported"}</span>
          </div>
        )}
      </div>

      {selected && (
        <div className="settings-card">
          <div className="section-heading">
            <div>
              <p className="eyebrow">Generated input</p>
              <h2>{verbLabel(selected)}</h2>
            </div>
          </div>
          {blocker !== null ? (
            <div className="notice invocation-unavailable" role="status">
              <strong>Invocation unavailable for this schema</strong>
              <span>{blocker}</span>
            </div>
          ) : contract.status === "ready" ? (
            <form
              className="capability-form"
              noValidate
              onSubmit={(event) => {
                event.preventDefault();
                void invoke();
              }}
            >
              {contract.fields.length === 0 ? (
                <p className="muted">This capability declares no input fields.</p>
              ) : (
                <div className="capability-fields">
                  {contract.fields.map((field) => (
                    <InvocationField
                      field={field}
                      value={values[field.id] ?? ""}
                      error={errors[field.id]}
                      key={field.id}
                      onChange={(value) => {
                        invalidateRequestPresentation();
                        setValues((current) => ({ ...current, [field.id]: value }));
                        setReceipt(null);
                        setRetryRequest(null);
                        setPendingInvocation((current) => (
                          current === null ? null : { ...current, invalidated: true }
                        ));
                        setFinalization((current) => (
                          current === "waiting" || current === "checking"
                            ? "invalidated"
                            : current
                        ));
                        setErrors((current) => {
                          const next = { ...current };
                          delete next[field.id];
                          return next;
                        });
                      }}
                    />
                  ))}
                </div>
              )}
              {selected.consequence === "high" && (
                <p className="notice">
                  High-consequence execution may pause for an independent human decision in the originating chat.
                </p>
              )}
              {selected.idempotency_mode === "disabled" && (
                <p className="notice">
                  This capability disables replay caching. An ambiguous result cannot be retried
                  safely from this generic surface.
                </p>
              )}
              <button className="primary-button" type="submit" disabled={running}>
                {running ? "Running…" : "Run through kernel"}
              </button>
            </form>
          ) : null}
        </div>
      )}
      {receipt && (
        <InvocationReceipt receipt={receipt.result} verb={receipt.verb} />
      )}
      <FinalizationReceipt
        state={finalization}
        canCheck={Boolean(
          pendingInvocation
          && !pendingInvocation.invalidated
          && selected
          && capabilityKey(selected) === pendingInvocation.verbKey,
        )}
        running={running}
        onCheck={() => void finalizePending()}
      />
      {retryRequest && (
        <section className="settings-card invocation-retry">
          <div>
            <strong>Ambiguous transport result</strong>
            <p>
              Retry the exact same noun, verb and typed parameters with the same kernel
              idempotency key. Editing the form starts a different attempt.
            </p>
          </div>
          <button
            className="secondary-button"
            disabled={running}
            onClick={() => void sendRequest(
              retryRequest.request,
              retryRequest.verb,
            )}
          >
            Retry same invocation
          </button>
        </section>
      )}
    </section>
  );
}
