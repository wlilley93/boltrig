import { useMemo } from "react";

import { findCell, type DeckRow } from "@/deck/types";

export function useDeckAnnounce(rows: DeckRow[], settledKey: string) {
  return useMemo(() => {
    const pos = findCell(rows, settledKey);
    if (!pos) return "";
    const m = pos.row.cols.length;
    return m > 1
      ? `${pos.row.label}: ${pos.col.label} (${pos.x + 1} of ${m})`
      : `${pos.row.label}: ${pos.col.label}`;
  }, [rows, settledKey]);
}
