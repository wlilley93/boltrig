import { useEffect, useState } from "react";
import type {
  AuditVerifyResponse,
  AuditRow,
  BirthProfileObservation,
  BirthProfileResponse,
  BudgetItem,
  BudgetPolicyRequest,
  ConsoleModelTelemetry,
  ConsoleOverviewResponse,
  GovernedRouteResponse,
  PlatformStatusResponse,
  ReadinessResponse,
  StatusAck,
} from "@wlilley93/boltrig-web-sdk";

import { client } from "../client";
import type { WorkerRoute } from "../routes";
import { BackupStatusCard } from "./BackupStatusCard";
import {
  ExactApprovalFinalizer,
  governedResultReason,
  useExactApprovalFinalizer,
} from "./ExactApprovalFinalizer";
import { Topbar, Unavailable } from "./Shell";

type BudgetMutation =
  | {
    kind: "upsert";
    scopeType: BudgetPolicyRequest["scope_type"];
    scopeId: string;
    body: Omit<BudgetPolicyRequest, "scope_type" | "scope_id">;
    success: string;
  }
  | {
    kind: "reset";
    scopeType: BudgetPolicyRequest["scope_type"];
    scopeId: string;
    window: BudgetPolicyRequest["window"];
    success: string;
  };

export function HomeView({ onRoute }: { onRoute(route: WorkerRoute): void }) {
  const [overview, setOverview] = useState<ConsoleOverviewResponse | null>(null);
  const [error, setError] = useState("");

  function refresh() {
    setError("");
    void client.consoleOverview(12)
      .then(setOverview)
      .catch(() => setError("The operational overview is unavailable."));
  }

  useEffect(refresh, []);

  return (
    <div className="page">
      <Topbar
        title="Home"
        status={overview ? `${overview.counts.pending_approvals} need you` : "Loading"}
      />
      <div className="page-content">
        <div className="page-intro">
          <div>
            <h2>What needs attention?</h2>
            <p>One scope-filtered view of active work, approvals, spend and runtime posture.</p>
          </div>
          <button className="primary-button" onClick={() => onRoute("chat")}>Start a task</button>
        </div>
        {error && <p className="notice">{error}</p>}
        {!overview && !error ? <Unavailable title="Loading your workspace">Reading the governed console projection.</Unavailable> : overview && (
          <>
            <div className="pulse-grid">
              <Pulse
                label="Needs you"
                value={overview.counts.pending_approvals}
                detail="pending approvals"
                onClick={() => onRoute("inbox")}
              />
              <Pulse
                label="Recent work"
                value={overview.counts.recent_runs}
                detail="visible runs"
                onClick={() => onRoute("runs")}
              />
              <Pulse
                label="Spend in view"
                value={formatMoney(overview.cost.total_cost_micros)}
                detail="scope-filtered"
                onClick={() => onRoute("operate")}
              />
              <Pulse
                label="Runtime posture"
                value={attentionCount(overview)}
                detail="components need attention"
                onClick={() => onRoute("operate")}
              />
            </div>
            <div className="home-columns">
              <section className="settings-card">
                <div className="section-heading"><div><p className="eyebrow">Recent runs</p><h2>Work in motion</h2></div><button className="secondary-button" onClick={() => onRoute("runs")}>All runs</button></div>
                {overview.recent_runs.length === 0 ? <p className="muted">No runs in your current scope.</p> : overview.recent_runs.slice(0, 7).map((run) => (
                  <div className="compact-row" key={`${run.seq}-${run.run_id}`}>
                    <span className={`activity-dot ${statusClass(run.status)}`} />
                    <span><strong>{run.verb}</strong><small>{run.actor} · {formatDate(run.ts)}</small></span>
                    <span className="row-meta">{run.status}</span>
                  </div>
                ))}
              </section>
              <section className="settings-card">
                <div className="section-heading"><div><p className="eyebrow">Agent stack</p><h2>Current posture</h2></div><button className="secondary-button" onClick={refresh}>Refresh</button></div>
                {[...overview.platform.components, ...overview.platform.runtimes].slice(0, 8).map((item) => (
                  <div className="compact-row" key={`${item.kind}-${item.id}`}>
                    <span className={`activity-dot ${statusClass(item.status)}`} />
                    <span><strong>{item.id}</strong><small>{item.kind}{item.message ? ` · ${item.message}` : ""}</small></span>
                    <span className="row-meta">{item.status}</span>
                  </div>
                ))}
              </section>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function Pulse(props: {
  label: string;
  value: number | string;
  detail: string;
  onClick(): void;
}) {
  return (
    <button className="pulse-card" onClick={props.onClick}>
      <span>{props.label}</span>
      <strong>{props.value}</strong>
      <small>{props.detail}</small>
    </button>
  );
}

export function OperateView() {
  const [tab, setTab] = useState<"posture" | "audit" | "budgets">("posture");
  return (
    <div className="page">
      <Topbar title="Operate" status="Scope filtered" />
      <div className="page-content">
        <div className="page-intro">
          <div><h2>Run Boltrig with evidence</h2><p>Readiness, runtimes, audit integrity, spend and budget controls from the canonical kernel.</p></div>
        </div>
        <nav className="tabs" aria-label="Operate sections">
          {(["posture", "audit", "budgets"] as const).map((item) => (
            <button className={tab === item ? "active" : ""} aria-current={tab === item ? "page" : undefined} onClick={() => setTab(item)} key={item}>
              {item[0].toUpperCase() + item.slice(1)}
            </button>
          ))}
        </nav>
        {tab === "posture" && <Posture />}
        {tab === "audit" && <Audit />}
        {tab === "budgets" && <Budgets />}
      </div>
    </div>
  );
}

function Posture() {
  const [readiness, setReadiness] = useState<ReadinessResponse | null>(null);
  const [platform, setPlatform] = useState<PlatformStatusResponse | null>(null);
  const [birthProfile, setBirthProfile] = useState<BirthProfileResponse | null>(null);
  const [models, setModels] = useState<ConsoleModelTelemetry[]>([]);
  const [sourceState, setSourceState] = useState({
    readiness: "loading",
    platform: "loading",
    birthProfile: "loading",
    models: "loading",
  });

  function refresh() {
    void Promise.allSettled([
      client.readiness(),
      client.platformStatus(),
      // Keep this evidence source independently failure-contained.  Older
      // embedded SDKs and a single failed request must not take readiness,
      // platform posture or model receipts down with it.
      Promise.resolve().then(() => client.birthProfile()),
      client.modelTelemetry(20),
    ]).then(([ready, status, profile, telemetry]) => {
      if (ready.status === "fulfilled") setReadiness(ready.value);
      if (status.status === "fulfilled") setPlatform(status.value);
      if (profile.status === "fulfilled") setBirthProfile(profile.value);
      if (telemetry.status === "fulfilled") setModels(telemetry.value.models);
      setSourceState({
        readiness: ready.status === "fulfilled" ? "ready" : "unavailable",
        platform: status.status === "fulfilled" ? "ready" : "unavailable",
        birthProfile: profile.status === "fulfilled" ? "ready" : "unavailable",
        models: telemetry.status === "fulfilled" ? "ready" : "unavailable",
      });
    });
  }
  useEffect(refresh, []);

  const checks = Object.entries(readiness?.checks ?? {});
  const items = [...(platform?.components ?? []), ...(platform?.runtimes ?? [])];
  const postureTitle = sourceState.readiness === "loading" && !readiness
    ? "Loading runtime posture"
    : sourceState.readiness === "unavailable" && !readiness
      ? "Readiness unavailable"
      : readiness?.status === "ready"
        ? "Ready for traffic"
        : "Not ready or unknown";
  return (
    <div className="operate-stack">
      <section className={`posture-hero ${readiness?.status === "ready" ? "ok" : "attention"}`}>
        <div><p className="eyebrow">Traffic readiness</p><h2>{postureTitle}</h2></div>
        <button className="secondary-button" onClick={refresh}>Refresh</button>
      </section>
      {sourceState.readiness === "unavailable" && (
        <p className="notice" role="status">
          Readiness could not be {readiness ? "refreshed; showing the last result." : "reached."}
        </p>
      )}
      {sourceState.platform === "unavailable" && (
        <p className="notice" role="status">
          Component posture could not be {platform ? "refreshed; showing the last result." : "reached."}
        </p>
      )}
      {sourceState.models === "unavailable" && (
        <p className="notice" role="status">
          Model receipts could not be refreshed{models.length > 0 ? "; showing the last result." : "."}
        </p>
      )}
      {sourceState.birthProfile === "unavailable" && (
        <p className="notice" role="status">
          Process startup receipts could not be {birthProfile
            ? "refreshed; showing the last result."
            : "reached."}
        </p>
      )}
      <div className="home-columns">
        <section className="settings-card">
          <p className="eyebrow">Required checks</p>
          {sourceState.readiness === "loading" && !readiness ? (
            <p className="muted">Loading readiness checks…</p>
          ) : sourceState.readiness === "unavailable" && !readiness ? (
            <p className="muted">Readiness checks are unavailable.</p>
          ) : checks.length === 0 ? <p className="muted">No readiness detail returned.</p> : checks.map(([name, check]) => (
            <div className="compact-row" key={name}>
              <span className={`activity-dot ${statusClass(check.status)}`} />
              <span><strong>{human(name)}</strong><small>{check.reason ? human(check.reason) : check.required ? "Required" : "Optional"}</small></span>
              <span className="row-meta">{check.status}</span>
            </div>
          ))}
        </section>
        <section className="settings-card">
          <p className="eyebrow">Components and runtimes</p>
          {sourceState.platform === "loading" && !platform ? (
            <p className="muted">Loading component posture…</p>
          ) : sourceState.platform === "unavailable" && !platform ? (
            <p className="muted">Component posture is unavailable.</p>
          ) : items.length === 0 ? <p className="muted">No platform components reported.</p> : items.map((item) => (
            <div className="compact-row" key={`${item.kind}-${item.id}`}>
              <span className={`activity-dot ${statusClass(item.status)}`} />
              <span><strong>{item.id}</strong><small>{item.kind}{item.message ? ` · ${item.message}` : ""}</small></span>
              <span className="row-meta">{item.status}</span>
            </div>
          ))}
        </section>
      </div>
      <section className="settings-card" aria-label="Maintenance attempt evidence">
        <p className="eyebrow">Background maintenance</p>
        <h2>Last observed attempts</h2>
        <p className="muted">
          These are bounded receipts from opaque fleet-process instances. They
          show completed attempts for this organisation; they are not heartbeats
          and do not prove current liveness or complete replica coverage.
        </p>
        {sourceState.platform === "loading" && !platform ? (
          <p className="muted">Loading maintenance attempt evidence…</p>
        ) : sourceState.platform === "unavailable" && !platform ? (
          <p className="muted">
            Maintenance attempt evidence is unavailable; no health conclusion was inferred.
          </p>
        ) : platform?.background_job_evidence?.status === "unavailable" ? (
          <p className="muted">
            Maintenance attempt evidence could not be read; no health conclusion was inferred.
          </p>
        ) : (platform?.background_jobs ?? []).length === 0 ? (
          <p className="muted">
            No maintenance attempt receipts have been observed for this organisation.
          </p>
        ) : (platform?.background_jobs ?? []).map((job) => (
          <div
            className="compact-row"
            key={`${job.job_name}-${job.process_instance_identity}`}
          >
            <span className={`activity-dot ${backgroundJobStatusClass(job.state)}`} />
            <span>
              <strong>
                {backgroundJobLabel(job.job_name)} · process{" "}
                {job.process_instance_identity.slice(0, 12)}
              </strong>
              <small>
                {human(job.state)} · attempted {formatDate(job.last_attempt_at)}
                {" · "}{formatLag(job.lag_seconds)} ago
              </small>
            </span>
            <span className="row-meta">
              {job.last_outcome === "succeeded"
                ? `${job.last_item_count} affected`
                : "Attempt failed"}
            </span>
          </div>
        ))}
      </section>
      <PasswordResetDeliveryCard
        delivery={platform?.password_reset_delivery}
        loading={sourceState.platform === "loading" && !platform}
        unavailable={sourceState.platform === "unavailable" && !platform}
      />
      <BackupStatusCard />
      <MemoryProjectionDeliveryCard
        delivery={platform?.memory_projection_delivery}
        loading={sourceState.platform === "loading" && !platform}
        unavailable={sourceState.platform === "unavailable" && !platform}
      />
      <section className="settings-card" aria-label="Effective network and egress coverage">
        <p className="eyebrow">Network policy</p>
        <h2>Effective egress coverage</h2>
        <p className="muted">
          The manifest network policy governs web.fetch only. This is a
          process-start snapshot, not a universal egress firewall; browser, MCP,
          other adapters and model transports keep the separate boundaries shown below.
        </p>
        {sourceState.platform === "loading" && !platform ? (
          <p className="muted">Loading effective network policy…</p>
        ) : sourceState.platform === "unavailable" && !platform ? (
          <p className="muted">
            Effective network policy is unavailable; no coverage was inferred.
          </p>
        ) : platform?.network_policy?.status !== "available"
          || !platform.network_policy.web_fetch ? (
          <p className="muted">
            The live web.fetch policy snapshot is unavailable; no enforcement
            state was inferred.
          </p>
        ) : (
          <>
            {Object.entries(platform.network_policy.web_fetch.fields).map(
              ([name, field]) => (
                <div className="compact-row" key={name}>
                  <span className="activity-dot ok" />
                  <span>
                    <strong>web.fetch · {networkPolicyFieldLabel(name)}</strong>
                    <small>{networkPolicyFieldDetail(field)}</small>
                  </span>
                  <span className="row-meta">{field.enforcement}</span>
                </div>
              ),
            )}
            <div className="compact-row">
              <span className="activity-dot ok" />
              <span>
                <strong>web.fetch · DNS pinning</strong>
                <small>
                  {human(platform.network_policy.web_fetch.controls.dns_pinning)}
                </small>
              </span>
              <span className="row-meta">enforced path</span>
            </div>
            {platform.network_policy.coverage.map((item) => (
              <div className="compact-row" key={item.surface}>
                <span className="activity-dot paused" />
                <span>
                  <strong>{networkPolicySurfaceLabel(item.surface)}</strong>
                  <small>
                    {human(item.limitation)} · controls:{" "}
                    {item.controls.map(human).join(", ")}
                  </small>
                </span>
                <span className="row-meta">{human(item.status)}</span>
              </div>
            ))}
          </>
        )}
        <p className="muted">
          Proxy addresses, CA paths and contents, domain rules and provider
          endpoints are never returned here. Change manifest-owned values at
          deployment and restart the relevant process for them to take effect.
        </p>
      </section>
      <section className="settings-card" aria-label="Authentication trust policy">
        <p className="eyebrow">Authentication</p>
        <h2>Effective trust mode</h2>
        <p className="muted">
          Trust endpoints and audiences remain redacted. When generic OIDC is
          selected, a partial manifest trio or drift from simultaneously
          configured process trust refuses boot; changes require a process restart.
        </p>
        {sourceState.platform === "loading" && !platform ? (
          <p className="muted">Loading authentication trust evidence…</p>
        ) : platform?.identity_policy?.status !== "available" ? (
          <p className="muted">
            Authentication policy evidence is unavailable; no mode is inferred.
          </p>
        ) : (
          <>
            <div className="compact-row">
              <span className={`activity-dot ${
                platform.identity_policy.mode === "deny_all" ? "paused" : "ok"
              }`} />
              <span>
                <strong>{human(platform.identity_policy.mode)}</strong>
                <small>Effective process-start authentication resolver</small>
              </span>
              <span className="row-meta">restart-bound</span>
            </div>
            <div className="compact-row">
              <span className={`activity-dot ${
                platform.identity_policy.oidc.serving_state.startsWith("active")
                  ? "ok"
                  : "paused"
              }`} />
              <span>
                <strong>Manifest OIDC trust</strong>
                <small>
                  {human(platform.identity_policy.oidc.serving_state)}
                  {" · "}{human(platform.identity_policy.oidc.manifest_trio_state)} trio
                </small>
              </span>
              <span className="row-meta">exact-match drift guard</span>
            </div>
          </>
        )}
      </section>
      <section className="settings-card" aria-label="Langfuse delivery evidence">
        <p className="eyebrow">Trace mirror</p>
        <h2>Langfuse delivery attempts</h2>
        <p className="muted">
          These are content-free counters from this API process&apos;s spawner.
          They do not prove sink health, delivery lag or complete fleet/Hatchet
          replica coverage; the kernel audit remains the compliance record.
        </p>
        {sourceState.platform === "loading" && !platform ? (
          <p className="muted">Loading trace-mirror evidence…</p>
        ) : platform?.langfuse_delivery?.status !== "available" ? (
          <p className="muted">
            Langfuse attempt evidence is unavailable; no delivery state is inferred.
          </p>
        ) : (
          <>
            <div className="compact-row">
              <span className={`activity-dot ${
                platform.langfuse_delivery.sink_state === "enabled" ? "ok" : "paused"
              }`} />
              <span>
                <strong>
                  Sink {human(platform.langfuse_delivery.sink_state)}
                </strong>
                <small>{human(platform.langfuse_delivery.reason)}</small>
              </span>
              <span className="row-meta">
                {platform.langfuse_delivery.attempt_count} attempts
              </span>
            </div>
            <div className="compact-row">
              <span className={`activity-dot ${
                platform.langfuse_delivery.failure_count > 0 ? "paused" : "ok"
              }`} />
              <span>
                <strong>Process-local outcomes</strong>
                <small>
                  Last success{" "}
                  {platform.langfuse_delivery.last_success_at
                    ? formatDate(platform.langfuse_delivery.last_success_at)
                    : "not observed"}
                  {" · "}last failure{" "}
                  {platform.langfuse_delivery.last_failure_at
                    ? formatDate(platform.langfuse_delivery.last_failure_at)
                    : "not observed"}
                </small>
              </span>
              <span className="row-meta">
                {platform.langfuse_delivery.success_count} sent ·{" "}
                {platform.langfuse_delivery.failure_count} failed
              </span>
            </div>
          </>
        )}
      </section>
      <section className="settings-card" aria-label="Codex rollout and admission evidence">
        <p className="eyebrow">Codex runtime</p>
        <h2>Rollout and admission wall</h2>
        <p className="muted">
          This is process-composition evidence, not cell liveness. Reading it
          does not admit a cell or alter execution.
        </p>
        {sourceState.platform === "loading" && !platform ? (
          <p className="muted">Loading Codex admission evidence…</p>
        ) : platform?.codex_admission?.status !== "available" ? (
          <p className="muted">
            Codex admission evidence is unavailable; no readiness is inferred.
          </p>
        ) : (
          <>
            <div className="compact-row">
              <span className="activity-dot paused" />
              <span>
                <strong>Rollout mode · OFF</strong>
                <small>
                  Root execution remains legacy-only; assignment admission is
                  inactive and canary selection is unavailable.
                </small>
              </span>
              <span className="row-meta">
                {platform.codex_admission.rollout.generation === null
                  ? "scaffold not composed"
                  : `generation ${platform.codex_admission.rollout.generation}`}
              </span>
            </div>
            <div className="compact-row">
              <span className="activity-dot paused" />
              <span>
                <strong>Native production activation refused</strong>
                <small>
                  Runtime config and runtime class remain production-unready
                  while isolation controls are unresolved.
                </small>
              </span>
              <span className="row-meta">
                {human(platform.codex_admission.runtime.trusted_provider)}
              </span>
            </div>
            <div className="compact-row">
              <span className="activity-dot paused" />
              <span>
                <strong>Cell evidence unavailable</strong>
                <small>
                  No durable per-cell preflight receipts or liveness evidence
                  are projected.
                </small>
              </span>
              <span className="row-meta">no canary decision</span>
            </div>
          </>
        )}
      </section>
      <section className="settings-card">
        <p className="eyebrow">Process startup composition</p>
        <h2>Birth-profile comparison</h2>
        <p className="muted">
          Retained API, fleet and Hatchet startup receipts are compared with the
          latest API startup receipt. That receipt is a reference, not desired state.
          These snapshots do not prove replica coverage or process liveness.
        </p>
        {sourceState.birthProfile === "loading" && !birthProfile ? (
          <p className="muted">Loading process startup receipts…</p>
        ) : sourceState.birthProfile === "unavailable" && !birthProfile ? (
          <p className="muted">
            Process startup receipts are unavailable; no composition match is inferred.
          </p>
        ) : birthProfile?.observations.map((observation, index) => (
          <div
            className="compact-row"
            key={`${observation.process_kind}-${observation.instance_identity ?? `missing-${index}`}`}
          >
            <span className={`activity-dot ${birthProfileStatusClass(observation)}`} />
            <span>
              <strong>{birthProfileProcessLabel(observation.process_kind)}</strong>
              <small>
                {birthProfileEvidenceLabel(observation)}
                {observation.expires_at ? ` · expires ${formatDate(observation.expires_at)}` : ""}
              </small>
            </span>
            <span className="row-meta">
              {observation.mismatches.length > 0
                ? observation.mismatches.map(human).join(", ")
                : observation.instance_identity?.slice(0, 11) ?? "No receipt"}
            </span>
          </div>
        ))}
        {birthProfile && (
          <p className="muted">
            {birthProfile.summary.retained_instance_count} retained boot{" "}
            {birthProfile.summary.retained_instance_count === 1 ? "receipt" : "receipts"};
            at most {birthProfile.summary.max_retained_instances_per_process} newest
            receipts per process kind are retained. Liveness and complete replica
            inventory remain unknown.
          </p>
        )}
      </section>
      <section className="settings-card">
        <p className="eyebrow">Model and runtime receipts</p>
        <h2>What has actually run</h2>
        {sourceState.models === "loading" ? (
          <p className="muted">Loading model receipts…</p>
        ) : sourceState.models === "unavailable" && models.length === 0 ? (
          <p className="muted">Model receipts are unavailable; no absence is inferred.</p>
        ) : models.length === 0 ? <p className="muted">No model invocations are visible in the current scope. This is not evidence that a runtime is production-ready.</p> : models.map((model) => (
          <div className="compact-row" key={`${model.provider}-${model.model}-${model.runtime}-${model.profile ?? ""}`}>
            <span className={`activity-dot ${Object.keys(model.statuses).some((status) => ["error", "failed"].includes(status)) ? "paused" : "ok"}`} />
            <span><strong>{model.model}</strong><small>{model.provider} · {model.runtime}{model.profile ? ` · ${model.profile}` : ""} · last {formatDate(model.last_seen)}</small></span>
            <span className="row-meta">{model.calls} calls · {model.tokens.toLocaleString()} tokens · {formatMoney(model.cost_micros)}</span>
          </div>
        ))}
      </section>
    </div>
  );
}

function Audit() {
  const [actor, setActor] = useState("");
  const [verb, setVerb] = useState("");
  const [run, setRun] = useState("");
  const [resource, setResource] = useState("");
  const [status, setStatus] = useState("");
  const [since, setSince] = useState("");
  const [until, setUntil] = useState("");
  const [eventType, setEventType] = useState("");
  const [security, setSecurity] = useState(false);
  const [rows, setRows] = useState<AuditRow[]>([]);
  const [offset, setOffset] = useState(0);
  const [nextOffset, setNextOffset] = useState<number | null>(null);
  const [integrity, setIntegrity] = useState<AuditVerifyResponse | null>(null);
  const [integrityState, setIntegrityState] = useState<
    "idle" | "loading" | "ready" | "unavailable"
  >("idle");
  const [message, setMessage] = useState("");

  async function search(event?: React.FormEvent, pageOffset = 0) {
    event?.preventDefault();
    setMessage("");
    try {
      const result = await client.auditSearch({
        actor: actor.trim() || undefined,
        verb: verb.trim() || undefined,
        run: run.trim() || undefined,
        resource: resource.trim() || undefined,
        status: status.trim() || undefined,
        since: since || undefined,
        until: until || undefined,
        security,
        eventType: eventType.trim() || undefined,
        limit: 100,
        offset: pageOffset,
      });
      setRows(result.results);
      setOffset(result.offset ?? pageOffset);
      setNextOffset(result.next_offset ?? null);
    } catch {
      setMessage("Audit search is unavailable for this identity.");
    }
  }

  async function verify() {
    setIntegrityState("loading");
    try {
      const result = await client.auditVerify();
      setIntegrity(result);
      setIntegrityState("ready");
    } catch {
      setIntegrity(null);
      setIntegrityState("unavailable");
    }
  }

  async function exportAudit() {
    const result = await client.auditExport();
    if (!result.events) {
      setMessage(result.error ?? "Audit export is restricted.");
      return;
    }
    const url = URL.createObjectURL(new Blob([JSON.stringify(result, null, 2)], { type: "application/json" }));
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "boltrig-audit.json";
    anchor.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="operate-stack">
      <form className="audit-controls" onSubmit={(event) => void search(event)}>
        <input className="field-control" aria-label="Audit actor" placeholder="Actor" value={actor} onChange={(event) => setActor(event.target.value)} />
        {security ? (
          <input className="field-control" aria-label="Security event type" placeholder="Event type" value={eventType} onChange={(event) => setEventType(event.target.value)} />
        ) : (
          <>
            <input className="field-control" aria-label="Audit verb" placeholder="Exact verb" value={verb} onChange={(event) => setVerb(event.target.value)} />
            <input className="field-control" aria-label="Audit status" placeholder="Exact status" value={status} onChange={(event) => setStatus(event.target.value)} />
            <input className="field-control" aria-label="Audit run" placeholder="Run ID" value={run} onChange={(event) => setRun(event.target.value)} />
          </>
        )}
        <input className="field-control" aria-label="Audit resource" placeholder="Exact resource" value={resource} onChange={(event) => setResource(event.target.value)} />
        <label><span className="muted small">Since</span><input className="field-control" aria-label="Audit since" type="date" value={since} onChange={(event) => setSince(event.target.value)} /></label>
        <label><span className="muted small">Until</span><input className="field-control" aria-label="Audit until" type="date" value={until} onChange={(event) => setUntil(event.target.value)} /></label>
        <label className="check-label"><input type="checkbox" checked={security} onChange={(event) => setSecurity(event.target.checked)} /> Security stream (author/admin)</label>
        <button className="primary-button">Search</button>
      </form>
      <div className="inline-actions">
        <span className="status-pill"><i />Integrity: {integrityLabel(integrity, integrityState)}</span>
        <button className="secondary-button" disabled={integrityState === "loading"} onClick={() => void verify()}>
          {integrityState === "loading" ? "Verifying…" : "Verify chains"}
        </button>
        <button className="secondary-button" onClick={() => void exportAudit()}>Export JSON</button>
      </div>
      {integrityState === "ready" && integrity && integrity.status !== "denied" && (
        <section className="settings-card audit-anchor-evidence" aria-label="Audit anchor evidence">
          <div className="section-heading">
            <div>
              <p className="eyebrow">Tamper evidence</p>
              <h2>{integrity.anchor ? "Latest audit anchor" : "No anchor written yet"}</h2>
            </div>
            <span className={`status-pill ${integrity.intact === true ? "" : "warn"}`}>
              <i />{integrity.intact === true ? "Chains verify" : "Attention required"}
            </span>
          </div>
          {integrity.anchor ? (
            <>
              <dl className="fact-grid">
                <div><dt>Sequence range</dt><dd>{integrity.anchor.seq_start}–{integrity.anchor.seq_end}</dd></div>
                <div><dt>Anchored</dt><dd>{formatDate(integrity.anchor.anchored_at)}</dd></div>
                <div><dt>Evidence kind</dt><dd>{integrity.anchor.is_dev_fallback ? "Local development fallback" : "External signing evidence"}</dd></div>
                <div><dt>Anchor ID</dt><dd>{integrity.anchor.id}</dd></div>
              </dl>
              {integrity.anchor.is_dev_fallback && (
                <p className="notice">The chain is internally consistent, but this anchor is the local development fallback—not independent timestamp or KMS evidence.</p>
              )}
            </>
          ) : (
            <p className="notice">The hash chains were checked, but no rollup anchor exists yet. Integrity is not being presented as independently anchored.</p>
          )}
        </section>
      )}
      {integrityState === "ready" && integrity && integrity.status === "denied" && (
        <p className="notice">Audit integrity evidence is restricted to author and administrator roles.</p>
      )}
      {integrityState === "unavailable" && (
        <p className="notice">Audit integrity verification is unavailable; no conclusion was inferred.</p>
      )}
      {message && <p className="notice">{message}</p>}
      <section className="data-list" aria-label="Audit results">
        {rows.length === 0 ? <Unavailable title="No audit rows in view">Search the scoped audit or security stream.</Unavailable> : rows.map((row) => (
          <details className="data-row static" key={`${row.seq}-${row.ts}`}>
            <summary className="data-row-summary">
            <span className={`activity-dot ${statusClass(row.status ?? row.event_type ?? "")}`} />
            <span className="data-row-copy"><strong>{row.verb ?? row.event_type ?? "event"}</strong><small>{row.actor} · {formatDate(row.ts)}{row.run_id ? ` · ${row.run_id}` : ""}</small></span>
            <span className="row-meta">{row.status ?? row.reason ?? "recorded"}</span>
            </summary>
            <dl className="fact-grid audit-detail">
              <div><dt>Sequence</dt><dd>{row.seq}</dd></div>
              <div><dt>Workspace</dt><dd>{row.workspace_id ?? "organisation-wide"}</dd></div>
              <div><dt>Resource</dt><dd>{row.resource ? `${row.resource}${row.resource_id ? ` · ${row.resource_id}` : ""}` : "—"}</dd></div>
              <div><dt>Network</dt><dd>{row.ip_address ?? "not recorded"}</dd></div>
              <div><dt>User agent</dt><dd>{row.user_agent ?? "not recorded"}</dd></div>
              <div><dt>Reason</dt><dd>{row.reason ?? "—"}</dd></div>
            </dl>
          </details>
        ))}
      </section>
      <div className="button-row" aria-label="Audit result pages">
        <button className="secondary-button" disabled={offset === 0}
          onClick={() => void search(undefined, Math.max(0, offset - 100))}>Newer</button>
        <button className="secondary-button" disabled={nextOffset === null}
          onClick={() => void search(undefined, nextOffset ?? offset)}>Older</button>
      </div>
    </div>
  );
}

function integrityLabel(
  integrity: AuditVerifyResponse | null,
  state: "idle" | "loading" | "ready" | "unavailable",
): string {
  if (state === "idle") return "Not checked";
  if (state === "loading") return "Checking…";
  if (state === "unavailable") return "Unavailable";
  if (integrity?.status === "denied") return "Restricted";
  if (integrity?.intact !== true) return "Attention";
  if (!integrity.anchor) return "Intact · unanchored";
  return integrity.anchor.is_dev_fallback
    ? "Intact · local fallback"
    : "Intact · externally anchored";
}

function Budgets() {
  const [items, setItems] = useState<BudgetItem[]>([]);
  const [scopeType, setScopeType] = useState<"tenant" | "department">("tenant");
  const [scopeId, setScopeId] = useState("default");
  const [window, setWindow] = useState<"run" | "daily" | "monthly">("monthly");
  const [tokens, setTokens] = useState("");
  const [cost, setCost] = useState("");
  const [hardStop, setHardStop] = useState(true);
  const [message, setMessage] = useState("");

  const finalizer = useExactApprovalFinalizer<
    BudgetMutation,
    GovernedRouteResponse<StatusAck>
  >({
    isCurrent: (input) => {
      if (input.kind === "reset") {
        return items.some((item) => (
          item.scope_type === input.scopeType
          && item.id === input.scopeId
          && item.window === input.window
        ));
      }
      return routeInputEquals(input, budgetDraft({
        scopeType,
        scopeId,
        window,
        tokens,
        cost,
        hardStop,
      }));
    },
    replay: (input, approvalId) => (
      input.kind === "reset"
        ? client.resetBudget(
          input.scopeType, input.scopeId, input.window, approvalId,
        )
        : client.upsertBudget(
          input.scopeType, input.scopeId, input.body, approvalId,
        )
    ),
    onApplied: async (_result, input) => {
      setMessage(input.success);
      refresh();
    },
    onRefused: (result) => {
      setMessage(governedResultReason(
        result, "The approved budget change was refused.",
      ));
    },
  });

  function refresh() {
    finalizer.invalidate();
    void client.budgets().then((result) => setItems(result.budgets)).catch(() => setMessage("Budgets are unavailable."));
  }
  useEffect(refresh, []);

  async function save(event: React.FormEvent) {
    event.preventDefault();
    const input = budgetDraft({
      scopeType,
      scopeId,
      window,
      tokens,
      cost,
      hardStop,
    });
    const result = await client.upsertBudget(
      input.scopeType, input.scopeId, input.body,
    );
    if (finalizer.begin(input, result, "Budget policy change")) {
      setMessage("Budget change is waiting for approval in Inbox.");
      return;
    }
    setMessage(result.status === "ok"
      ? input.success
      : governedResultReason(result, result.status ?? "Budget change refused."));
    if (result.status === "ok") refresh();
  }

  async function reset(item: BudgetItem) {
    const input: BudgetMutation = {
      kind: "reset",
      scopeType: item.scope_type,
      scopeId: item.id,
      window: item.window,
      success: "Budget usage reset.",
    };
    const result = await client.resetBudget(
      input.scopeType, input.scopeId, input.window,
    );
    if (finalizer.begin(input, result, "Budget usage reset")) {
      setMessage("Usage reset is waiting for approval in Inbox.");
      return;
    }
    setMessage(result.status === "ok"
      ? input.success
      : governedResultReason(result, result.status ?? "Budget reset refused."));
    if (result.status === "ok") refresh();
  }

  return (
    <div className="home-columns">
      <section className="settings-card">
        <p className="eyebrow">Current policies</p>
        <ExactApprovalFinalizer controller={finalizer} />
        {message && <p className="notice">{message}</p>}
        {items.length === 0 ? <p className="muted">No budget policies in your scope.</p> : items.map((item) => (
          <article className="budget-row" key={`${item.scope_type}-${item.id}-${item.window}`}>
            <div>
              <strong>{item.scope_type} · {item.id}</strong>
              <small>
                {item.window === "run"
                  ? "per run · aggregate usage is not inferred"
                  : `${item.window} UTC window · automatic rollover${
                    item.window_ends_at ? ` ${formatDate(item.window_ends_at)}` : ""
                  }`} · {item.scope_type === "workflow"
                  ? "stored only; not enforced"
                  : item.hard_stop
                    ? "hard stop on spawned agent work"
                    : "alert only on spawned agent work"}
              </small>
            </div>
            <div>
              <span>{item.usage_state === "current"
                ? `${item.spent_tokens.toLocaleString()} / ${item.token_limit?.toLocaleString() ?? "∞"} tokens`
                : `— / ${item.token_limit?.toLocaleString() ?? "∞"} tokens`}</span>
              <span>{item.usage_state === "current"
                ? `${formatMoney(item.spent_micros)} / ${item.cost_limit_micros == null ? "∞" : formatMoney(item.cost_limit_micros)}`
                : `— / ${item.cost_limit_micros == null ? "∞" : formatMoney(item.cost_limit_micros)}`}</span>
            </div>
            {item.window !== "run" && (
              <button className="secondary-button" onClick={() => void reset(item)}>
                Reset current window
              </button>
            )}
          </article>
        ))}
      </section>
      <form className="settings-card budget-form" onSubmit={(event) => void save(event)}>
        <p className="eyebrow">Set policy</p>
        <p className="notice">
          Hard stops currently cover model-backed work entering the fleet spawner. Tenant
          policies cover Chat and other spawned runs; department policies apply when a
          spawn carries that department. Run windows are isolated by the exact run id;
          daily and monthly windows roll automatically at UTC boundaries. Realtime voice
          provider usage, direct adapter calls and workflow-scoped spend are not charged here.
        </p>
        <label><span>Scope type</span><select className="field-control" value={scopeType} onChange={(event) => {
          finalizer.invalidate();
          setScopeType(event.target.value as typeof scopeType);
        }}><option value="tenant">Tenant</option><option value="department">Department</option></select></label>
        <label><span>Scope id</span><input className="field-control" required value={scopeId} onChange={(event) => {
          finalizer.invalidate();
          setScopeId(event.target.value);
        }} /></label>
        <label>
          <span>Automatic window</span>
          <select className="field-control" value={window} onChange={(event) => {
            finalizer.invalidate();
            setWindow(event.target.value as typeof window);
          }}><option value="run">Run</option><option value="daily">Daily</option><option value="monthly">Monthly</option></select>
        </label>
        <label><span>Token limit</span><input className="field-control" type="number" min="0" value={tokens} onChange={(event) => {
          finalizer.invalidate();
          setTokens(event.target.value);
        }} /></label>
        <label><span>Cost limit (USD)</span><input className="field-control" type="number" min="0" step="0.01" value={cost} onChange={(event) => {
          finalizer.invalidate();
          setCost(event.target.value);
        }} /></label>
        <label className="check-label"><input type="checkbox" checked={hardStop} onChange={(event) => {
          finalizer.invalidate();
          setHardStop(event.target.checked);
        }} /> Stop spawned agent work when exhausted</label>
        <button className="primary-button">Save budget</button>
      </form>
    </div>
  );
}

function attentionCount(overview: ConsoleOverviewResponse) {
  return [...overview.platform.components, ...overview.platform.runtimes]
    .filter((item) => item.status !== "ok").length;
}

function budgetDraft({
  scopeType,
  scopeId,
  window,
  tokens,
  cost,
  hardStop,
}: {
  scopeType: BudgetPolicyRequest["scope_type"];
  scopeId: string;
  window: BudgetPolicyRequest["window"];
  tokens: string;
  cost: string;
  hardStop: boolean;
}): Extract<BudgetMutation, { kind: "upsert" }> {
  return {
    kind: "upsert",
    scopeType,
    scopeId: scopeId.trim(),
    body: {
      window,
      hard_stop: hardStop,
      token_limit: tokens ? Number(tokens) : undefined,
      cost_limit_micros: cost
        ? Math.round(Number(cost) * 1_000_000)
        : undefined,
    },
    success: "Budget policy saved.",
  };
}

function routeInputEquals(left: unknown, right: unknown): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}

function formatMoney(micros: number) {
  return new Intl.NumberFormat(undefined, { style: "currency", currency: "USD" }).format(micros / 1_000_000);
}

function statusClass(status: string) {
  if (["ready", "ok", "done", "completed", "active"].includes(status)) return "ok";
  if (["down", "failed", "error", "broken"].includes(status)) return "error";
  if (["not_ready", "degraded", "blocked", "pending_human"].includes(status)) return "paused";
  return status;
}

function human(value: string) {
  return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function formatDate(value: string) {
  const date = new Date(value);
  return Number.isFinite(date.getTime()) ? date.toLocaleString() : value;
}

function backgroundJobLabel(job: "hitl_expiry" | "retention") {
  return job === "hitl_expiry" ? "HITL expiry" : "Conversation retention";
}

function backgroundJobStatusClass(state: string) {
  if (state === "recent_succeeded_evidence") return "ok";
  if (state.includes("failed")) return "error";
  return "paused";
}

function formatLag(seconds: number) {
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h`;
  return `${Math.floor(seconds / 86400)}d`;
}

function MemoryProjectionDeliveryCard({
  delivery,
  loading,
  unavailable,
}: {
  delivery: PlatformStatusResponse["memory_projection_delivery"];
  loading: boolean;
  unavailable: boolean;
}) {
  return (
    <section className="settings-card" aria-label="Memory projection delivery evidence">
      <p className="eyebrow">Memory projections</p>
      <h2>Projection delivery</h2>
      <p className="muted">
        These are bounded, content-free status receipts. They are not queue
        depth or worker-liveness evidence. Pending age is receipt age, not
        engine queue lag.
      </p>
      {loading ? (
        <p className="muted">Loading projection delivery receipts…</p>
      ) : unavailable || delivery?.status === "unavailable" ? (
        <p className="muted">
          Projection delivery receipts are unavailable; no delivery or health
          conclusion was inferred.
        </p>
      ) : !delivery ? (
        <p className="muted">
          This kernel did not return projection delivery evidence.
        </p>
      ) : (
        <>
          <div className="compact-row">
            <span className={`activity-dot ${
              delivery.queue_posture.status === "configured" ? "ok" : "paused"
            }`} />
            <span>
              <strong>{human(delivery.queue_posture.execution_mode)}</strong>
              <small>
                {delivery.queue_posture.configured_projection_count} configured
                {" · "}automatic retry is bounded to one task invocation
                {" · "}enqueue is not retried after ambiguous acceptance
              </small>
            </span>
            <span className="row-meta">
              max {delivery.queue_posture.max_operation_attempts} attempts
            </span>
          </div>
          {delivery.receipts.length === 0 ? (
            <p className="muted">
              No projection delivery receipts have been observed for this organisation.
            </p>
          ) : delivery.receipts.map((receipt) => (
            <div className="compact-row" key={receipt.receipt_identity}>
              <span className={`activity-dot ${
                memoryProjectionStatusClass(receipt.state)
              }`} />
              <span>
                <strong>
                  {human(receipt.operation)} · projection{" "}
                  {receipt.projection_identity.slice(0, 12)}
                </strong>
                <small>
                  {human(receipt.state)} · {memoryProjectionTiming(receipt)}
                </small>
              </span>
              <span className="row-meta">
                {receipt.operation_attempts}/{receipt.max_operation_attempts} attempts
              </span>
            </div>
          ))}
          {delivery.truncated && (
            <p className="muted">
              Showing the newest {delivery.max_returned_receipts} bounded receipts.
            </p>
          )}
        </>
      )}
      <p className="notice">
        Manual retry is unavailable because Boltrig does not retain the original
        projection payload in these receipts. Recover from the canonical memory
        source through a future governed replay contract; this view does not
        create a second write path.
      </p>
    </section>
  );
}

function memoryProjectionStatusClass(state: string) {
  if (state === "delivered" || state === "delivered_after_retry") return "ok";
  if (state.includes("failed") || state.startsWith("terminal_")) return "error";
  return "paused";
}

function memoryProjectionTiming(
  receipt: NonNullable<
    PlatformStatusResponse["memory_projection_delivery"]
  >["receipts"][number],
) {
  if (receipt.pending_age_seconds !== null) {
    return `receipt pending for ${formatLag(receipt.pending_age_seconds)}`;
  }
  if (receipt.queue_wait_seconds !== null) {
    return `first attempt ${formatLag(receipt.queue_wait_seconds)} after receipt`;
  }
  if (receipt.last_attempt_at) {
    return `attempted ${formatDate(receipt.last_attempt_at)}`;
  }
  return "attempt timing unavailable";
}

function PasswordResetDeliveryCard({
  delivery,
  loading,
  unavailable,
}: {
  delivery: PlatformStatusResponse["password_reset_delivery"];
  loading: boolean;
  unavailable: boolean;
}) {
  let detail = "No password-reset delivery posture was returned.";
  if (loading) detail = "Loading notifier posture and bounded attempt evidence…";
  else if (unavailable) {
    detail = "Password-reset delivery posture is unavailable.";
  } else if (delivery?.configuration === "unavailable") {
    detail = "No password-reset notifier is composed in this API process.";
  } else if (delivery?.evidence_status === "restricted") {
    detail = "Delivery-attempt evidence is restricted to authors and administrators.";
  } else if (delivery?.evidence_status === "not_observed_in_bounded_tail") {
    detail = `No attempt was observed in the latest ${delivery.audit_tail_limit} audit rows; this is not proof that no earlier attempt exists.`;
  } else if (delivery?.evidence_status === "available") {
    detail = `${passwordResetOutcomeLabel(delivery.last_outcome)} · ${delivery.last_attempt_at
      ? formatDate(delivery.last_attempt_at)
      : "time unavailable"}`;
  }
  return (
    <section className="settings-card" aria-label="Password reset delivery evidence">
      <p className="eyebrow">Account recovery delivery</p>
      <h2>Password-reset notifier</h2>
      <p>{detail}</p>
      <p className="muted">
        This is bounded notifier-attempt evidence, not a provider receipt or
        proof that a message reached the recipient&apos;s inbox. No recipient,
        address, provider payload or secret is projected.
      </p>
    </section>
  );
}

function passwordResetOutcomeLabel(
  outcome: NonNullable<
    PlatformStatusResponse["password_reset_delivery"]
  >["last_outcome"],
) {
  if (outcome === "accepted_by_notifier") {
    return "Notifier accepted the delivery attempt";
  }
  if (outcome === "notifier_unavailable") return "Notifier was unavailable";
  if (outcome === "not_accepted_by_notifier") {
    return "No notifier acceptance was recorded";
  }
  return "No bounded attempt outcome";
}

function networkPolicyFieldLabel(name: string) {
  if (name === "https_proxy") return "HTTPS proxy";
  if (name === "ca_bundle") return "CA bundle";
  return human(name);
}

function networkPolicyFieldDetail(field: {
  enabled?: boolean;
  configured?: boolean;
  entry_count?: number;
}) {
  if (typeof field.enabled === "boolean") {
    return field.enabled ? "Enabled at process start" : "Disabled at process start";
  }
  const state = field.configured ? "Configured" : "Not configured";
  return typeof field.entry_count === "number"
    ? `${state} · ${field.entry_count} entries`
    : state;
}

function networkPolicySurfaceLabel(surface: string) {
  if (surface === "external_mcp") return "External MCP";
  if (surface === "http_adapters") return "Other HTTP adapters";
  if (surface === "model_providers_and_embeddings") {
    return "Model providers and embeddings";
  }
  return human(surface);
}

function birthProfileProcessLabel(
  processKind: BirthProfileObservation["process_kind"],
) {
  if (processKind === "api") return "API process";
  if (processKind === "fleet") return "Fleet worker";
  return "Hatchet worker";
}

function birthProfileEvidenceLabel(observation: BirthProfileObservation) {
  if (observation.evidence_state === "matched_reference_liveness_unknown") {
    return "Startup profile matches API reference · liveness unknown";
  }
  if (observation.evidence_state === "mismatched_startup_liveness_unknown") {
    return "Startup profile differs from API reference · liveness unknown";
  }
  if (observation.evidence_state === "stale_startup_liveness_unknown") {
    return "Startup receipt is stale · liveness unknown";
  }
  if (observation.evidence_state === "startup_observed_reference_unavailable") {
    return "Startup receipt observed; API reference unavailable";
  }
  return "Startup receipt unavailable";
}

function birthProfileStatusClass(observation: BirthProfileObservation) {
  if (observation.evidence_state === "matched_reference_liveness_unknown") return "ok";
  if (observation.evidence_state === "unavailable") return "error";
  return "paused";
}
