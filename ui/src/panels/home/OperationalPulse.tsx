import type { BudgetItem, ConsolePlatformItem } from "@/api/types";
import { api } from "@/api/client";
import { useSlideActive } from "@/deck/context";
import { navigate } from "@/router";
import { useFetch } from "@/useFetch";

function money(micros: number): string {
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: micros >= 1_000_000 ? 2 : 4,
  }).format(micros / 1_000_000);
}

function healthTone(status: string): "ok" | "warn" | "down" {
  const value = status.toLowerCase();
  if (["ok", "ready", "up", "healthy"].includes(value)) return "ok";
  if (["failed", "down", "error", "not_ready"].includes(value)) return "down";
  return "warn";
}

function PlatformRow({ item }: { item: ConsolePlatformItem }) {
  const tone = healthTone(item.status);
  return (
    <div className="home-ops__platform-row">
      <span className={`home-ops__dot home-ops__dot--${tone}`} aria-hidden="true" />
      <span className="home-ops__platform-name">{item.id}</span>
      <span className="muted">{item.kind}</span>
      <span className={`badge badge--${tone}`}>{item.status}</span>
    </div>
  );
}

function budgetRatio(budget: BudgetItem): number {
  const token = budget.token_limit ? budget.spent_tokens / budget.token_limit : 0;
  const cost = budget.cost_limit_micros ? budget.spent_micros / budget.cost_limit_micros : 0;
  return Math.max(token, cost);
}

function hottestBudget(budgets: BudgetItem[]): { budget: BudgetItem; ratio: number } | null {
  let result: { budget: BudgetItem; ratio: number } | null = null;
  for (const budget of budgets) {
    const ratio = budgetRatio(budget);
    if (!result || ratio > result.ratio) result = { budget, ratio };
  }
  return result;
}

function countProblems(statuses: Record<string, number>, pattern: RegExp): number {
  return Object.entries(statuses).reduce(
    (total, [status, count]) => total + (pattern.test(status) ? count : 0),
    0,
  );
}

export function OperationalPulse() {
  const active = useSlideActive();
  const overview = useFetch(() => api.consoleOverview(20), [], 15000, { paused: !active });
  const data = overview.data;
  const platform = data ? [...data.platform.components, ...data.platform.runtimes] : [];
  const failed = data ? countProblems(data.cost.by_status, /fail|error|denied/) : 0;
  const degraded = data?.cost.by_status.degraded ?? 0;
  const budget = data ? hottestBudget(data.budgets) : null;
  const model = data?.models[0];

  return (
    <section className="list-card home-ops" aria-labelledby="home-ops-title">
      <div className="list-card__head">
        <div>
          <h3 id="home-ops-title">Operational pulse</h3>
          <span className="muted">Live, scoped, and server-reported</span>
        </div>
        <button className="btn" onClick={() => overview.reload()}>Refresh</button>
      </div>
      <div className="list-card__body home-ops__body">
        {overview.loading && !data && <p className="muted">Loading operational posture...</p>}
        {overview.error && <p className="error">Could not load operational posture: {overview.error}</p>}
        {data && (
          <>
            <div className="home-ops__metrics">
              <button className="home-ops__metric" onClick={() => navigate("/insight")}>
                <span className="home-ops__value">{money(data.cost.total_cost_micros)}</span>
                <span className="muted">Scoped cost</span>
              </button>
              <button className="home-ops__metric" onClick={() => navigate("/runs")}>
                <span className={`home-ops__value ${failed ? "error" : ""}`}>{failed}</span>
                <span className="muted">Failed events</span>
              </button>
              <button className="home-ops__metric" onClick={() => navigate("/health")}>
                <span className={`home-ops__value ${degraded ? "warn" : ""}`}>{degraded}</span>
                <span className="muted">Degraded events</span>
              </button>
              <button className="home-ops__metric" onClick={() => navigate("/approvals")}>
                <span className="home-ops__value">{data.counts.pending_approvals}</span>
                <span className="muted">Pending approvals</span>
              </button>
            </div>

            <div className="home-ops__columns">
              <div>
                <div className="home-ops__subhead">
                  <h4>Runtime posture</h4>
                  <button className="entity-link" onClick={() => navigate("/health")}>Open health</button>
                </div>
                <div className="home-ops__platform">
                  {platform.length
                    ? platform.slice(0, 5).map((item) => <PlatformRow key={`${item.kind}:${item.id}`} item={item} />)
                    : <p className="muted">No runtime status provider is configured.</p>}
                </div>
              </div>
              <div>
                <div className="home-ops__subhead">
                  <h4>Spend posture</h4>
                  <button className="entity-link" onClick={() => navigate("/insight")}>Open insight</button>
                </div>
                {budget ? (
                  <div className="home-ops__budget">
                    <div>
                      <strong>{budget.budget.id}</strong>
                      <span className="muted">{budget.budget.scope_type} · {budget.budget.window}</span>
                    </div>
                    <div className="home-ops__bar" aria-label={`${Math.round(budget.ratio * 100)}% of budget used`}>
                      <span style={{ width: `${Math.min(100, budget.ratio * 100)}%` }} />
                    </div>
                    <span className={budget.ratio >= 1 && budget.budget.hard_stop ? "error" : budget.ratio >= 0.9 ? "warn" : "muted"}>
                      {budget.ratio >= 1 && budget.budget.hard_stop ? "Hard stop reached" : `${Math.round(budget.ratio * 100)}% used`}
                    </span>
                  </div>
                ) : <p className="muted">No scoped budgets are configured.</p>}
                {model && (
                  <div className="home-ops__model">
                    <span className="muted">Most recent model route</span>
                    <strong>{model.provider} / {model.model}</strong>
                    <span className="muted">{model.runtime} · {model.calls} call{model.calls === 1 ? "" : "s"} · {money(model.cost_micros)}</span>
                  </div>
                )}
              </div>
            </div>
          </>
        )}
      </div>
    </section>
  );
}
