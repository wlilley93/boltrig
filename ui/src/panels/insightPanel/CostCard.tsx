import { FetchError, Hint } from "@/panels/ux";
import { scopeLabel } from "@/panels/shared";
import type { InsightState } from "./useInsightState";
import { money } from "./formatting";

export function CostCard({ s }: { s: InsightState }) {
  const costData = s.costData;
  return (
    <div className="list-card">
      <div className="list-card__head">
        <h3>Cost</h3>
        <span className="muted">
          scope: {costData ? scopeLabel(costData.scope) : "..."}
        </span>
      </div>
      <div className="list-card__body">
        {s.cost.loading && !s.cost.data && <p className="muted">Loading...</p>}
        <FetchError error={s.cost.error} status={s.cost.errorStatus} onRetry={s.cost.reload} />
        {costData && (
          <>
            <div className="row-line">
              <span className="muted">Total cost</span>
              <strong title={`${costData.total_cost_micros} micros`}>
                {money(costData.total_cost_micros)}
              </strong>
            </div>
            {Object.entries(costData.by_actor).length === 0 ? (
              <p className="muted">No cost recorded in scope yet.</p>
            ) : (
              <>
                <Hint>Who has spent what:</Hint>
                {Object.entries(costData.by_actor).map(([who, micros]) => (
                  <div className="row-line" key={who}>
                    <code>{who}</code>
                    <span title={`${micros} micros`}>{money(micros)}</span>
                  </div>
                ))}
              </>
            )}
          </>
        )}
      </div>
    </div>
  );
}
