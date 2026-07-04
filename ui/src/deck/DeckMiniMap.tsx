import { navigate } from "@/router";
import type { DeckRow } from "@/deck/types";

interface DeckMiniMapProps {
  rows: DeckRow[];
  active: { rowId: string; colKey: string };
}

export function DeckMiniMap({ rows, active }: DeckMiniMapProps) {
  return (
    <div className="deck__map" role="presentation" aria-hidden="true">
      {rows.map((row) => {
        const isRow = row.id === active.rowId;
        const anchor = row.cols[0];
        if (!anchor) return null;
        return (
          <div
            key={row.id}
            className={`deck-map__row${isRow ? " deck-map__row--active" : ""}`}
          >
            {isRow && row.cols.length > 1 && (
              <span className="deck-map__dots">
                {row.cols.map((c) => (
                  <button
                    key={c.key}
                    type="button"
                    className="deck-map__dot"
                    aria-label={`${row.label}: ${c.label}`}
                    aria-current={c.key === active.colKey ? "true" : undefined}
                    onClick={() => navigate(c.path)}
                  />
                ))}
              </span>
            )}
            <button
              type="button"
              className="deck-map__rowbtn"
              aria-label={`Go to ${row.label}`}
              aria-current={isRow && row.cols.length === 1 ? "true" : undefined}
              onClick={() => navigate(anchor.path)}
            >
              {row.label}
            </button>
          </div>
        );
      })}
    </div>
  );
}
