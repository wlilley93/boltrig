import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const css = readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), "../src/components/PermanentFleetTopology.css"),
  "utf8",
);

function rule(selector: string): string {
  const start = css.indexOf(`${selector} {`);
  expect(start).toBeGreaterThanOrEqual(0);
  return css.slice(start, css.indexOf("}", start) + 1);
}

describe("Agents fleet parity CSS", () => {
  it("locks the desktop controls to the Figma topbar geometry", () => {
    expect(rule(".agents-fleet-topbar")).toContain("height: 48px;");
    expect(rule(".agents-fleet-topbar > .console-seg")).toContain("width: 290px;");
    expect(rule(".agents-fleet-topbar > .console-seg")).toContain("flex: 0 0 290px;");
    expect(rule(".agents-fleet-topbar > .console-primary")).toContain("height: 30px;");
    expect(rule(".agents-fleet-topbar > .console-primary")).toContain("padding-block: 0;");
  });

  it("keeps the fleet map inside the target inset frame", () => {
    const canvas = rule(".fleet-canvas");
    expect(canvas).toContain("border: 1px solid var(--border);");
    expect(canvas).toContain("border-radius: 14px;");
    expect(css).not.toContain(".agents-fleet-page .fleet-canvas {");
    expect(css).not.toContain("margin-inline: -18px;");
    expect(css).not.toContain("border-inline: 0;");
  });

  it("derives the canonical framed canvas width from the shell gutters", () => {
    const viewportWidth = 1440;
    const sidebarWidth = 262;
    const fleetGutter = 18;
    expect(rule(".permanent-fleet")).toContain("padding: 14px 18px 18px;");
    expect(sidebarWidth + fleetGutter).toBe(280);
    expect(viewportWidth - sidebarWidth - fleetGutter * 2).toBe(1142);
  });

  it("preserves the canonical summary, legend and canvas vertical rhythm", () => {
    const viewportHeight = 900;
    const topbarHeight = 48;
    const fleetTopPadding = 14;
    const summaryHeight = 34;
    const legendHeight = 28;
    const legendGap = 12;
    const fleetBottomPadding = 18;

    expect(rule(".agents-fleet-topbar")).toContain("padding: 18px 22px 0;");
    expect(rule(".fleet-summary")).toContain("padding: 0 2px 12px;");
    expect(rule(".fleet-authority-key")).toContain("margin-bottom: 12px;");
    expect(topbarHeight + fleetTopPadding).toBe(62);
    expect(topbarHeight + fleetTopPadding + summaryHeight).toBe(96);
    const canvasY = topbarHeight + fleetTopPadding + summaryHeight + legendHeight + legendGap;
    expect(canvasY).toBe(136);
    expect(viewportHeight - canvasY - fleetBottomPadding).toBe(746);
  });
});
