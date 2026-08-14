// @vitest-environment happy-dom

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ChatMessage, StepEntry } from "@wlilley93/boltrig-web-sdk";

import { QueuedMessages, RunProgress } from "../src/components/chat/QueuedMessages";

afterEach(cleanup);

function step(stepId: string, action: string, status: StepEntry["status"]): StepEntry {
  return { stepId, action, status };
}

function message(patch: Partial<ChatMessage>): ChatMessage {
  return {
    id: "queued-1",
    role: "user",
    content: "Review the release checks",
    created_at: "2026-08-14T08:00:00Z",
    ...patch,
  };
}

describe("run progress", () => {
  it("shows the real current step and expands the complete kernel step list", () => {
    render(<RunProgress steps={[
      step("audit", "Audit the current surface", "ok"),
      step("build", "Implement the compact queue", "ok"),
      step("verify", "Verify visual and runtime behaviour", "running"),
      step("release", "Rebuild the desktop app", "paused"),
    ]} />);

    const summary = screen.getByText("Step 3 / 4").closest("summary");
    expect(summary?.getAttribute("aria-label")).toBe("Step 3 / 4. In progress. Run steps");
    expect(summary?.closest("details")?.open).toBe(false);
    fireEvent.click(summary!);
    expect(summary?.closest("details")?.open).toBe(true);
    expect(screen.getByRole("list", { name: "Run steps" }).children).toHaveLength(4);
    expect(screen.getByText("Verify visual and runtime behaviour")).toBeTruthy();
    expect(screen.getByText("In progress")).toBeTruthy();
    expect(screen.queryByText(/files changed/i)).toBeNull();
  });

  it("uses a settled label only when every published step settled safely", () => {
    render(<RunProgress steps={[
      step("audit", "Audit", "ok"),
      step("optional", "Optional check", "skipped"),
    ]} />);

    expect(screen.getByText("2 / 2 finished")).toBeTruthy();
    expect(document.querySelector('.run-progress-ring[data-tone="done"]')).toBeTruthy();
  });

  it("does not present a failed current step as running", () => {
    render(<RunProgress steps={[
      step("audit", "Audit", "ok"),
      step("verify", "Verify", "failed"),
    ]} />);

    expect(screen.getByLabelText("Step 2 / 2. Failed. Run steps")).toBeTruthy();
    expect(document.querySelector('.run-progress-ring[data-tone="failed"]')).toBeTruthy();
    expect(document.querySelector('.run-progress-ring[data-tone="running"]')).toBeNull();
  });
});

describe("queued messages", () => {
  it("keeps every queued turn thin, previewable and steerable", () => {
    const onSteer = vi.fn();
    const image = message({
      id: "queued-image",
      content: "",
      attachments: [
        { name: "one.png", media_type: "image/png", data: "aW1hZ2U=", size: 5 },
        { name: "two.png", media_type: "image/png", data: "aW1hZ2U=", size: 5 },
      ],
    });
    render(<QueuedMessages messages={[message({}), image]} onSteer={onSteer} />);

    const region = screen.getByRole("region", { name: "Queued messages" });
    expect(region.querySelectorAll(".queued-message")).toHaveLength(2);
    expect(screen.getByText("2 images")).toBeTruthy();
    expect(region.querySelector(".queued-message-preview img")?.getAttribute("src"))
      .toBe("data:image/png;base64,aW1hZ2U=");

    fireEvent.click(screen.getByRole("button", { name: "Steer queued message: 2 images" }));
    expect(onSteer).toHaveBeenCalledWith(image);
    expect(screen.queryByRole("button", { name: /remove queued/i })).toBeNull();
  });

  it("reorders the complete queue by keyboard and announces the new position", () => {
    const onReorder = vi.fn();
    const first = message({ id: "queued-first", content: "First instruction" });
    const second = message({ id: "queued-second", content: "Second instruction" });
    render(
      <QueuedMessages
        messages={[first, second]}
        onReorder={onReorder}
        onSteer={vi.fn()}
      />,
    );

    fireEvent.keyDown(
      screen.getByRole("button", { name: "Reorder queued message: First instruction" }),
      { key: "ArrowDown" },
    );
    expect(onReorder).toHaveBeenCalledWith(
      ["queued-first", "queued-second"],
      ["queued-second", "queued-first"],
    );
    expect(screen.getByText("First instruction moved to position 2 of 2.")).toBeTruthy();
  });

  it("supports pointer drag without adding a fictional queue mutation", () => {
    const onReorder = vi.fn();
    const first = message({ id: "queued-first", content: "First instruction" });
    const second = message({ id: "queued-second", content: "Second instruction" });
    render(
      <QueuedMessages
        messages={[first, second]}
        onReorder={onReorder}
        onSteer={vi.fn()}
      />,
    );
    const dataTransfer = { effectAllowed: "none", setData: vi.fn() };
    fireEvent.dragStart(
      screen.getByRole("button", { name: "Reorder queued message: First instruction" }),
      { dataTransfer },
    );
    fireEvent.dragOver(document.querySelector('[data-message-id="queued-second"]')!, {
      dataTransfer,
    });
    fireEvent.drop(document.querySelector('[data-message-id="queued-second"]')!, {
      dataTransfer,
    });

    expect(dataTransfer.setData).toHaveBeenCalledWith("text/plain", "queued-first");
    expect(onReorder).toHaveBeenCalledWith(
      ["queued-first", "queued-second"],
      ["queued-second", "queued-first"],
    );
  });
});
