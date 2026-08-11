// @vitest-environment happy-dom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { JarvisLabels, readingText } from "../src/components/jarvis/JarvisLabels";
import { NO_READING, type GaugeReading } from "../src/components/jarvis/JarvisTelemetry";

const reading = (over: Partial<GaugeReading>): GaugeReading => ({
  ...NO_READING, known: true, ...over,
});

afterEach(cleanup);

describe("interrogating a gauge", () => {
  // An arc gives a proportion. The number is the thing you actually need when
  // you are about to spend more.
  it("answers with the real figures, not the percentage alone", () => {
    const text = readingText(
      "Spend",
      reading({ fill: 0.824, spent: 4_120_000, limit: 5_000_000, window: "daily" }),
      "cost",
    );
    expect(text).toContain("$4.12");
    expect(text).toContain("$5.00");
    expect(text).toContain("daily");
    expect(text).toContain("82%");
  });

  it("says a hard stop is a hard stop", () => {
    const hard = readingText("Spend", reading({ spent: 1, limit: 2, hard: true }), "cost");
    const soft = readingText("Spend", reading({ spent: 1, limit: 2, hard: false }), "cost");
    expect(hard).toContain("hard stop");
    expect(soft).not.toContain("hard stop");
  });

  // The honesty rule, in the one place a person will actually read words.
  it("says 'no reading' rather than inventing a zero", () => {
    const text = readingText("Spend", NO_READING, "cost");
    expect(text).toBe("Spend: no reading");
    expect(text).not.toContain("0");
  });

  it("compacts token counts instead of printing them in full", () => {
    const text = readingText("Tokens", reading({ spent: 1_200_000, limit: 4_000_000 }), "tokens");
    // Intl compact notation is locale- and ICU-dependent ("1.2M" in a browser,
    // "1.2m" under Node ICU), so assert the shape rather than the casing.
    expect(text.toUpperCase()).toContain("1.2M");
  });

  it("exposes each track as a focusable control carrying its own reading", () => {
    render(
      <JarvisLabels
        mode="working"
        telemetry={{
          budget: reading({ fill: 0.5, spent: 2_500_000, limit: 5_000_000, window: "daily" }),
          tokens: NO_READING,
        }}
      />,
    );
    // Currency presentation is locale/ICU dependent ("$2.50" in a browser,
    // "US$2.50" under Node), so match the figures rather than the symbol.
    const spend = screen.getByRole("button", { name: /Spend:.*2\.50.*5\.00.*daily/ });
    expect(spend.tagName).toBe("BUTTON");
    // The unread track still answers — honestly.
    expect(screen.getByRole("button", { name: "Tokens: no reading" })).toBeTruthy();
  });

  it("answers a keyboard user on focus", () => {
    const { container } = render(
      <JarvisLabels
        mode="working"
        telemetry={{
          budget: reading({ fill: 0.5, spent: 2_500_000, limit: 5_000_000 }),
          tokens: NO_READING,
        }}
      />,
    );
    const spend = screen.getByRole("button", { name: /Spend/ });
    fireEvent.focus(spend);
    expect(container.querySelector(".jarvis-labels__asked")?.textContent)
      .toContain("2.50");
    fireEvent.blur(spend);
    expect(container.querySelector(".jarvis-labels__asked")).toBeNull();
  });

  it("shows the answer on pointer hover and clears it on leave", () => {
    const { container } = render(
      <JarvisLabels
        mode="working"
        telemetry={{
          budget: reading({ fill: 0.5, spent: 2_500_000, limit: 5_000_000 }),
          tokens: NO_READING,
        }}
      />,
    );
    // The pointer path is the SVG track itself, which is aria-hidden by design
    // — the buttons above are the accessible path. Both must work.
    const track = container.querySelector(".jarvis-labels__probes circle");
    expect(track).toBeTruthy();
    expect(container.querySelector(".jarvis-labels__asked")).toBeNull();
    fireEvent.pointerEnter(track!);
    expect(container.querySelector(".jarvis-labels__asked")?.textContent)
      .toContain("2.50");
    fireEvent.pointerLeave(track!);
    expect(container.querySelector(".jarvis-labels__asked")).toBeNull();
  });
});
