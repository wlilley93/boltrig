import { api } from "@/api/client";
import { useFetch } from "@/useFetch";
import { FetchError } from "@/panels/ux";
import { money, pct } from "./formatting";

export function Budgets() {
  const budgets = useFetch(() => api.budgets(), []);
  const list = budgets.data?.budgets ?? [];
  return (
    <div className="list-card">
      <div className="list-card__head">
        <h3>Budgets</h3>
        <button className="btn" onClick={() => budgets.reload()}>
          Refresh
        </button>
      </div>
      <div className="list-card__body">
        {budgets.loading && !budgets.data && <p className="muted">Loading...</p>}
        <FetchError error={budgets.error} status={budgets.errorStatus} onRetry={budgets.reload} />
        {!budgets.loading && !budgets.error && list.length === 0 && (
          <p className="muted">No budgets set. Budgets cap token + cost spend per scope.</p>
        )}
        {list.map((b) => {
          const tp = pct(b.spent_tokens, b.token_limit);
          const cp = pct(b.spent_micros, b.cost_limit_micros);
          const worst = Math.max(tp ?? 0, cp ?? 0);
          return (
            <div className="budget-row" key={`${b.scope_type}:${b.id}`}>
              <div className="kv">
                <code className="tag">{b.scope_type}</code>
                <strong>{b.id}</strong>
                <span className="muted" style={{ fontSize: 11 }}>{b.window}</span>
                {b.hard_stop && (
                  <span className="badge badge--conseq-high" title="Spending stops at the limit.">
                    hard stop
                  </span>
                )}
              </div>
              <div
                className="budget-bar"
                title={`${worst}% of the tightest limit used`}
                role="progressbar"
                aria-valuenow={worst}
                aria-valuemin={0}
                aria-valuemax={100}
                aria-label={`${b.id} budget: ${worst}% used`}
              >
                <span
                  className={`budget-bar__fill ${worst >= 90 ? "is-down" : worst >= 70 ? "is-warn" : ""}`}
                  style={{ width: `${worst}%` }}
                />
              </div>
              <div className="kv" style={{ fontSize: 11 }}>
                {b.token_limit != null && (
                  <span className="muted">
                    tokens {b.spent_tokens.toLocaleString()} / {b.token_limit.toLocaleString()}
                  </span>
                )}
                {b.cost_limit_micros != null && (
                  <span className="muted">
                    cost {money(b.spent_micros)} / {money(b.cost_limit_micros)}
                  </span>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
