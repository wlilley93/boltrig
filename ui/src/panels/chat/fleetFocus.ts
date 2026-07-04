// Shared fleet-focus signal for the empty-composer ArrowDown shortcut
// (CHAT-DESIGN-BRIEF sec 18). A tiny module bus lets the composer key handler
// ask the live FleetBar to take focus, and lets the FleetBar hand focus back to
// the composer on Escape, WITHOUT changing any component prop signatures. The
// composer key handler also uses the pure predicate below so the entry decision
// is unit-testable in isolation.

export interface FleetEntryContext {
  key: string;
  input: string;
  streaming: boolean;
  fleetActive: boolean;
}

// True when ArrowDown in an EMPTY, idle composer should hand focus to the live
// fleet bar. Mirrors the keyboard table in sec 18: the slash menu (input starts
// with "/") keeps owning Up/Down, so this only fires on truly empty input, and
// only while a run is live (fleetActive).
export function shouldEnterFleetNavigation(ctx: FleetEntryContext): boolean {
  return (
    ctx.key === "ArrowDown" &&
    ctx.input.trim() === "" &&
    !ctx.streaming &&
    ctx.fleetActive
  );
}

type Listener = () => void;

const fleetListeners = new Set<Listener>();
const composerListeners = new Set<Listener>();

// Ask the live FleetBar to take focus (it resets its focus index to 0). No-op
// when no FleetBar is mounted, which is the correct degradation when no run is
// live.
export function requestFleetFocus(): void {
  fleetListeners.forEach((fn) => fn());
}

// Subscribe to fleet-focus requests. Returns an unsubscribe function.
export function onFleetFocusRequest(fn: Listener): () => void {
  fleetListeners.add(fn);
  return () => {
    fleetListeners.delete(fn);
  };
}

// Ask the composer textarea to take focus (used by the fleet Escape handler to
// return focus to the composer).
export function requestComposerFocus(): void {
  composerListeners.forEach((fn) => fn());
}

// Subscribe to composer-focus requests. Returns an unsubscribe function.
export function onComposerFocusRequest(fn: Listener): () => void {
  composerListeners.add(fn);
  return () => {
    composerListeners.delete(fn);
  };
}
