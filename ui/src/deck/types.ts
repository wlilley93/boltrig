// The deck engine: every zone is a slide on one large translated plane, rows
// stacked vertically and each row's columns laid out horizontally. The route is
// the only source of truth - the deck never holds "where am I" state of its
// own; it navigates by writing the hash and animates when the active cell
// (given via props) changes. Overlays (RunView, CommandPalette) must stay
// SIBLINGS of the deck: they are position:fixed and a transformed ancestor
// would re-root them into a slide.

import type { ReactNode } from "react";

export interface DeckCol {
  key: string;
  label: string;
  // full hash path for the cell, segments already URI-encoded (e.g. "/agents/front-desk")
  path: string;
}

export interface DeckRow {
  id: string;
  label: string;
  // cols[0] is the row anchor
  cols: DeckCol[];
}

export interface DeckProps {
  // VISIBLE rows in vertical order (role-filtered by the caller)
  rows: DeckRow[];
  // total: the caller guarantees it names an existing cell
  active: { rowId: string; colKey: string };
  render: (rowId: string, colKey: string) => ReactNode;
  // extra cell keys (rowId + ":" + colKey) kept mounted once visited
  keepAlive?: string[];
}

// matches --deck-dur in styles.css; the settle fallback adds 80ms of slack
export const SLIDE_MS = 360;
// just past --dur-fast (120ms) so the fade completes before the jump
export const FADE_MS = 140;

export type Dir = "left" | "right" | "up" | "down";

export interface CellPos {
  row: DeckRow;
  col: DeckCol;
  x: number;
  y: number;
}

export interface SlideProps {
  x: number;
  y: number;
  row: DeckRow;
  col: DeckCol;
  active: boolean;
  neighbour: boolean;
  // keep-alive cell outside the neighbourhood: mounted (state survives) but not painted
  parked: boolean;
  // the slide being left keeps focus / AT visibility until the move settles
  outgoingHold: boolean;
  frameRef: (el: HTMLDivElement | null) => void;
  children: ReactNode;
}

export function cellKey(rowId: string, colKey: string): string {
  return `${rowId}:${colKey}`;
}

export function findCell(rows: DeckRow[], key: string): CellPos | null {
  for (let y = 0; y < rows.length; y++) {
    const row = rows[y];
    for (let x = 0; x < row.cols.length; x++) {
      if (cellKey(row.id, row.cols[x].key) === key) {
        return { row, col: row.cols[x], x, y };
      }
    }
  }
  return null;
}

// Navigation target one step in a direction. Vertical moves land on the same
// column index when the adjacent row has one, else that row's anchor - the
// engine then renders the move as a far-jump fade rather than a slide.
export function navTarget(rows: DeckRow[], key: string, dir: Dir): DeckCol | null {
  const pos = findCell(rows, key);
  if (!pos) return null;
  if (dir === "left") return pos.x > 0 ? pos.row.cols[pos.x - 1] : null;
  if (dir === "right") {
    return pos.x < pos.row.cols.length - 1 ? pos.row.cols[pos.x + 1] : null;
  }
  const ny = dir === "up" ? pos.y - 1 : pos.y + 1;
  if (ny < 0 || ny >= rows.length) return null;
  const nrow = rows[ny];
  return nrow.cols[pos.x] ?? nrow.cols[0] ?? null;
}

// Orthogonal neighbours for the MOUNT set: only cells that sit directly beside
// the given cell on the plane (vertical requires the same column index, or the
// pre-mounted slide would not be the one seen during the transition).
export function mountNeighbours(rows: DeckRow[], key: string): string[] {
  const pos = findCell(rows, key);
  if (!pos) return [];
  const out: string[] = [];
  if (pos.x > 0) out.push(cellKey(pos.row.id, pos.row.cols[pos.x - 1].key));
  if (pos.x < pos.row.cols.length - 1) {
    out.push(cellKey(pos.row.id, pos.row.cols[pos.x + 1].key));
  }
  for (const ny of [pos.y - 1, pos.y + 1]) {
    const nrow = rows[ny];
    const ncol = nrow?.cols[pos.x];
    if (nrow && ncol) out.push(cellKey(nrow.id, ncol.key));
  }
  return out;
}

// Deck keys must never fire while the user is typing or inside the flow canvas.
export function editingContext(): boolean {
  const el = document.activeElement as HTMLElement | null;
  if (!el) return false;
  const tag = el.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
  if (el.isContentEditable) return true;
  if (el.closest(".react-flow")) return true;
  return false;
}

// The app zeroes transition durations under reduce-motion, which covers the
// CSS-driven slide; the fade-jump choreography uses JS timeouts, so it checks
// this and snaps instantly instead.
export function motionOff(): boolean {
  return (
    document.documentElement.classList.contains("reduce-motion") ||
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

export const CHEVRON_PATH: Record<Dir, string> = {
  left: "m14 6-6 6 6 6",
  right: "m10 6 6 6-6 6",
  up: "m6 14 6-6 6 6",
  down: "m6 10 6 6 6-6",
};
