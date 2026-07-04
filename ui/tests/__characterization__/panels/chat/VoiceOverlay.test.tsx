import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render } from "@testing-library/react";

import { VoiceOverlay, VOICE_TRANSCRIPT_QUEUE } from "@/panels/chat/VoiceOverlay";
import type { ChatAgent } from "@/panels/chat/constants";

const agent: ChatAgent = {
  id: "bolt",
  name: "Bolt",
  role: "Chief of Staff",
  initials: "B",
  color: "#3DD3F0",
  dept: "Org-wide",
  status: "active",
  snippet: "",
  time: "now",
  tier: 1,
  history: [],
};

function props(overrides: Partial<Parameters<typeof VoiceOverlay>[0]> = {}) {
  return {
    agent,
    seconds: 12,
    muted: false,
    speaker: false,
    onMute: vi.fn(),
    onSpeaker: vi.fn(),
    onEnd: vi.fn(),
    ...overrides,
  };
}

describe("chat/VoiceOverlay transcript + rings (sec 12)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
    cleanup();
  });

  it("renders three expanding rings", () => {
    const { container } = render(<VoiceOverlay {...props()} />);
    const rings = container.querySelectorAll(".voice-card__mic span");
    expect(rings.length).toBe(3);
  });

  it("reveals the transcript one line at a time via the timer chain", () => {
    const { container } = render(<VoiceOverlay {...props()} />);
    const lines = () => container.querySelectorAll(".voice-card__line");

    // Only the first queued line is visible immediately.
    expect(lines().length).toBe(1);

    // Advancing the first-step delay reveals the second line.
    act(() => {
      vi.advanceTimersByTime(900);
    });
    expect(lines().length).toBe(2);

    // Each subsequent step reveals one more line.
    act(() => {
      vi.advanceTimersByTime(1500);
    });
    expect(lines().length).toBe(3);
    act(() => {
      vi.advanceTimersByTime(1500);
    });
    expect(lines().length).toBe(4);

    // Advancing past the end reveals the whole queue and no more.
    act(() => {
      vi.advanceTimersByTime(60_000);
    });
    expect(lines().length).toBe(VOICE_TRANSCRIPT_QUEUE.length);
  });

  it("colors user vs agent transcript labels distinctly", () => {
    const { container } = render(<VoiceOverlay {...props()} />);
    act(() => {
      vi.advanceTimersByTime(60_000);
    });
    const user = container.querySelector(".voice-card__line--user .voice-card__line-label");
    const agentLine = container.querySelector(".voice-card__line--agent .voice-card__line-label");
    expect(user).not.toBeNull();
    expect(agentLine).not.toBeNull();
  });

  it("cleans up pending timers on unmount so no further lines appear", () => {
    const { container, unmount } = render(<VoiceOverlay {...props()} />);
    expect(container.querySelectorAll(".voice-card__line").length).toBe(1);
    unmount();
    // After unmount, advancing time must not throw or mutate anything.
    expect(() =>
      act(() => {
        vi.advanceTimersByTime(60_000);
      }),
    ).not.toThrow();
  });

  it("keeps mic bounce, timer, and call controls intact", () => {
    const onMute = vi.fn();
    const onEnd = vi.fn();
    const { getByText, getByLabelText } = render(
      <VoiceOverlay {...props({ onMute, onEnd })} />,
    );
    expect(getByText("Voice call active")).toBeTruthy();
    expect(getByText("00:12")).toBeTruthy();
    getByLabelText("End call").click();
    expect(onEnd).toHaveBeenCalledTimes(1);
  });
});
