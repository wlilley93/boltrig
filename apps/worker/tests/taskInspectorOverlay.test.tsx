// @vitest-environment happy-dom

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { TaskInspector } from "../src/components/chat/TaskInspector";
import type { TaskInspectorViewModel } from "../src/components/chat/TaskInspectorModel";

afterEach(cleanup);

const EMPTY_MODEL: TaskInspectorViewModel = {
  outputs: [],
  subagents: [],
  backgroundProcesses: [],
  computerUse: [],
  sources: [],
  runActivity: [],
};

it("opens as a non-modal overlay without isolating the chat", () => {
  const onClose = vi.fn();
  const view = render(
    <>
      <section><button type="button">Keep working</button></section>
      <TaskInspector mode="overlay" model={EMPTY_MODEL} onClose={onClose} open />
    </>,
  );

  expect(screen.getByRole("complementary", { name: "Task details" })).toBeTruthy();
  expect(screen.getByRole("button", { name: "Keep working" })).toBeTruthy();
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(screen.queryByRole("button", { name: "Dismiss task details" })).toBeNull();
  expect(document.body.style.overflow).toBe("");

  fireEvent.keyDown(window, { key: "Escape" });
  expect(onClose).toHaveBeenCalledOnce();
  view.rerender(
    <TaskInspector mode="overlay" model={EMPTY_MODEL} onClose={onClose} open={false} />,
  );
  expect(screen.queryByRole("complementary", { name: "Task details" })).toBeNull();
  expect(document.getElementById("worker-task-details")?.hasAttribute("inert")).toBe(true);
});
