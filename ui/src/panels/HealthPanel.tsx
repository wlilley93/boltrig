import { api } from "@/api/client";
import type { ReadinessCheck } from "@/api/types";
import { useFetch } from "@/useFetch";
import { FetchError, PageIntro } from "./ux";

function humanName(value: string): string {
  return value.replace(/_/g, " ").replace(/\b\w/g, (letter: string) => letter.toUpperCase());
}

function CheckRow({ name, check }: { name: string; check: ReadinessCheck }) {
  const ok = check.status === "ok";
  const disabled = check.status === "disabled";
  return (
    <div className="health-row">
      <span className={`health-row__status ${ok ? "is-ok" : disabled ? "is-idle" : "is-down"}`} aria-hidden="true" />
      <span className="health-row__name">
        <strong>{humanName(name)}</strong>
        <span>{check.reason ? humanName(check.reason) : check.required ? "Required" : "Optional"}</span>
      </span>
      <span className="health-row__value">{humanName(check.status)}</span>
    </div>
  );
}

export function HealthPanel() {
  const readiness = useFetch(() => api.readiness(), [], 15000);
  const liveness = useFetch(() => api.health(), [], 30000);
  const checks = Object.entries(readiness.data?.checks ?? {});
  const ready = readiness.data?.status === "ready";

  function refresh() {
    readiness.reload();
    liveness.reload();
  }

  return (
    <section className="panel health-panel">
      <PageIntro
        title="Health"
        lead="Live kernel liveness and fail-closed readiness for the dependencies this deployment requires."
        how="The public probes expose only coarse status and reason codes; credentials and raw dependency output never appear here."
        actions={<button className="btn" onClick={refresh}>Refresh</button>}
      />

      <div className={`health-hero ${ready ? "is-ready" : "is-attention"}`}>
        <span className="health-hero__mark" aria-hidden="true">{ready ? "✓" : "!"}</span>
        <div>
          <strong>{ready ? "Ready for traffic" : "Not ready for traffic"}</strong>
          <span>
            Kernel {liveness.data?.status === "ok" ? "is live" : "liveness is unknown"}; required dependency checks {ready ? "pass" : "need attention"}.
          </span>
        </div>
      </div>

      <FetchError error={readiness.error} status={readiness.errorStatus} onRetry={readiness.reload} />
      {readiness.loading && !readiness.data && <p className="muted">Checking deployment readiness...</p>}
      {checks.length > 0 && (
        <div className="health-list" aria-label="Readiness checks">
          {checks.map(([name, check]) => <CheckRow key={name} name={name} check={check} />)}
        </div>
      )}
    </section>
  );
}
