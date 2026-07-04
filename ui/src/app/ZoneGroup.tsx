import { Fragment } from "react";
import type { DeckRow } from "@/deck/Deck";
import { navigate } from "@/router";
import { HINT, ICON } from "./navMeta";

interface ZoneGroupProps {
  rows: DeckRow[];
  active: { rowId: string; colKey: string };
}

// The zone rows (Chat, Agents, Automations, Settings) in the sidebar rail. Each
// row can expand into a sublist of its slides when it is active.
export function ZoneGroup({ rows, active }: ZoneGroupProps) {
  return (
    <div className="side-group" role="group" aria-label="Zones">
      {rows.map((row) => {
        const rowActive = active.rowId === row.id;
        return (
          <Fragment key={row.id}>
            <button
              className={`side-item ${rowActive ? "side-item--active" : ""}`}
              aria-current={rowActive ? "page" : undefined}
              title={HINT[row.id]}
              onClick={() => navigate(row.cols[0].path)}
            >
              <span className="side-item__icon" aria-hidden="true">{ICON[row.id]}</span>
              <span className="side-item__label">{row.label}</span>
            </button>
            {rowActive && row.cols.length > 1 && (
              <div
                className="side-sublist"
                role="group"
                aria-label={`${row.label} slides`}
              >
                {row.cols.map((col) => (
                  <button
                    key={col.key}
                    className={`side-subitem ${active.colKey === col.key ? "side-subitem--active" : ""}`}
                    aria-current={active.colKey === col.key ? "page" : undefined}
                    onClick={() => navigate(col.path)}
                  >
                    <span className="side-subitem__label">{col.label}</span>
                  </button>
                ))}
              </div>
            )}
          </Fragment>
        );
      })}
    </div>
  );
}
