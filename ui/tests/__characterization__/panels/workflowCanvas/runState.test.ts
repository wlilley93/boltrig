import { describe, expect, it } from "vitest";

import { stepsToGraph } from "@/panels/workflowCanvas/graph";
import {
  edgeVariantForStatus,
  overlayRunState,
} from "@/panels/workflowCanvas/runState";

describe("workflow live run overlay", () => {
  const base = stepsToGraph(
    [
      { id: "fetch", parents: [], action: "web.fetch" },
      { id: "publish", parents: ["fetch"], action: "channel.send" },
    ],
    new Map(),
  );

  it("lights the wire into the currently running step", () => {
    const overlaid = overlayRunState(
      base.nodes,
      base.edges,
      { fetch: "ok", publish: "running" },
      false,
    );

    expect(overlaid.nodes[1].data.runStatus).toBe("running");
    expect(overlaid.edges[0].data?.variant).toBe("running");
  });

  it("holds a paused node and its incoming wire in the governance state", () => {
    const overlaid = overlayRunState(
      base.nodes,
      base.edges,
      { fetch: "ok", publish: "paused" },
      false,
    );

    expect(overlaid.nodes[1].data.runStatus).toBe("paused");
    expect(overlaid.edges[0].data?.variant).toBe("paused");
    expect(edgeVariantForStatus("paused")).toBe("paused");
  });

  it("stops a stale running pulse when the stream has closed", () => {
    const overlaid = overlayRunState(
      base.nodes,
      base.edges,
      { publish: "running" },
      true,
    );

    expect(overlaid.nodes[1].data.runStatus).toBe("pending");
    expect(overlaid.edges[0].data?.variant).toBe("default");
  });
});
