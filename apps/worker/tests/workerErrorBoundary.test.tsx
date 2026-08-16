// @vitest-environment happy-dom

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  WORKER_CHUNK_RECOVERY_KEY,
  WorkerErrorBoundary,
  isRecoverableChunkError,
} from "../src/components/WorkerErrorBoundary";

function Crash({ error }: { error: Error }): never {
  throw error;
}

beforeEach(() => {
  sessionStorage.clear();
  vi.spyOn(console, "error").mockImplementation(() => undefined);
});

afterEach(() => {
  cleanup();
  sessionStorage.clear();
  vi.restoreAllMocks();
});

describe("Worker release recovery", () => {
  it("recognises browser and bundler dynamic-import failures", () => {
    expect(isRecoverableChunkError(new TypeError(
      "Failed to fetch dynamically imported module: https://dev.boltrig.io/assets/ChatView-old.js",
    ))).toBe(true);
    expect(isRecoverableChunkError(new Error("Loading chunk 42 failed"))).toBe(true);
    expect(isRecoverableChunkError(new Error("ordinary render failure"))).toBe(false);
  });

  it("reloads once when a stale lazy chunk is first encountered", () => {
    const reload = vi.fn();
    const error = new TypeError(
      "Failed to fetch dynamically imported module: https://dev.boltrig.io/assets/ChatView-old.js",
    );

    render(
      <WorkerErrorBoundary reload={reload}>
        <Crash error={error} />
      </WorkerErrorBoundary>,
    );

    expect(reload).toHaveBeenCalledTimes(1);
    expect(screen.getByText("Updating Boltrig…")).toBeTruthy();
    expect(sessionStorage.getItem(WORKER_CHUNK_RECOVERY_KEY)).toContain("ChatView-old.js");
  });

  it("stops an automatic reload loop and leaves an explicit recovery action", () => {
    const reload = vi.fn();
    const message = "Importing a module script failed: ChatView-old.js";
    sessionStorage.setItem(WORKER_CHUNK_RECOVERY_KEY, message);

    render(
      <WorkerErrorBoundary reload={reload}>
        <Crash error={new TypeError(message)} />
      </WorkerErrorBoundary>,
    );

    expect(reload).not.toHaveBeenCalled();
    expect(screen.getByText("The update didn’t load.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Reload" }));
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it("shows a nonblank fallback without auto-reloading ordinary errors", () => {
    const reload = vi.fn();

    render(
      <WorkerErrorBoundary reload={reload}>
        <Crash error={new Error("ordinary render failure")} />
      </WorkerErrorBoundary>,
    );

    expect(reload).not.toHaveBeenCalled();
    expect(screen.getByText("Boltrig couldn’t open.")).toBeTruthy();
    expect(screen.getByText("Your work is safe. Reload the app to try again.")).toBeTruthy();
  });

  it("clears an old recovery marker after a healthy private app mount", () => {
    sessionStorage.setItem(WORKER_CHUNK_RECOVERY_KEY, "old failure");

    render(
      <WorkerErrorBoundary>
        <div>Private workspace</div>
      </WorkerErrorBoundary>,
    );

    expect(screen.getByText("Private workspace")).toBeTruthy();
    expect(sessionStorage.getItem(WORKER_CHUNK_RECOVERY_KEY)).toBeNull();
  });
});
