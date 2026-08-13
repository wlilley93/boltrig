// @vitest-environment happy-dom

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TranscriptNavigation } from "./TranscriptNavigation";
import { useTranscriptViewport } from "./useTranscriptViewport";

interface TranscriptItem {
  id: string;
  role: "assistant" | "user";
  text: string;
}

interface ViewportMetrics {
  clientHeight: number;
  scrollHeight: number;
  scrollTop: number;
  scrollCalls: ScrollToOptions[];
}

interface HarnessProps {
  conversationKey: string | null;
  contentRevision: string | number;
  items: TranscriptItem[];
  metrics: ViewportMetrics;
}

function installViewportMetrics(viewport: HTMLDivElement, metrics: ViewportMetrics) {
  Object.defineProperties(viewport, {
    clientHeight: { configurable: true, get: () => metrics.clientHeight },
    scrollHeight: { configurable: true, get: () => metrics.scrollHeight },
    scrollTop: {
      configurable: true,
      get: () => metrics.scrollTop,
      set: (value: number) => { metrics.scrollTop = value; },
    },
    scrollTo: {
      configurable: true,
      value: (options: ScrollToOptions) => {
        metrics.scrollCalls.push(options);
        if (typeof options.top === "number") metrics.scrollTop = options.top;
      },
    },
  });
}

function TranscriptHarness({
  conversationKey,
  contentRevision,
  items,
  metrics,
}: HarnessProps) {
  const controller = useTranscriptViewport({ conversationKey, contentRevision });
  return (
    <main>
      <div
        aria-label="Conversation transcript"
        id="test-conversation-transcript"
        onScroll={controller.onTranscriptScroll}
        ref={(node) => {
          controller.transcriptRef.current = node;
          if (node) installViewportMetrics(node, metrics);
        }}
        role="region"
      >
        {items.map((item) => (
          <article className={`message ${item.role}`} key={item.id}>
            {item.text}
          </article>
        ))}
      </div>
      <TranscriptNavigation
        model={controller.navigation}
        transcriptId="test-conversation-transcript"
      />
      <button onClick={controller.prepareForHistoryPrepend} type="button">
        Prepare prepend
      </button>
      <button onClick={controller.cancelHistoryPrepend} type="button">
        Cancel prepend
      </button>
      <output data-testid="following-latest">{String(controller.followingLatest)}</output>
    </main>
  );
}

function metrics(overrides: Partial<ViewportMetrics> = {}): ViewportMetrics {
  return {
    clientHeight: 100,
    scrollHeight: 500,
    scrollTop: 0,
    scrollCalls: [],
    ...overrides,
  };
}

function stubReducedMotion(reduced: boolean) {
  vi.stubGlobal("matchMedia", vi.fn().mockImplementation((query: string) => ({
    matches: query === "(prefers-reduced-motion: reduce)" && reduced,
    media: query,
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })));
}

const ITEMS: TranscriptItem[] = [
  { id: "user-a", role: "user", text: "First prompt" },
  { id: "assistant-a", role: "assistant", text: "First answer" },
  { id: "user-b", role: "user", text: "Second prompt" },
  { id: "assistant-b", role: "assistant", text: "Second answer" },
];

const originalScrollIntoView = HTMLElement.prototype.scrollIntoView;

beforeEach(() => stubReducedMotion(false));

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  if (originalScrollIntoView) {
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
      configurable: true,
      value: originalScrollIntoView,
    });
  } else {
    delete (HTMLElement.prototype as Partial<HTMLElement>).scrollIntoView;
  }
});

describe("useTranscriptViewport", () => {
  it("follows content updates only while the reader remains near the bottom", () => {
    const viewportMetrics = metrics();
    const view = render(
      <TranscriptHarness
        contentRevision={0}
        conversationKey="conversation-a"
        items={ITEMS}
        metrics={viewportMetrics}
      />,
    );
    const transcript = screen.getByRole("region", { name: "Conversation transcript" });
    expect(viewportMetrics.scrollTop).toBe(500);

    viewportMetrics.scrollTop = 0;
    fireEvent.scroll(transcript);
    expect(screen.getByTestId("following-latest").textContent).toBe("false");
    expect(screen.getByRole("button", { name: "Jump to latest" })).toBeTruthy();

    viewportMetrics.scrollHeight = 560;
    view.rerender(
      <TranscriptHarness
        contentRevision={1}
        conversationKey="conversation-a"
        items={[...ITEMS, { id: "assistant-c", role: "assistant", text: "Live update" }]}
        metrics={viewportMetrics}
      />,
    );
    expect(viewportMetrics.scrollTop).toBe(0);

    viewportMetrics.scrollTop = 430;
    fireEvent.scroll(transcript);
    expect(screen.getByTestId("following-latest").textContent).toBe("true");
    expect(screen.queryByRole("button", { name: "Jump to latest" })).toBeNull();

    viewportMetrics.scrollHeight = 620;
    view.rerender(
      <TranscriptHarness
        contentRevision={2}
        conversationKey="conversation-a"
        items={[...ITEMS, { id: "assistant-c", role: "assistant", text: "Longer live update" }]}
        metrics={viewportMetrics}
      />,
    );
    expect(viewportMetrics.scrollTop).toBe(620);
  });

  it("preserves the reading anchor when history is prepended and resets at a conversation boundary", () => {
    const viewportMetrics = metrics({ scrollHeight: 700 });
    const view = render(
      <TranscriptHarness
        contentRevision={0}
        conversationKey="conversation-a"
        items={ITEMS}
        metrics={viewportMetrics}
      />,
    );
    const transcript = screen.getByRole("region", { name: "Conversation transcript" });
    viewportMetrics.scrollTop = 120;
    fireEvent.scroll(transcript);
    fireEvent.click(screen.getByRole("button", { name: "Prepare prepend" }));

    viewportMetrics.scrollHeight = 980;
    view.rerender(
      <TranscriptHarness
        contentRevision={1}
        conversationKey="conversation-a"
        items={[
          { id: "user-older", role: "user", text: "Older prompt" },
          { id: "assistant-older", role: "assistant", text: "Older answer" },
          ...ITEMS,
        ]}
        metrics={viewportMetrics}
      />,
    );
    expect(viewportMetrics.scrollTop).toBe(400);
    expect(screen.getByTestId("following-latest").textContent).toBe("false");

    // A failed older-page request can cancel its snapshot; the next ordinary
    // update must not be mistaken for another prepend.
    fireEvent.click(screen.getByRole("button", { name: "Prepare prepend" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel prepend" }));
    viewportMetrics.scrollHeight = 1_050;
    view.rerender(
      <TranscriptHarness
        contentRevision={2}
        conversationKey="conversation-a"
        items={ITEMS}
        metrics={viewportMetrics}
      />,
    );
    expect(viewportMetrics.scrollTop).toBe(400);

    viewportMetrics.scrollHeight = 300;
    view.rerender(
      <TranscriptHarness
        contentRevision={0}
        conversationKey="conversation-b"
        items={[{ id: "user-new", role: "user", text: "A different task" }]}
        metrics={viewportMetrics}
      />,
    );
    expect(viewportMetrics.scrollTop).toBe(300);
    expect(screen.getByTestId("following-latest").textContent).toBe("true");
    expect(screen.queryByRole("button", { name: "Jump to latest" })).toBeNull();
    expect(screen.getByText("No user message selected")).toBeTruthy();
  });

  it("moves backward and forward through existing user-message DOM in order", () => {
    const scrollIntoView = vi.fn();
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
      configurable: true,
      value: scrollIntoView,
    });
    const viewportMetrics = metrics();
    render(
      <TranscriptHarness
        contentRevision={0}
        conversationKey="conversation-a"
        items={[
          ...ITEMS,
          { id: "user-c", role: "user", text: "Third prompt" },
          { id: "assistant-c", role: "assistant", text: "Third answer" },
        ]}
        metrics={viewportMetrics}
      />,
    );

    const navigation = screen.getByRole("navigation", { name: "Transcript navigation" });
    const status = navigation.querySelector<HTMLElement>("[role='status']")!;
    expect(navigation.getAttribute("aria-describedby")).toBe(status.id);
    expect(status.getAttribute("aria-live")).toBe("polite");
    expect(status.getAttribute("aria-atomic")).toBe("true");
    expect([...navigation.querySelectorAll("button")].every((button) => (
      button.getAttribute("aria-controls") === "test-conversation-transcript"
    ))).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "Previous user message" }));
    expect(scrollIntoView).toHaveBeenLastCalledWith({
      behavior: "smooth",
      block: "start",
      inline: "nearest",
    });
    expect(scrollIntoView.mock.instances.at(-1)).toBe(screen.getByText("Third prompt"));
    expect(screen.getByText("User message 3 of 3")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Previous user message" }));
    expect(scrollIntoView.mock.instances.at(-1)).toBe(screen.getByText("Second prompt"));
    expect(screen.getByText("User message 2 of 3")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Next user message" }));
    expect(scrollIntoView.mock.instances.at(-1)).toBe(screen.getByText("Third prompt"));
    expect(screen.getByRole<HTMLButtonElement>("button", { name: "Next user message" }).disabled)
      .toBe(true);
    expect(screen.getByRole("region", { name: "Conversation transcript" })
      .querySelector("nav")).toBeNull();
  });

  it("uses immediate scrolling when reduced motion is requested", () => {
    stubReducedMotion(true);
    const scrollIntoView = vi.fn();
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
      configurable: true,
      value: scrollIntoView,
    });
    const viewportMetrics = metrics();
    render(
      <TranscriptHarness
        contentRevision={0}
        conversationKey="conversation-a"
        items={ITEMS}
        metrics={viewportMetrics}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Previous user message" }));
    expect(scrollIntoView).toHaveBeenLastCalledWith({
      behavior: "auto",
      block: "start",
      inline: "nearest",
    });

    const transcript = screen.getByRole("region", { name: "Conversation transcript" });
    viewportMetrics.scrollTop = 0;
    fireEvent.scroll(transcript);
    fireEvent.click(screen.getByRole("button", { name: "Jump to latest" }));
    expect(viewportMetrics.scrollTop).toBe(500);
    expect(viewportMetrics.scrollCalls).toEqual([]);
  });
});
