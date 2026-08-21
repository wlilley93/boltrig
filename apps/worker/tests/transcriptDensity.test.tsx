// @vitest-environment happy-dom

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type {
  NormalizedTurn,
  SubagentEntry,
  ToolEntry,
} from "@wlilley93/boltrig-web-sdk";

import { SubagentChips } from "../src/components/chat/SubagentChips";
import { WorkDisclosure } from "../src/components/chat/WorkDisclosure";

afterEach(cleanup);

const EMPTY_TURN: NormalizedTurn = {
  text: "",
  reasoning: "",
  tools: [],
  subagents: [],
  hitls: [],
  questions: [],
  displayObjects: [],
  steps: [],
  timeline: [],
  ended: false,
  cancelled: false,
  degraded: false,
};

function tool(verb: string, status = "ok"): ToolEntry {
  return { key: `${verb}-${status}`, verb, status };
}

function agent(patch: Partial<SubagentEntry>): SubagentEntry {
  return {
    key: "agent-a",
    childRunId: "run-a",
    task: "Read account health",
    skills: [],
    ...patch,
  };
}

describe("compact transcript activity", () => {
  it("deduplicates honest tool categories into one natural-language row", () => {
    const tools = [
      tool("figma.get_design_context"),
      tool("file.read"),
      tool("file.open"),
      tool("apply_patch"),
      tool("exec_command"),
    ];
    render(<WorkDisclosure turn={{ ...EMPTY_TURN, tools }} />);

    const text = screen.getByText(
      "Used Figma integration, read files, edited files, ran commands",
    );
    const details = text.closest("details");
    const summary = text.closest("summary");
    expect(details?.open).toBe(false);
    expect(summary?.getAttribute("aria-label")).toContain("5 tool details");
    expect(summary?.querySelector(".transcript-tool-glyph")?.getAttribute("data-kind"))
      .toBe("figma");
    expect(summary?.querySelectorAll(".transcript-tool-glyph path")).toHaveLength(4);
    expect(summary?.querySelector(":scope > svg")).toBeNull();
    summary?.focus();
    expect(document.activeElement).toBe(summary);
    expect(document.querySelector(".work-rule")).toBeNull();
    expect(document.querySelector(".activity-row")).toBeNull();

    fireEvent.click(summary!);
    expect(details?.open).toBe(true);
    expect(screen.getByRole("list", { name: "Exact tool details" })
      .querySelectorAll("[role=listitem]")).toHaveLength(5);
    expect(screen.getByText("figma.get_design_context")).toBeTruthy();
    expect(screen.getByText("exec_command")).toBeTruthy();
  });

  it("keeps real pending and failed tool states visible without claiming completion", () => {
    render(
      <WorkDisclosure
        turn={{
          ...EMPTY_TURN,
          tools: [tool("file.read", "pending"), tool("custom.tool", "error")],
        }}
      />,
    );

    expect(screen.getByText("Read files, used 1 other tool")).toBeTruthy();
    expect(screen.queryByText(/custom\.tool/, { selector: "summary *" })).toBeNull();
    expect(screen.getByText("working, 1 did not complete")).toBeTruthy();
    expect(document.querySelector("[data-tone=red]")).toBeTruthy();
  });

  it("shows every subagent once as a focusable chip with its real status", () => {
    const lyell = agent({ key: "lyell", childRunId: "run-lyell", name: "Lyell", status: "ok" });
    const hutton = agent({ key: "hutton", childRunId: "run-hutton", name: "Hutton", status: "running" });
    const noether = agent({ key: "noether", childRunId: "run-noether", name: "Noether", status: "error" });
    const onOpenSubagent = vi.fn();
    render(
      <SubagentChips
        onOpenSubagent={onOpenSubagent}
        subagents={[lyell, hutton, noether]}
        tech={false}
        turnEnded={false}
      />,
    );

    expect(document.querySelector(".subagent-fanout")).toBeNull();
    expect(document.querySelectorAll("button.transcript-subagent-chip")).toHaveLength(3);
    expect(screen.getByText("1 updated, 1 working, 1 failed")).toBeTruthy();
    expect(document.querySelectorAll(".transcript-subagent-group-state")).toHaveLength(1);
    for (const chip of document.querySelectorAll(".transcript-subagent-chip")) {
      expect(chip.textContent).not.toMatch(/updated|working|failed/);
    }

    const lyellButton = screen.getByRole("button", { name: /Open subagent Lyell/ });
    lyellButton.focus();
    expect(document.activeElement).toBe(lyellButton);
    fireEvent.click(lyellButton);
    expect(onOpenSubagent).toHaveBeenCalledWith(lyell);
  });

  it("does not invent a state or a clickable action for missing settled facts", () => {
    render(
      <SubagentChips
        subagents={[agent({ name: undefined, status: undefined })]}
        tech={false}
        turnEnded
      />,
    );

    const chip = screen.getByText("Read account health").closest(".transcript-subagent-chip");
    expect(chip?.tagName).toBe("SPAN");
    expect(chip?.hasAttribute("aria-label")).toBe(false);
    expect(chip?.textContent).not.toContain("updated");
    expect(chip?.textContent).not.toContain("working");
    expect(screen.queryByRole("button")).toBeNull();
    expect(document.querySelector(".transcript-subagent-group-state")).toBeNull();
  });

  it("shows one shared settled state after a completed chip group", () => {
    render(
      <SubagentChips
        subagents={[
          agent({ key: "lyell", name: "Lyell", status: "ok" }),
          agent({ key: "hutton", name: "Hutton", status: "ok" }),
        ]}
        tech={false}
        turnEnded
      />,
    );

    expect(screen.getByText("updated")).toBeTruthy();
    expect(document.querySelectorAll(".transcript-subagent-group-state")).toHaveLength(1);
    expect(document.querySelectorAll(".transcript-subagent-chip")).toHaveLength(2);
    expect(document.querySelectorAll(".transcript-subagent-chip .transcript-subagent-sr"))
      .toHaveLength(2);
    expect(document.querySelector(".transcript-subagent-chip .transcript-subagent-sr")?.textContent)
      .toContain("updated");
  });
});
