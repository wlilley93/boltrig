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
  it("pins the desktop notice to the canonical lower-right coordinate", () => {
    const notice = rule(".voice-call-notice");
    expect(notice).toContain("position: fixed;");
    expect(notice).toContain("top: 649px;");
    expect(notice).toContain("right: 24px;");
    expect(notice).toContain("left: auto;");
    expect(notice).toContain("width: 236px;");
    expect(notice).toContain("padding: 12px 13px;");

    const viewportWidth = 1_440;
    const noticeWidth = 236;
    const rightInset = 24;
    expect(viewportWidth - rightInset - noticeWidth).toBe(1_180);
  });

  it("uses the canonical 150px primary familiar wrapper and stage", () => {
    const wrapper = rule(".voice-call-primary-familiar");
    expect(wrapper).toContain("width: 150px;");
    expect(wrapper).toContain("height: 150px;");

    const stage = rule(".voice-call-primary-familiar .familiar-stage");
    expect(stage).toContain("width: 150px;");
    expect(stage).toContain("height: 150px;");

    const renderSurface = rule(
      ".voice-call-primary-familiar .familiar-stage-canvas",
    );
    expect(renderSurface).toContain("position: absolute;");
    expect(renderSurface).toContain("top: 50%;");
    expect(renderSurface).toContain("left: 50%;");
    expect(renderSurface).toContain("width: 184px;");
    expect(renderSurface).toContain("height: 184px;");
    expect(renderSurface).toContain("margin-top: -92px;");
    expect(renderSurface).toContain("margin-left: -92px;");
    expect(renderSurface).toContain("max-width: none;");
    expect(renderSurface).toContain("max-height: none;");
  });
});
