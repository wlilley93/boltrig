import { api } from "@/api/client";
import type { DeckCol } from "@/deck/Deck";
import { navigate } from "@/router";
import { useFetch } from "@/useFetch";
import { HINT, ICON } from "./navMeta";

interface OpsGroupProps {
  cols: DeckCol[];
  active: { rowId: string; colKey: string };
}

// The Ops group: Home + the remaining tabs as deck columns, with a pending
// approvals count. The lightweight 30s poll lives HERE so its re-render stays
// inside this sidebar group instead of re-rendering the whole shell + deck.
export function OpsGroup({ cols, active }: OpsGroupProps) {
  const hitl = useFetch(() => api.hitl(), [], 30000);
  const pending = hitl.data?.requests.length ?? 0;
  const badgeTitle = `${pending} approval(s) waiting`;
  return (
    <div className="side-group" role="group" aria-label="Ops">
      <div className="side-group__head">
        <span className="side-group__label">Ops</span>
        {pending > 0 && (
          <span className="side-badge side-badge--group" title={badgeTitle}>
            {pending}
          </span>
        )}
      </div>
      {cols.map((col) => {
        const isActive = active.rowId === "ops" && active.colKey === col.key;
        return (
          <button
            key={col.key}
            className={`side-item ${isActive ? "side-item--active" : ""}`}
            aria-current={isActive ? "page" : undefined}
            title={HINT[col.key]}
            onClick={() => navigate(col.path)}
          >
            <span className="side-item__icon" aria-hidden="true">{ICON[col.key]}</span>
            <span className="side-item__label">{col.label}</span>
            {col.key === "approvals" && pending > 0 && (
              <span className="side-badge side-badge--item" title={badgeTitle}>
                {pending}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
