// @vitest-environment happy-dom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const native = vi.hoisted(() => ({
  checkDesktopUpdate: vi.fn(),
  desktopUpdateReadiness: vi.fn(),
  installDesktopUpdate: vi.fn(),
  restartDesktopAfterUpdate: vi.fn(),
}));

vi.mock("../src/desktop", () => native);

import { DesktopUpdater } from "../src/components/DesktopUpdater";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

beforeEach(() => {
  native.desktopUpdateReadiness.mockResolvedValue({
    runtime: "desktop",
    state: "ready",
    current_version: "0.1.0",
    target: "linux-x86_64",
    endpoint_origin: "https://releases.boltrig.test",
    public_key_fingerprint: "f".repeat(64),
    reason: null,
  });
});

describe("signed desktop updater", () => {
  it("keeps browser sessions explicitly unavailable", async () => {
    native.desktopUpdateReadiness.mockResolvedValue({
      runtime: "web",
      state: "unavailable",
      current_version: null,
      target: null,
      endpoint_origin: null,
      public_key_fingerprint: null,
      reason: "desktop_runtime_required",
    });

    render(<DesktopUpdater />);

    await screen.findByText("Updates unavailable");
    expect(screen.getByText(/unavailable in a browser/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Check for updates" })).toBeNull();
    expect(native.checkDesktopUpdate).not.toHaveBeenCalled();
  });

  it("checks, downloads, installs, and restarts one reported signed version", async () => {
    native.checkDesktopUpdate.mockResolvedValue({
      status: "available",
      current_version: "0.1.0",
      version: "0.2.0",
      notes: "Security and reliability update.",
      published_at: "2030-01-01T00:00:00Z",
    });
    native.installDesktopUpdate.mockImplementation(
      async (_version: string, onProgress: (event: unknown) => void) => {
        onProgress({ event: "started", content_length: 100 });
        onProgress({ event: "progress", chunk_length: 40 });
        onProgress({ event: "progress", chunk_length: 60 });
        onProgress({ event: "download_finished" });
      },
    );
    native.restartDesktopAfterUpdate.mockResolvedValue(undefined);

    render(<DesktopUpdater />);
    fireEvent.click(await screen.findByRole("button", {
      name: "Check for updates",
    }));
    await screen.findByText("Update available");
    expect(screen.getByText("Version 0.2.0")).toBeTruthy();
    expect(screen.getByText("https://releases.boltrig.test")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", {
      name: "Download, verify and install",
    }));
    await screen.findByText("Restart required");
    expect(native.installDesktopUpdate).toHaveBeenCalledWith(
      "0.2.0",
      expect.any(Function),
    );
    fireEvent.click(screen.getByRole("button", { name: "Restart Worker" }));
    await waitFor(() => expect(native.restartDesktopAfterUpdate).toHaveBeenCalled());
  });

  it("does not infer installation after a failed signed download", async () => {
    native.checkDesktopUpdate.mockResolvedValue({
      status: "available",
      current_version: "0.1.0",
      version: "0.2.0",
      notes: null,
      published_at: null,
    });
    native.installDesktopUpdate.mockRejectedValue(
      new Error("update_install_failed"),
    );

    render(<DesktopUpdater />);
    fireEvent.click(await screen.findByRole("button", {
      name: "Check for updates",
    }));
    fireEvent.click(await screen.findByRole("button", {
      name: "Download, verify and install",
    }));

    await screen.findByText("Update did not complete");
    expect(screen.getByText(/current version/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Restart Worker" })).toBeNull();
  });

  it("does not claim signature verification at download completion", async () => {
    native.checkDesktopUpdate.mockResolvedValue({
      status: "available",
      current_version: "0.1.0",
      version: "0.2.0",
      notes: null,
      published_at: null,
    });
    let finishInstall: (() => void) | undefined;
    native.installDesktopUpdate.mockImplementation(
      async (_version: string, onProgress: (event: unknown) => void) => {
        onProgress({ event: "download_finished" });
        await new Promise<void>((resolve) => {
          finishInstall = resolve;
        });
      },
    );

    render(<DesktopUpdater />);
    fireEvent.click(await screen.findByRole("button", {
      name: "Check for updates",
    }));
    fireEvent.click(await screen.findByRole("button", {
      name: "Download, verify and install",
    }));

    expect(await screen.findByText(
      "Download complete. Verifying and installing the update…",
    )).toBeTruthy();
    expect(screen.queryByText(/Signature verified/i)).toBeNull();
    finishInstall?.();
    await screen.findByText("Restart required");
  });
});
