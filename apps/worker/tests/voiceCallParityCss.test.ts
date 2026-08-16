import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const css = readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), "../src/components/VoiceCall.css"),
  "utf8",
);

function rule(selector: string): string {
  const start = css.indexOf(`${selector} {`);
  expect(start).toBeGreaterThanOrEqual(0);
  return css.slice(start, css.indexOf("}", start) + 1);
}

describe("Voice Call parity CSS", () => {
  it("keeps the exceptional approval notice clear of the immersive controls", () => {
    const notice = rule(".voice-call-notice");
    expect(notice).toContain("position: fixed;");
    expect(notice).toContain("top: 64px;");
    expect(notice).toContain("right: 24px;");
    expect(notice).toContain("left: auto;");
    expect(notice).toContain("width: 236px;");
    expect(notice).toContain("padding: 12px 13px;");
  });

  it("gives Familiar and Jarvis the full call canvas at bounded retina resolution", () => {
    const wrapper = rule(".voice-call-primary-familiar");
    expect(wrapper).toContain("flex: 1;");
    expect(wrapper).toContain("width: min(1120px, 100%);");
    expect(wrapper).toContain("min-height: 260px;");

    const stage = rule(".voice-call-primary-familiar .familiar-stage");
    expect(stage).toContain("width: min(78vw, calc(100dvh - 170px), 880px);");
    expect(stage).toContain("height: min(78vw, calc(100dvh - 170px), 880px);");

    const renderSurface = rule(
      ".voice-call-primary-familiar .familiar-stage-canvas",
    );
    expect(renderSurface).toContain("width: 100%;");
    expect(renderSurface).toContain("height: 100%;");

    const jarvis = rule(".voice-call-primary-familiar .jarvis-stage");
    expect(jarvis).toContain("width: 100%;");
    expect(jarvis).toContain("height: 100%;");
  });

  it("keeps a full-width chat bar below the call canvas", () => {
    const controls = rule(".voice-call-controls");
    expect(controls).toContain("width: min(745px, calc(100vw - 48px));");
    expect(controls).toContain("flex-wrap: wrap;");

    const text = rule(".voice-call-text");
    expect(text).toContain("width: 100%;");
    expect(text).toContain("flex: 1 0 100%;");
  });

  it("animates both shell rails away while the full-window call is present", () => {
    const shell = rule(
      "body.voice-call-animate .worker-shell:has(.sidebar.shell-parity)",
    );
    expect(shell).toContain("grid-template-columns: 0 minmax(0, 1fr);");

    const sidebar = rule("body.voice-call-animate .sidebar-wrap");
    expect(sidebar).toContain("transform: translateX(calc(-100% - 20px));");
    expect(sidebar).toContain("opacity: 0;");
    expect(sidebar).toContain("pointer-events: none;");

    const inspector = rule("body.voice-call-animate .task-inspector.right-rail");
    expect(inspector).toContain("transform: translateX(calc(100% + 20px));");
    expect(inspector).toContain("opacity: 0;");
    expect(inspector).toContain("pointer-events: none;");
  });
});
