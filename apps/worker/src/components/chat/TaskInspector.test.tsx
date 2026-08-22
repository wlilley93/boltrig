// @vitest-environment happy-dom

import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { NormalizedTurn } from "@wlilley93/boltrig-web-sdk";

import { TaskInspector } from "./TaskInspector";
import {
  buildTaskInspectorModel,
  hasTaskInspectorContent,
  taskInspectorStatus,
  type TaskInspectorViewModel,
} from "./TaskInspectorModel";

afterEach(cleanup);

const EMPTY_MODEL: TaskInspectorViewModel = {
  outputs: [],
  subagents: [],
  backgroundProcesses: [],
  computerUse: [],
  sources: [],
  runActivity: [],
};

const TURN: NormalizedTurn = {
  runId: "run-1",
  text: "",
  reasoning: "",
  tools: [
    {
      key: "tool-background",
      callId: "call-background",
      verb: "background_process.start",
      status: "pending",
      input: { command: "curl https://example.test/?token=secret-value" },
      output: { token: "result-secret" },
    },
    {
      key: "tool-computer",
      verb: "computer_use.picture_in_picture",
      status: "ok",
      input: { password: "never-render-this" },
    },
    {
      key: "tool-figma",
      verb: "figma.design.read",
      status: "grant_missing",
      input: { node: "sensitive-node" },
    },
  ],
  subagents: [{
    key: "agent-1",
    childRunId: "child-1",
    task: "Handle the private customer named Never Render Ltd",
    name: "Researcher",
    skills: [],
    status: "ok",
  }],
  hitls: [],
  questions: [], displayObjects: [],
  steps: [],
  timeline: [
    { kind: "tool", key: "tool-background", entry: {
      key: "tool-background",
      callId: "call-background",
      verb: "background_process.start",
      status: "pending",
    } },
    { kind: "tool", key: "tool-figma", entry: {
      key: "tool-figma",
      verb: "figma.design.read",
      status: "grant_missing",
    } },
  ],
  ended: true,
  cancelled: false,
  degraded: false,
};

describe("TaskInspector model", () => {
  it("projects only compact, safe contract fields", () => {
    const model = buildTaskInspectorModel({
      artifacts: [{
        id: "artifact-1",
        owner_id: "owner-1",
        name: "report.pdf",
        digest: "private-digest",
        media_type: "application/pdf",
        size: 4096,
        revision: 2,
        provenance: { kind: "tool", actor_ref: "private-actor" },
        created_at: "2026-08-12T00:00:00Z",
      }],
      integrationSources: [{
        id: "figma",
        label: "Figma",
        category: "storage_design",
        transport: "mcp",
        auth: ["oauth2"],
        description: "Private setup copy",
        certification: "certified",
      }],
      sources: [{
        name: "brief.txt",
        media_type: "text/plain",
        data: "c2VjcmV0LWF0dGFjaG1lbnQ=",
        size: 17,
      }],
      turn: TURN,
    });

    const projection = JSON.stringify(model);
    expect(projection).not.toContain("secret-value");
    expect(projection).not.toContain("result-secret");
    expect(projection).not.toContain("never-render-this");
    expect(projection).not.toContain("sensitive-node");
    expect(projection).not.toContain("private-digest");
    expect(projection).not.toContain("private-actor");
    expect(projection).not.toContain("Private setup copy");
    expect(projection).not.toContain("c2VjcmV0LWFjaG1lbnQ=");
    expect(projection).not.toContain("Never Render Ltd");
    expect(model.backgroundProcesses[0]?.label).toBe("Background process start");
    expect(model.computerUse[0]?.label).toBe("Computer use picture in picture");
    expect(model.runActivity[0]).toMatchObject({
      label: "Figma design read",
      status: "failed",
    });
  });

  it("reports whether any truthful group has content", () => {
    expect(hasTaskInspectorContent(EMPTY_MODEL)).toBe(false);
    expect(hasTaskInspectorContent({
      ...EMPTY_MODEL,
      runActivity: [{ id: "a", kind: "step", label: "Review", status: "done" }],
    })).toBe(true);
  });

  it("keeps skipped work neutral instead of reporting a failure", () => {
    expect(taskInspectorStatus("skipped")).toBe("skipped");
    const model: TaskInspectorViewModel = {
      ...EMPTY_MODEL,
      runActivity: [{ id: "skipped", kind: "step", label: "Optional review", status: "skipped" }],
    };
    render(<TaskInspector model={model} />);
    expect(screen.getByRole("img", { name: "Skipped" }).getAttribute("data-status"))
      .toBe("skipped");
    expect(document.querySelector('[data-tone="neutral"]')).toBeTruthy();
  });
});

describe("TaskInspector", () => {
  it("renders only populated groups and no conversation or governance furniture", () => {
    const model = buildTaskInspectorModel({ turn: TURN });
    render(<TaskInspector model={model} />);

    expect(screen.getByRole("region", { name: "Subagents" })).toBeTruthy();
    expect(document.querySelector(".task-inspector__mark--wide .rail-agent-stack"))
      .toBeTruthy();
    expect(screen.getByRole("region", { name: "Background processes" })).toBeTruthy();
    expect(screen.getByRole("region", { name: "Computer Use" })).toBeTruthy();
    expect(screen.getByRole("region", { name: "Run activity" })).toBeTruthy();
    expect(screen.getByRole("region", { name: "Outputs" }).textContent).toContain("No outputs");
    expect(screen.queryByRole("region", { name: "Sources" })).toBeNull();
    expect(screen.queryByText(/conversation/i)).toBeNull();
    expect(screen.queryByText(/governed by/i)).toBeNull();
  });

  it("shows the output capability only when its real action is supplied", () => {
    const onCreateOutput = vi.fn();
    render(<TaskInspector model={EMPTY_MODEL} onCreateOutput={onCreateOutput} />);
    fireEvent.click(screen.getByRole("button", { name: "Create a file or site" }));
    expect(onCreateOutput).toHaveBeenCalledOnce();
  });

  it("gives output pagination a stable accessible name", () => {
    const onLoadMoreOutputs = vi.fn();
    const view = render(
      <TaskInspector
        hasMoreOutputs
        model={EMPTY_MODEL}
        onLoadMoreOutputs={onLoadMoreOutputs}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Load more outputs" }));
    expect(onLoadMoreOutputs).toHaveBeenCalledOnce();

    view.rerender(
      <TaskInspector
        hasMoreOutputs
        model={EMPTY_MODEL}
        onLoadMoreOutputs={onLoadMoreOutputs}
        outputsLoading
      />,
    );
    expect(screen.getByRole("button", { name: "Loading more outputs" })).toBeTruthy();
  });

  it("resizes from the keyboard with bounded, announced values", () => {
    const onWidthChange = vi.fn();
    render(
      <TaskInspector
        defaultWidth={316}
        maxWidth={340}
        minWidth={280}
        model={{ ...EMPTY_MODEL, runActivity: [
          { id: "a", kind: "step", label: "Review", status: "done" },
        ] }}
        onWidthChange={onWidthChange}
      />,
    );
    const handle = screen.getByRole("separator", { name: "Resize task details" });
    expect(handle.getAttribute("aria-valuenow")).toBe("316");

    fireEvent.keyDown(handle, { key: "ArrowLeft" });
    expect(handle.getAttribute("aria-valuenow")).toBe("324");
    expect(onWidthChange).toHaveBeenLastCalledWith(324);

    fireEvent.keyDown(handle, { key: "ArrowLeft", shiftKey: true });
    expect(handle.getAttribute("aria-valuenow")).toBe("340");
    fireEvent.keyDown(handle, { key: "Home" });
    expect(handle.getAttribute("aria-valuenow")).toBe("280");
    expect(handle.getAttribute("aria-valuetext")).toBe("280 pixels wide");
  });

  it("resizes by dragging its left edge", () => {
    const onWidthChange = vi.fn();
    render(
      <TaskInspector
        model={{ ...EMPTY_MODEL, runActivity: [
          { id: "a", kind: "step", label: "Review", status: "done" },
        ] }}
        onWidthChange={onWidthChange}
      />,
    );
    const handle = screen.getByRole("separator", { name: "Resize task details" });
    fireEvent.pointerDown(handle, { button: 0, clientX: 500, pointerId: 7 });
    fireEvent.pointerMove(window, { clientX: 468, pointerId: 7 });
    fireEvent.pointerUp(window, { clientX: 468, pointerId: 7 });
    expect(onWidthChange).toHaveBeenLastCalledWith(348);
  });

  it("uses dialog, scrim, escape, focus trap and return-focus semantics in sheet mode", () => {
    const onClose = vi.fn();
    const trigger = document.createElement("button");
    trigger.textContent = "Details";
    document.body.append(trigger);
    trigger.focus();

    const model: TaskInspectorViewModel = {
      ...EMPTY_MODEL,
      outputs: [{
        id: "output-1",
        name: "report.pdf",
        mediaType: "application/pdf",
        revision: 1,
        size: 20,
      }],
    };
    const view = render(
      <TaskInspector mode="sheet" model={model} onClose={onClose} open />,
    );
    const dialog = screen.getByRole("dialog", { name: "Task details" });
    const close = within(dialog).getByRole("button", { name: "Close task details" });
    expect(document.activeElement).toBe(close);
    expect(screen.getAllByRole("button", { name: "Close task details" })).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Dismiss task details" })).toBeTruthy();

    fireEvent.keyDown(dialog, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(close);
    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(onClose).toHaveBeenCalledOnce();

    view.rerender(<TaskInspector mode="sheet" model={model} onClose={onClose} open={false} />);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(trigger);
    trigger.remove();
  });

  it("isolates every background branch and restores pre-existing modal state", () => {
    const background = document.createElement("section");
    background.setAttribute("aria-hidden", "false");
    background.dataset.testid = "outer-background";
    document.body.append(background);
    const alreadyIsolated = document.createElement("aside");
    alreadyIsolated.inert = true;
    alreadyIsolated.setAttribute("aria-hidden", "true");
    alreadyIsolated.dataset.testid = "already-isolated";
    document.body.append(alreadyIsolated);

    const view = render(
      <>
        <section aria-hidden="false" data-testid="inner-background">
          <button type="button">Background action</button>
        </section>
        <TaskInspector mode="sheet" model={EMPTY_MODEL} onClose={vi.fn()} open />
      </>,
    );

    const dialog = screen.getByRole("dialog", { name: "Task details" });
    const scrim = screen.getByRole("button", { name: "Dismiss task details" });
    const innerBackground = screen.getByTestId("inner-background");
    expect(dialog.inert).toBe(false);
    expect(scrim.inert).toBe(false);
    expect(innerBackground.inert).toBe(true);
    expect(innerBackground.getAttribute("aria-hidden")).toBe("true");
    expect(background.inert).toBe(true);
    expect(background.getAttribute("aria-hidden")).toBe("true");
    expect(alreadyIsolated.inert).toBe(true);
    expect(alreadyIsolated.getAttribute("aria-hidden")).toBe("true");
    expect(screen.queryByRole("button", { name: "Background action" })).toBeNull();

    view.rerender(
      <>
        <section aria-hidden="false" data-testid="inner-background">
          <button type="button">Background action</button>
        </section>
        <TaskInspector mode="sheet" model={EMPTY_MODEL} onClose={vi.fn()} open={false} />
      </>,
    );

    expect(screen.getByTestId("inner-background").inert).toBe(false);
    expect(screen.getByTestId("inner-background").getAttribute("aria-hidden")).toBe("false");
    expect(background.inert).toBe(false);
    expect(background.getAttribute("aria-hidden")).toBe("false");
    expect(alreadyIsolated.inert).toBe(true);
    expect(alreadyIsolated.getAttribute("aria-hidden")).toBe("true");
    background.remove();
    alreadyIsolated.remove();
  });

  it("recovers sheet keyboard handling when focus falls outside the dialog", () => {
    const onClose = vi.fn();
    render(<TaskInspector mode="sheet" model={EMPTY_MODEL} onClose={onClose} open />);
    document.body.tabIndex = -1;
    document.body.focus();
    expect(document.activeElement).toBe(document.body);

    fireEvent.keyDown(window, { key: "Tab" });
    expect(document.activeElement).toBe(screen.getByRole("button", {
      name: "Close task details",
    }));

    document.body.focus();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledOnce();
    document.body.removeAttribute("tabindex");
  });

  it("routes row actions without embedding backend behavior", () => {
    const onSelectActivity = vi.fn();
    const model: TaskInspectorViewModel = {
      ...EMPTY_MODEL,
      runActivity: [{ id: "activity-1", kind: "step", label: "Review", status: "done" }],
    };
    render(<TaskInspector model={model} onSelectActivity={onSelectActivity} />);
    fireEvent.click(screen.getByRole("button", { name: /Review/ }));
    expect(onSelectActivity).toHaveBeenCalledWith(model.runActivity[0]);
  });
});
