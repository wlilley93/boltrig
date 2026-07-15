import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PrototypeApp } from "@/prototype/PrototypeApp";

function move(hash: string) {
  window.location.hash = hash;
  window.dispatchEvent(new Event("hashchange"));
}

describe("organisation OS prototype", () => {
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  beforeEach(() => {
    Object.defineProperty(window, "innerWidth", { configurable: true, value: 1024 });
    localStorage.clear();
    move("#/prototype/home");
  });

  it("presents one coherent organisation pulse", () => {
    render(<PrototypeApp />);
    expect(screen.getByText("Good morning, Will.")).toBeTruthy();
    expect(screen.getAllByText("Launch the governed automation beta").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Research Scout T3-A19F").length).toBeGreaterThan(0);
    expect(screen.getByRole("navigation", { name: "Primary navigation" })).toBeTruthy();
  });

  it("creates a goal in deterministic prototype state", () => {
    move("#/prototype/goals");
    render(<PrototypeApp />);
    fireEvent.click(screen.getByRole("button", { name: "New goal" }));
    fireEvent.change(screen.getByPlaceholderText("What should change?"), { target: { value: "Reach five governed pilots" } });
    fireEvent.click(screen.getByRole("button", { name: "Create goal" }));
    expect(screen.getAllByText("Reach five governed pilots").length).toBeGreaterThan(0);
  });

  it("records an explicit approval decision", () => {
    move("#/prototype/approvals");
    render(<PrototypeApp />);
    fireEvent.click(screen.getByRole("button", { name: "Review approval: Publish customer-facing beta summary" }));
    fireEvent.click(screen.getByRole("button", { name: "Approve intentionally" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm approval" }));
    expect(screen.getAllByText("approved").length).toBeGreaterThan(0);
  });

  it("turns a chat into governed work, a specialist team and a reusable workflow", () => {
    move("#/prototype/chat");
    render(<PrototypeApp />);
    expect(screen.getByText("Turn our design-partner research into a repeatable weekly evidence brief. Delegate the analysis and make sure nothing publishes without a human.")).toBeTruthy();
    expect(screen.getByText("Delegated to two specialists")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Spawn specialist team" }));
    expect(screen.getByRole("button", { name: "Team prepared" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Save as workflow" }));
    expect(screen.getByRole("button", { name: "Workflow saved" })).toBeTruthy();
    fireEvent.change(screen.getByRole("textbox", { name: "Message Bolt" }), { target: { value: "Create the review task" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    expect(screen.getByText("Create the review task")).toBeTruthy();
  });

  it("keeps the active conversation stable while inspecting its connected run", () => {
    move("#/prototype/chat");
    render(<PrototypeApp />);
    fireEvent.click(screen.getByRole("button", { name: "Prepare the production readiness review Operations · 24 min" }));
    expect(screen.getByRole("heading", { level: 1, name: "Prepare the production readiness review" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Inspect run-2044" }));
    expect(screen.getByRole("heading", { level: 1, name: "Prepare the production readiness review" })).toBeTruthy();
  });

  it("opens and closes the connected run inspector on mobile", () => {
    Object.defineProperty(window, "innerWidth", { configurable: true, value: 390 });
    move("#/prototype/chat");
    render(<PrototypeApp />);
    expect(screen.queryByRole("dialog", { name: "Customer evidence synthesis" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Inspect connected run run-2048" }));
    expect(screen.getByRole("dialog", { name: "Customer evidence synthesis" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Close inspector" }));
    expect(screen.queryByRole("dialog", { name: "Customer evidence synthesis" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Inspect connected run run-2048" }));
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Close inspector" }));
    act(() => move("#/prototype/work"));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("keeps stopped run and worker state consistent across chat and inspector", () => {
    move("#/prototype/chat");
    render(<PrototypeApp />);
    fireEvent.click(screen.getByRole("button", { name: "Stop run" }));
    expect(screen.getByText("Stopped")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Inspect connected run run-2048" }));
    expect(screen.getAllByText("stopped").length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("button", { name: "RS Research Scout Reviewing interview 8 of 12 £0.84" }));
    expect(screen.getByText("Stopped at the run checkpoint")).toBeTruthy();
  });

  it("preserves the selected conversation when leaving and returning to Chat", () => {
    move("#/prototype/chat");
    render(<PrototypeApp />);
    fireEvent.click(screen.getByRole("button", { name: "Prepare the production readiness review Operations · 24 min" }));
    act(() => move("#/prototype/work"));
    act(() => move("#/prototype/chat"));
    expect(screen.getByRole("heading", { level: 1, name: "Prepare the production readiness review" })).toBeTruthy();
  });

  it("keeps approval status and confirmation semantics consistent", () => {
    move("#/prototype/chat");
    render(<PrototypeApp />);
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    expect(screen.getByRole("group", { name: "Confirm retention approval" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Confirm approval" }));
    expect(screen.queryByText("Needs you")).toBeNull();
    expect(screen.getByText("Recorded")).toBeTruthy();
  });

  it("requires inspector decisions to be confirmed", () => {
    move("#/prototype/approvals");
    render(<PrototypeApp />);
    fireEvent.click(screen.getByRole("button", { name: "Review approval: Publish customer-facing beta summary" }));
    fireEvent.click(screen.getByRole("button", { name: "Approve intentionally" }));
    expect(screen.getByRole("group", { name: "Confirm approval for Publish customer-facing beta summary" })).toBeTruthy();
    expect(screen.getAllByText("pending").length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("button", { name: "Confirm approval" }));
    expect(screen.getAllByText("approved").length).toBeGreaterThan(0);
  });

  it("clears an armed inspector decision when context changes", () => {
    move("#/prototype/approvals");
    render(<PrototypeApp />);
    fireEvent.click(screen.getByRole("button", { name: "Review approval: Publish customer-facing beta summary" }));
    fireEvent.click(screen.getByRole("button", { name: "Approve intentionally" }));
    expect(screen.getByRole("group", { name: "Confirm approval for Publish customer-facing beta summary" })).toBeTruthy();
    act(() => move("#/prototype/work"));
    act(() => move("#/prototype/approvals"));
    expect(screen.queryByRole("group", { name: "Confirm approval for Publish customer-facing beta summary" })).toBeNull();
    expect(screen.getByRole("button", { name: "Approve intentionally" })).toBeTruthy();
  });

  it("uses disclosure keyboard behavior for conversation actions", () => {
    move("#/prototype/chat");
    render(<PrototypeApp />);
    const trigger = screen.getByRole("button", { name: "Conversation options" });
    fireEvent.click(trigger);
    const actions = screen.getByRole("group", { name: "Conversation actions" });
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Rename" }));
    fireEvent.keyDown(actions, { key: "Escape" });
    expect(screen.queryByRole("group", { name: "Conversation actions" })).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });

  it("filters conversations and does not run global shortcuts while typing", () => {
    move("#/prototype/chat");
    render(<PrototypeApp />);
    fireEvent.change(screen.getByRole("textbox", { name: "Search Chat" }), { target: { value: "readiness" } });
    expect(screen.getByRole("button", { name: "Prepare the production readiness review Operations · 24 min" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Turn research into a weekly evidence brief Bolt · Now" })).toBeNull();
    const composer = screen.getByRole("textbox", { name: "Message Bolt" });
    composer.focus();
    fireEvent.keyDown(composer, { key: "b", metaKey: true });
    fireEvent.keyDown(composer, { key: "1", metaKey: true });
    expect(window.location.hash).toBe("#/prototype/chat");
    expect(screen.getByRole("complementary", { name: "Chat navigator" })).toBeTruthy();
  });

  it("keeps the newest notification for its full timeout", () => {
    vi.useFakeTimers();
    move("#/prototype/chat");
    render(<PrototypeApp />);
    fireEvent.click(screen.getByRole("button", { name: "Spawn specialist team" }));
    act(() => vi.advanceTimersByTime(1000));
    fireEvent.click(screen.getByRole("button", { name: "Save as workflow" }));
    act(() => vi.advanceTimersByTime(1600));
    expect(screen.getByRole("status").textContent).toContain("Workflow draft saved");
    act(() => vi.advanceTimersByTime(1000));
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("supports the desktop light and dark companion themes", () => {
    const { container } = render(<PrototypeApp />);
    expect(container.querySelector(".proto-app--light")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Toggle theme" }));
    expect(container.querySelector(".proto-app--dark")).toBeTruthy();
  });
});
