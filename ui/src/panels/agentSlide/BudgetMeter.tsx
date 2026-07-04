import { budgetPct } from "../agents/model";
import type { BudgetItem } from "../../api/types";

export function BudgetMeter({ budget }: { budget?: BudgetItem }) {
  const pct = budgetPct(budget);
  if (!budget || pct === null) {
    return <span className="muted">No department budget row is visible.</span>;
  }
  const limit =
    budget.token_limit !== null
      ? `${budget.spent_tokens} / ${budget.token_limit} tokens`
      : budget.cost_limit_micros !== null
        ? `$${(budget.spent_micros / 1_000_000).toFixed(2)} / $${(budget.cost_limit_micros / 1_000_000).toFixed(2)}`
        : "no limit";
  return (
    <div className="ag-detail-budget">
      <span className="ag-budget ag-budget--wide">
        <span className="ag-budget__fill" style={{ width: `${pct}%` }} />
      </span>
      <span>
        {limit} this {budget.window}. {budget.hard_stop ? "Hard stop on." : "Soft alert only."}
      </span>
    </div>
  );
}
