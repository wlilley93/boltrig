import { Suspense, useEffect, useMemo, useRef } from "react";

import { DeckSlideContext, type SlideState } from "@/deck/context";
import { ErrorBoundary } from "@/ErrorBoundary";
import type { SlideProps } from "@/deck/types";

export function DeckSlide(props: SlideProps) {
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
