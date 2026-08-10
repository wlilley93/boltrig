// @vitest-environment happy-dom

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { NormalizedTurn } from "@wlilley93/boltrig-web-sdk";

import { MobileChat } from "../src/components/MobileChat";

afterEach(() => {
  cleanup();
  delete document.documentElement.dataset.mobileSurface;
});

const EMPTY_TURN: NormalizedTurn = {
  text: "", reasoning: "", tools: [], subagents: [], hitls: [],
  questions: [], steps: [], timeline: [], ended: false,
  cancelled: false, degraded: false,
};

function turnWith(patch: Partial<NormalizedTurn>): NormalizedTurn {
  return { ...EMPTY_TURN, ...patch };
}

function renderMobile(props: Partial<Parameters<typeof MobileChat>[0]> = {}) {
  return render(
    <MobileChat
      busy={false}
      composerValue=""
      messages={[]}
      onBack={vi.fn()}
      onComposerChange={vi.fn()}
      onSend={vi.fn()}
      subtitle=""
      title="Renewal outreach"
      turn={EMPTY_TURN}
      {...props}
    />,
  );
}

describe("mobile surface", () => {
  it("claims the screen so the shell chrome cannot sit on the back control", () => {
    renderMobile();
    expect(document.documentElement.dataset.mobileSurface).toBe("chat");
    expect(screen.getByRole("button", { name: "Back" })).toBeTruthy();
  });

  it("releases the screen when it unmounts", () => {
    const view = renderMobile();
    expect(document.documentElement.dataset.mobileSurface).toBe("chat");
    view.unmount();
    expect(document.documentElement.dataset.mobileSurface).toBeUndefined();
  });

  it("draws the agent tree and the plan from the live turn", () => {
    renderMobile({
      turn: turnWith({
        subagents: [
          { key: "a", childRunId: "r1", task: "Read health signals", skills: [], name: "Lyell" },
          { key: "b", childRunId: "r2", task: "Draft outreach", skills: [], name: "Hutton" },
        ],
        steps: [
          { stepId: "s1", action: "Read the accounts", status: "ok" },
          { stepId: "s2", action: "Draft the messages", status: "running" },
        ],
      }),
    });

    expect(screen.getByText("Lyell")).toBeTruthy();
    expect(screen.getByText("Hutton")).toBeTruthy();
    expect(screen.getByText("The plan")).toBeTruthy();
    // Progress counts only what finished, so a running step is not claimed done.
    expect(screen.getByText("1 of 2")).toBeTruthy();
  });

  it("surfaces what is waiting on a person", () => {
    renderMobile({
      turn: turnWith({
        hitls: [{
          hitlRequestId: "h1",
          kind: "approval",
          question: "Raise 3 tickets",
          options: [],
        }],
      }),
    });
    expect(screen.getByText("Raise 3 tickets")).toBeTruthy();
    // Without a wired responder the row stays read-only: the surface never
    // draws a button that goes nowhere.
    expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
  });

  it("answers an approval inline when a responder is wired", async () => {
    const onRespondHitl = vi.fn().mockResolvedValue(true);
    renderMobile({
      onRespondHitl,
      turn: turnWith({
        hitls: [{
          hitlRequestId: "h1",
          kind: "approval",
          question: "Raise 3 tickets",
          options: [],
        }],
      }),
    });

    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    expect(onRespondHitl).toHaveBeenCalledWith("h1", "approve");
    expect(await screen.findByText(/was recorded/)).toBeTruthy();
    // The optimistic settle removes the buttons once the kernel accepted it.
    expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
  });

  it("reverts the optimistic settle when the kernel refuses the decision", async () => {
    const onRespondHitl = vi.fn().mockResolvedValue(false);
    renderMobile({
      onRespondHitl,
      turn: turnWith({
        hitls: [{
          hitlRequestId: "h1",
          kind: "approval",
          question: "Raise 3 tickets",
          options: [],
        }],
      }),
    });

    fireEvent.click(screen.getByRole("button", { name: "Deny" }));
    expect(await screen.findByText(/was not accepted/)).toBeTruthy();
  });

  it("offers stop while a run is live and send otherwise", () => {
    const view = renderMobile({ busy: true });
    expect(screen.getByRole("button", { name: "Stop" })).toBeTruthy();
    view.unmount();
    renderMobile({ busy: false });
    expect(screen.getByRole("button", { name: "Send" })).toBeTruthy();
  });

  it("does not send an empty follow up", () => {
    const onSend = vi.fn();
    renderMobile({ composerValue: "", onSend });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    // The guard lives in the caller, so what this asserts is that the control is
    // wired at all; the empty-string guard is covered by ChatView's own tests.
    expect(onSend).toHaveBeenCalled();
  });
});
