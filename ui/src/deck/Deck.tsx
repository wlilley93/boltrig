// The deck engine: every zone is a slide on one large translated plane, rows
// stacked vertically and each row's columns laid out horizontally. The route is
// the only source of truth - the deck never holds "where am I" state of its
// own; it navigates by writing the hash and animates when the active cell
// (given via props) changes. Overlays (RunView, CommandPalette) must stay
// SIBLINGS of the deck: they are position:fixed and a transformed ancestor
// would re-root them into a slide.

import {
  Suspense,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { ErrorBoundary } from "../ErrorBoundary";
import { getRoute, navigate } from "../router";
import { DeckSlideContext, type SlideState } from "./context";

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
const SLIDE_MS = 360;
// just past --dur-fast (120ms) so the fade completes before the jump
const FADE_MS = 140;

type Dir = "left" | "right" | "up" | "down";

interface CellPos {
  row: DeckRow;
  col: DeckCol;
  x: number;
  y: number;
}

function cellKey(rowId: string, colKey: string): string {
  return `${rowId}:${colKey}`;
}

function findCell(rows: DeckRow[], key: string): CellPos | null {
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
function navTarget(rows: DeckRow[], key: string, dir: Dir): DeckCol | null {
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
function mountNeighbours(rows: DeckRow[], key: string): string[] {
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
function editingContext(): boolean {
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
function motionOff(): boolean {
  return (
    document.documentElement.classList.contains("reduce-motion") ||
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

const CHEVRON_PATH: Record<Dir, string> = {
  left: "m14 6-6 6 6 6",
  right: "m10 6 6 6-6 6",
  up: "m6 14 6-6 6 6",
  down: "m6 10 6 6 6-6",
};

interface SlideProps {
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

function DeckSlide(props: SlideProps) {
  const { x, y, row, col, active, neighbour, parked, outgoingHold, frameRef, children } = props;
  const ref = useRef<HTMLDivElement>(null);
  const inertOn = parked || (!active && !outgoingHold);
  useEffect(() => {
    // React 18 does not type the inert prop - toggle the DOM attribute instead.
    ref.current?.toggleAttribute("inert", inertOn);
  }, [inertOn]);
  const ctx = useMemo<SlideState>(() => ({ active, neighbour }), [active, neighbour]);
  const m = row.cols.length;
  const n = row.cols.findIndex((c) => c.key === col.key) + 1;
  return (
    <div
      ref={ref}
      className={`deck__slide${active ? " deck__slide--active" : ""}${parked ? " deck__slide--parked" : ""}`}
      style={{ left: `calc(${x} * 100%)`, top: `calc(${y} * 100%)` }}
      aria-hidden={inertOn ? true : undefined}
    >
      {m > 1 && (
        <div className="deck__crumb" aria-hidden="true">
          {row.label} / {col.label} - {n} of {m}
        </div>
      )}
      {/* the frame is the scroller; tabIndex -1 so settle can focus it */}
      <div className="deck__frame" tabIndex={-1} ref={frameRef}>
        <DeckSlideContext.Provider value={ctx}>
          <ErrorBoundary label={col.label}>
            <Suspense fallback={<p className="muted">Loading...</p>}>{children}</Suspense>
          </ErrorBoundary>
        </DeckSlideContext.Provider>
      </div>
    </div>
  );
}

export function Deck(props: DeckProps): JSX.Element {
  const { rows, active, render, keepAlive } = props;
  const activeKey = cellKey(active.rowId, active.colKey);

  const deckRef = useRef<HTMLDivElement>(null);
  const planeRef = useRef<HTMLDivElement>(null);
  const frames = useRef(new Map<string, HTMLDivElement>());
  const visited = useRef(new Set<string>());
  // idempotent grow-only set: safe under StrictMode's double render
  visited.current.add(activeKey);

  // settledKey lags activeKey while a move is in flight; the mount set derives
  // from it so new neighbours mount only after the transition settles.
  const [settledKey, setSettledKey] = useState(activeKey);
  const [moving, setMoving] = useState(false);
  const [announce, setAnnounce] = useState("");

  // latest props for window-level handlers and late settle callbacks
  const latest = useRef({ rows, activeKey });
  latest.current = { rows, activeKey };

  const prevPos = useRef<{ key: string; x: number; y: number } | null>(null);
  // cancels the pending settle (listeners or fade timers) WITHOUT settling
  const settleCleanup = useRef<(() => void) | null>(null);

  const target = findCell(rows, activeKey);
  const tx = target ? target.x : 0;
  const ty = target ? target.y : 0;

  const finishMove = () => {
    const { rows: rs, activeKey: key } = latest.current;
    setMoving(false);
    setSettledKey(key);
    const plane = planeRef.current;
    if (plane) plane.style.willChange = "";
    // focus first; the outgoing slide only goes inert on the re-render that
    // follows (React batches the state writes above until this handler exits).
    // Guard: only claim focus when it is not parked somewhere outside the deck
    // (e.g. a sidebar item mid keyboard navigation).
    const frame = frames.current.get(key);
    const ae = document.activeElement;
    const deck = deckRef.current;
    if (frame && (!ae || ae === document.body || (deck && deck.contains(ae)))) {
      frame.focus({ preventScroll: true });
    }
    const pos = findCell(rs, key);
    if (pos) {
      const m = pos.row.cols.length;
      setAnnounce(
        m > 1
          ? `${pos.row.label}: ${pos.col.label} (${pos.x + 1} of ${m})`
          : `${pos.row.label}: ${pos.col.label}`,
      );
    }
  };

  // Settle primitive: transitionend / transitioncancel on the plane filtered to
  // transform, with a duration + 80ms timeout fallback. Retargeting mid-flight
  // first cancels the previous arm; the interrupted transition then emits one
  // stale transitioncancel, which is swallowed exactly once.
  const armSettle = (plane: HTMLElement, ms: number, done: () => void) => {
    const wasPending = settleCleanup.current !== null;
    settleCleanup.current?.();
    let fired = false;
    let skipCancel = wasPending;
    const cleanup = () => {
      plane.removeEventListener("transitionend", onEnd);
      plane.removeEventListener("transitioncancel", onEnd);
      window.clearTimeout(timer);
    };
    const finish = () => {
      if (fired) return;
      fired = true;
      cleanup();
      settleCleanup.current = null;
      done();
    };
    const onEnd = (ev: TransitionEvent) => {
      if (ev.target !== plane || ev.propertyName !== "transform") return;
      if (ev.type === "transitioncancel" && skipCancel) {
        skipCancel = false;
        return;
      }
      finish();
    };
    const timer = window.setTimeout(finish, ms + 80);
    plane.addEventListener("transitionend", onEnd);
    plane.addEventListener("transitioncancel", onEnd);
    settleCleanup.current = () => {
      cleanup();
      settleCleanup.current = null;
    };
  };

  useLayoutEffect(() => {
    const plane = planeRef.current;
    if (!plane || !target) return;
    const apply = () => {
      plane.style.setProperty("--deck-x", String(tx));
      plane.style.setProperty("--deck-y", String(ty));
    };
    const snap = () => {
      plane.style.transition = "none";
      apply();
      void plane.offsetWidth; // flush so restoring the transition does not animate
      plane.style.transition = "";
    };
    const prev = prevPos.current;
    prevPos.current = { key: activeKey, x: tx, y: ty };

    if (!prev) {
      // first paint - position without animating
      snap();
      return;
    }
    if (prev.key === activeKey) {
      // same cell whose indices shifted (a column list changed): re-derive the
      // transform for the same key with the transition suppressed - no lurch.
      if (prev.x !== tx || prev.y !== ty) snap();
      return;
    }
    const dist = Math.abs(tx - prev.x) + Math.abs(ty - prev.y);
    // Unknown tabs and #/runs deep links resolve to the chat anchor with NO
    // animation: a route whose first segment matches no deck cell is one of those.
    const route = getRoute();
    const known = rows.some((r) =>
      r.cols.some((c) => c.path.split("/").filter(Boolean)[0] === route.tab),
    );
    if (dist === 0 || !known || document.visibilityState !== "visible" || (dist > 1 && motionOff())) {
      settleCleanup.current?.();
      snap();
      finishMove();
      return;
    }
    setMoving(true);
    plane.style.willChange = "transform";
    if (dist === 1) {
      plane.style.transition = "";
      apply();
      armSettle(plane, SLIDE_MS, finishMove);
    } else {
      // far or diagonal move: fade the plane out, jump the transform, fade back
      settleCleanup.current?.();
      plane.classList.add("deck__plane--faded");
      const t1 = window.setTimeout(() => {
        snap();
        plane.classList.remove("deck__plane--faded");
        const t2 = window.setTimeout(() => {
          settleCleanup.current = null;
          finishMove();
        }, FADE_MS);
        settleCleanup.current = () => {
          window.clearTimeout(t2);
          settleCleanup.current = null;
        };
      }, FADE_MS);
      settleCleanup.current = () => {
        window.clearTimeout(t1);
        plane.classList.remove("deck__plane--faded");
        settleCleanup.current = null;
      };
    }
    // finishMove and rows are read through refs / only on a keyed move
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeKey, tx, ty]);

  // cancel any pending settle on unmount
  useEffect(() => () => settleCleanup.current?.(), []);

  // Boundary feedback: nudge the plane a few px toward the attempted direction.
  // The keyframe folds the base translate back in, so nothing jumps.
  const bump = (dir: Dir) => {
    const plane = planeRef.current;
    if (!plane) return;
    const horizontal = dir === "left" || dir === "right";
    const px = dir === "right" || dir === "down" ? -10 : 10;
    plane.style.setProperty("--deck-bump", `${px}px`);
    const cls = horizontal ? "deck__plane--bump-h" : "deck__plane--bump-v";
    plane.classList.remove("deck__plane--bump-h", "deck__plane--bump-v");
    void plane.offsetWidth; // restart the animation when bumping twice in a row
    plane.classList.add(cls);
    window.setTimeout(() => plane.classList.remove(cls), 260);
  };

  const tryMove = (dir: Dir) => {
    const { rows: rs, activeKey: key } = latest.current;
    const t = navTarget(rs, key, dir);
    if (t) navigate(t.path);
    else bump(dir);
  };

  // Deck keys: Ctrl+Alt+Arrow (Cmd+Alt on mac). Plain Alt+Arrow stays with the
  // browser so history back / forward keeps working (and animates via the route).
  useEffect(() => {
    const DIRS: Record<string, Dir> = {
      ArrowLeft: "left",
      ArrowRight: "right",
      ArrowUp: "up",
      ArrowDown: "down",
    };
    function onKey(e: KeyboardEvent) {
      const dir = DIRS[e.key];
      if (!dir) return;
      if (!e.altKey || !(e.ctrlKey || e.metaKey)) return;
      if (e.defaultPrevented) return;
      if (editingContext()) return;
      if (document.querySelector(".cmdk-overlay")) return; // command palette open
      if (getRoute().runId) return; // run drawer open
      e.preventDefault();
      tryMove(dir);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // tryMove reads only refs, so the mount-time closure stays correct
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Touch swipe: pointerType touch only, claimed only when clearly horizontal
  // and no element under the finger can scroll that way. No wheel hijack ever.
  interface SwipeState {
    id: number;
    startX: number;
    startY: number;
    scrollables: HTMLElement[];
  }
  const swipe = useRef<SwipeState | null>(null);

  const onPointerDown = (e: React.PointerEvent) => {
    if (e.pointerType !== "touch") return;
    // leave the OS edge (back) gesture alone
    if (e.clientX <= 24 || e.clientX >= window.innerWidth - 24) return;
    const deck = deckRef.current;
    const path = e.nativeEvent.composedPath();
    const scrollables: HTMLElement[] = [];
    for (const t of path) {
      if (!(t instanceof HTMLElement)) continue;
      if (t === deck) break;
      const tag = t.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      if (t.isContentEditable) return;
      if (t.classList.contains("react-flow")) return;
      if (t.scrollWidth > t.clientWidth + 1) scrollables.push(t);
    }
    swipe.current = { id: e.pointerId, startX: e.clientX, startY: e.clientY, scrollables };
  };

  const onPointerMove = (e: React.PointerEvent) => {
    const s = swipe.current;
    if (!s || e.pointerId !== s.id) return;
    const dx = e.clientX - s.startX;
    const dy = e.clientY - s.startY;
    if (Math.abs(dx) <= 48 || Math.abs(dx) <= 2 * Math.abs(dy)) return;
    swipe.current = null; // decided: claim or yield exactly once per gesture
    for (const el of s.scrollables) {
      const room =
        dx < 0 ? el.scrollLeft + el.clientWidth < el.scrollWidth - 1 : el.scrollLeft > 0;
      if (room) return; // the content still has scroll room - not our gesture
    }
    tryMove(dx < 0 ? "right" : "left");
  };

  const onPointerEnd = (e: React.PointerEvent) => {
    if (swipe.current && e.pointerId === swipe.current.id) swipe.current = null;
  };

  // Mount policy: active + settled + orthogonal neighbours of the SETTLED cell
  // (so new neighbours mount only after settle) + visited keep-alive cells.
  const neighbourKeys = useMemo(
    () => new Set(mountNeighbours(rows, settledKey)),
    [rows, settledKey],
  );

  const mountedKeys = useMemo(() => {
    const set = new Set<string>();
    const add = (k: string) => {
      if (findCell(rows, k)) set.add(k);
    };
    add(activeKey);
    add(settledKey);
    for (const k of neighbourKeys) add(k);
    for (const k of keepAlive ?? []) if (visited.current.has(k)) add(k);
    return set;
    // visited only grows, and every growth comes with a render of its own
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows, activeKey, settledKey, neighbourKeys, keepAlive]);

  const slides: JSX.Element[] = [];
  for (const key of mountedKeys) {
    const pos = findCell(rows, key);
    if (!pos) continue;
    const isActive = key === activeKey;
    const isNeighbour = !isActive && neighbourKeys.has(key);
    const isOutgoing = moving && key === settledKey && !isActive;
    const parked = !isActive && !isNeighbour && !isOutgoing;
    slides.push(
      <DeckSlide
        key={key}
        x={pos.x}
        y={pos.y}
        row={pos.row}
        col={pos.col}
        active={isActive}
        neighbour={isNeighbour}
        parked={parked}
        outgoingHold={isOutgoing}
        frameRef={(el) => {
          if (el) frames.current.set(key, el);
          else frames.current.delete(key);
        }}
      >
        {render(pos.row.id, pos.col.key)}
      </DeckSlide>,
    );
  }

  const chevrons = (["left", "right", "up", "down"] as Dir[]).map((dir) => {
    const t = navTarget(rows, activeKey, dir);
    if (!t) return null;
    return (
      <button
        key={dir}
        type="button"
        className={`deck__chevron deck__chevron--${dir}`}
        aria-label={`${t.label} (${dir})`}
        title={`${t.label} (${dir})`}
        onClick={() => navigate(t.path)}
      >
        <svg
          viewBox="0 0 24 24"
          width="18"
          height="18"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d={CHEVRON_PATH[dir]} />
        </svg>
      </button>
    );
  });

  return (
    <div
      ref={deckRef}
      className={`deck${moving ? " deck--moving" : ""}`}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerEnd}
      onPointerCancel={onPointerEnd}
    >
      <div ref={planeRef} className="deck__plane">
        {slides}
      </div>

      {chevrons}

      <div className="deck__map" role="group" aria-label="Deck map">
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

      {/* outside the plane so a transform never re-roots it; announces settles */}
      <div className="deck__announcer" aria-live="polite">
        {announce}
      </div>
    </div>
  );
}
