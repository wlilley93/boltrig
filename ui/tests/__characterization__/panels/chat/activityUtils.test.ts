import { describe, expect, it } from "vitest";

import { buildTimelineNodes } from "@/panels/chat/activityUtils";
import type { NormalizedTurn } from "@/panels/chatTurn";

const emptyTurn: NormalizedTurn = {
  text: "",
  reasoning: "",
  tools: [],
  subagents: [],
  hitls: [],
  questions: [],
  steps: [],
  ended: false,
  cancelled: false,
};

describe("activityUtils (per-event-type shape, brief sec 13.1)", () => {
  it("session start: 8px cyan dot, no avatar, 500 weight label", () => {
    const nodes = buildTimelineNodes({
      messages: [],
      live: emptyTurn,
      activeAgentColor: "#5E69DD",
      activeAgentName: "Head of Engineering",
    });
    const session = nodes[0];
    expect(session.key).toBe("session");
    expect(session.dotSize).toBe(8);
    expect(session.dotColor).toBe("#3DD3F0");
    expect(session.hasAvatar).toBe(false);
    expect(session.labelWeight).toBe(500);
  });

  it("pending: 8px cyan dot, no avatar, hasLine false", () => {
    const nodes = buildTimelineNodes({
      messages: [],
      live: emptyTurn,
      activeAgentColor: "#3DD3F0",
      activeAgentName: "Bolt",
    });
    const pending = nodes[nodes.length - 1];
    expect(pending.key).toBe("pending");
    expect(pending.dotSize).toBe(8);
    expect(pending.dotColor).toBe("#3DD3F0");
    expect(pending.hasLine).toBe(false);
    expect(pending.hasAvatar).toBeFalsy();
  });

  it("agent action: 12px dot with 2px #04060D border + 20px avatar, 600 weight", () => {
    const live: NormalizedTurn = { ...emptyTurn, runId: "r1", text: "working" };
    const nodes = buildTimelineNodes({
      messages: [],
      live,
      activeAgentColor: "#5E69DD",
      activeAgentName: "Head of Engineering",
    });
    const agent = nodes.find((n) => n.badge === "agent");
    expect(agent).toBeTruthy();
    expect(agent!.dotSize).toBe(12);
    expect(agent!.dotExtra).toBe("2px solid #04060D");
    expect(agent!.hasAvatar).toBe(true);
    expect(agent!.avatarSize).toBe(20);
    expect(agent!.avatarColor).toBe("#5E69DD");
    expect(agent!.labelWeight).toBe(600);
    expect(agent!.labelColor).toBe("#5E69DD");
  });

  it("tool call: 7px dot, no avatar, 400 weight, shows receipt id", () => {
    const live: NormalizedTurn = {
      ...emptyTurn,
      runId: "r1",
      tools: [{ key: "t0", callId: "call-9", verb: "search", status: "ok" }],
    };
    const nodes = buildTimelineNodes({
      messages: [],
      live,
      activeAgentColor: "#3DD3F0",
      activeAgentName: "Bolt",
    });
    const agent = nodes.find((n) => n.badge === "agent")!;
    const tool = agent.children!.find((c) => c.badge === "tool");
    expect(tool).toBeTruthy();
    expect(tool!.dotSize).toBe(7);
    expect(tool!.hasAvatar).toBe(false);
    expect(tool!.labelWeight).toBe(400);
    expect(tool!.detail).toContain("call-9");
  });

  it("ephemeral spawn: 9px dot with 2px border + 16px avatar, 500 weight", () => {
    const live: NormalizedTurn = {
      ...emptyTurn,
      runId: "r1",
      subagents: [{ key: "s0", childRunId: "sub-1", task: "check deps", skills: ["deps-scan"] }],
    };
    const nodes = buildTimelineNodes({
      messages: [],
      live,
      activeAgentColor: "#3DD3F0",
      activeAgentName: "Bolt",
    });
    const agent = nodes.find((n) => n.badge === "agent")!;
    const delegation = agent.children!.find((c) => c.badge === "delegation")!;
    const ephemeral = delegation.children!.find((c) => c.badge === "ephemeral");
    expect(ephemeral).toBeTruthy();
    expect(ephemeral!.dotSize).toBe(9);
    expect(ephemeral!.dotExtra).toContain("2px solid");
    expect(ephemeral!.hasAvatar).toBe(true);
    expect(ephemeral!.avatarSize).toBe(16);
    expect(ephemeral!.labelWeight).toBe(500);
  });

  it("delegation: 12px dot, agent-colored badge + label, 600 weight", () => {
    const live: NormalizedTurn = {
      ...emptyTurn,
      runId: "r1",
      subagents: [{ key: "s0", childRunId: "sub-1", task: "check deps", skills: [] }],
    };
    const nodes = buildTimelineNodes({
      messages: [],
      live,
      activeAgentColor: "#3DD3F0",
      activeAgentName: "Bolt",
    });
    const agent = nodes.find((n) => n.badge === "agent")!;
    const delegation = agent.children!.find((c) => c.badge === "delegation");
    expect(delegation).toBeTruthy();
    expect(delegation!.dotSize).toBe(12);
    expect(delegation!.badgeColor).toBe(delegation!.dotColor);
    expect(delegation!.badgeBorder).toBe(delegation!.dotColor);
    expect(delegation!.labelWeight).toBe(600);
    expect(delegation!.labelColor).toBe(delegation!.dotColor);
  });
});

describe("activityUtils public API", () => {
  it("preserves the barrel export", () => {
    expect(typeof buildTimelineNodes).toBe("function");
  });
});
