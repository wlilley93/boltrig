// @vitest-environment happy-dom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  invoke: vi.fn(),
  invokeApprovalState: vi.fn(),
}));

vi.mock("../src/client", () => ({ client: api }));

import { BrowserWorkspace } from "../src/components/browser/BrowserWorkspace";

const frame = {
  id: "frame_one",
  media_type: "image/jpeg",
  width: 1000,
  height: 700,
  url: "https://example.com",
  title: "Example",
  captured_at: "2026-08-15T12:00:00Z",
};

function installBrowserMock(clickStatus: "ok" | "stale_frame" = "ok") {
  api.invoke.mockImplementation(async (request) => {
    if (request.verb === "browser.tabs.list") {
      return { status: "ok", output: { tabs: [{ id: "tab_one", title: "Example", url: frame.url }] } };
    }
    if (request.verb === "browser.snapshot") {
      return { status: "ok", output: { status: "ok", frame } };
    }
    if (request.verb === "browser.frame.read") {
      return { status: "ok", output: { id: request.params.id, media_type: "image/jpeg", data: "\/9j\/2Q==".replaceAll("\\/", "/") } };
    }
    if (request.verb === "browser.click") {
      return {
        status: "ok",
        output: {
          status: clickStatus,
          frame: { ...frame, id: "frame_two" },
          ...(clickStatus === "ok" ? { cursor: { x: 500, y: 350, kind: "click" } } : {}),
        },
      };
    }
    return { status: "ok", output: {} };
  });
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("Browser workspace", () => {
  it("shows the bounded shared frame and maps clicks to exact viewport coordinates", async () => {
    installBrowserMock();
    render(<BrowserWorkspace />);

    const canvas = await screen.findByRole("button", { name: "Interact with Example" });
    canvas.getBoundingClientRect = () => ({
      left: 10, top: 20, width: 500, height: 350, right: 510, bottom: 370,
      x: 10, y: 20, toJSON: () => ({}),
    });
    fireEvent.click(canvas, { clientX: 260, clientY: 195 });

    await waitFor(() => expect(api.invoke).toHaveBeenCalledWith(expect.objectContaining({
      noun: "browser",
      verb: "browser.click",
      params: expect.objectContaining({
        expected_frame_id: "frame_one",
        name: "workspace",
        x: 500,
        y: 350,
      }),
    })));
    expect(document.querySelector(".browser-cursor.click")).toBeTruthy();
  });

  it("keeps edge clicks inside the captured frame and exposes bounded tab close", async () => {
    installBrowserMock();
    render(<BrowserWorkspace />);

    const canvas = await screen.findByRole("button", { name: "Interact with Example" });
    canvas.getBoundingClientRect = () => ({
      left: 10, top: 20, width: 500, height: 350, right: 510, bottom: 370,
      x: 10, y: 20, toJSON: () => ({}),
    });
    fireEvent.click(canvas, { clientX: 510, clientY: 370 });
    await waitFor(() => expect(api.invoke).toHaveBeenCalledWith(expect.objectContaining({
      verb: "browser.click",
      params: expect.objectContaining({ x: 999, y: 699 }),
    })));
    const close = screen.getByRole("button", { name: "Close Example tab" }) as HTMLButtonElement;
    await waitFor(() => expect(close.disabled).toBe(false));
    fireEvent.click(close);
    await waitFor(() => expect(api.invoke).toHaveBeenCalledWith(expect.objectContaining({
      verb: "browser.tab.close",
      params: expect.objectContaining({ target_id: "tab_one" }),
    })));
  });

  it("refreshes a stale frame without retrying the rejected click", async () => {
    installBrowserMock("stale_frame");
    render(<BrowserWorkspace />);
    const canvas = await screen.findByRole("button", { name: "Interact with Example" });
    canvas.getBoundingClientRect = () => ({
      left: 0, top: 0, width: 1000, height: 700, right: 1000, bottom: 700,
      x: 0, y: 0, toJSON: () => ({}),
    });
    fireEvent.click(canvas, { clientX: 10, clientY: 10 });

    await screen.findByText(/page changed before the action/i);
    expect(api.invoke.mock.calls.filter(([request]) => request.verb === "browser.click"))
      .toHaveLength(1);
    expect(document.querySelector(".browser-cursor")).toBeNull();
  });

  it("replays only the exact approved browser action", async () => {
    installBrowserMock();
    let clickCalls = 0;
    api.invoke.mockImplementation(async (request) => {
      if (request.verb === "browser.tabs.list") return { status: "ok", output: { tabs: [] } };
      if (request.verb === "browser.snapshot") return { status: "ok", output: { status: "ok", frame } };
      if (request.verb === "browser.frame.read") return { status: "ok", output: { id: frame.id, media_type: "image/jpeg", data: "/9j/2Q==" } };
      if (request.verb === "browser.click") {
        clickCalls += 1;
        if (clickCalls === 1) return { status: "pending_human", hitl_request_id: "approval_one" };
        return { status: "ok", output: { status: "ok", frame, cursor: { x: 10, y: 10, kind: "click" } } };
      }
      return { status: "error", reason: "unexpected" };
    });
    api.invokeApprovalState.mockResolvedValue({ status: "approved" });
    render(<BrowserWorkspace />);

    const canvas = await screen.findByRole("button", { name: "Interact with Example" });
    canvas.getBoundingClientRect = () => ({
      left: 0, top: 0, width: 1000, height: 700, right: 1000, bottom: 700,
      x: 0, y: 0, toJSON: () => ({}),
    });
    fireEvent.click(canvas, { clientX: 10, clientY: 10 });
    fireEvent.click(await screen.findByRole("button", { name: /check approval and apply/i }));

    await waitFor(() => expect(clickCalls).toBe(2));
    const replay = api.invoke.mock.calls.map(([request]) => request)
      .find((request) => request.verb === "browser.click" && request.approval_id);
    expect(replay).toEqual(expect.objectContaining({ approval_id: "approval_one" }));
    expect(replay.params.expected_frame_id).toBe("frame_one");
  });
});
