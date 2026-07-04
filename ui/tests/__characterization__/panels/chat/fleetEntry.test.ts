import { describe, it, expect } from "vitest";
import {
  shouldEnterFleetNavigation,
  requestFleetFocus,
  onFleetFocusRequest,
  requestComposerFocus,
  onComposerFocusRequest,
} from "@/panels/chat/fleetFocus";

describe("shouldEnterFleetNavigation (sec 18 key-handler branch)", () => {
  const base = { key: "ArrowDown", input: "", streaming: false, fleetActive: true };

  it("enters the fleet on ArrowDown from an empty, idle composer with a live fleet", () => {
    expect(shouldEnterFleetNavigation(base)).toBe(true);
  });

  it("does not enter when the composer has text (slash menu / typing owns the key)", () => {
    expect(shouldEnterFleetNavigation({ ...base, input: "hello" })).toBe(false);
    expect(shouldEnterFleetNavigation({ ...base, input: "  /clear  " })).toBe(false);
  });

  it("does not enter while streaming", () => {
    expect(shouldEnterFleetNavigation({ ...base, streaming: true })).toBe(false);
  });

  it("does not enter when no fleet run is live", () => {
    expect(shouldEnterFleetNavigation({ ...base, fleetActive: false })).toBe(false);
  });

  it("ignores keys other than ArrowDown", () => {
    expect(shouldEnterFleetNavigation({ ...base, key: "ArrowUp" })).toBe(false);
    expect(shouldEnterFleetNavigation({ ...base, key: "Enter" })).toBe(false);
    expect(shouldEnterFleetNavigation({ ...base, key: "Escape" })).toBe(false);
  });
});

describe("fleet-focus signal bus", () => {
  it("delivers fleet-focus requests to subscribers and lets them unsubscribe", () => {
    const calls: number[] = [];
    const off = onFleetFocusRequest(() => calls.push(1));
    requestFleetFocus();
    requestFleetFocus();
    off();
    requestFleetFocus();
    expect(calls.length).toBe(2);
  });

  it("delivers composer-focus requests to subscribers and lets them unsubscribe", () => {
    const calls: number[] = [];
    const off = onComposerFocusRequest(() => calls.push(1));
    requestComposerFocus();
    off();
    requestComposerFocus();
    expect(calls.length).toBe(1);
  });
});
