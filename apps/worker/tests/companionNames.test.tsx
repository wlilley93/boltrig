// @vitest-environment happy-dom

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { offeredCompanion } from "../src/components/onboarding/companionCatalogue";
import { ReadyStep } from "../src/components/onboarding/ReadyStep";

afterEach(() => {
  cleanup();
  vi.unstubAllEnvs();
});

describe("the companion a person chose keeps its own name", () => {
  it("the Ready step greets with the chosen companion, not always Familiar", () => {
    vi.stubEnv("VITE_DESKTOP_DOWNLOAD_URL", "https://downloads.boltrig.test/desktop");
    const { unmount } = render(<ReadyStep character="ultron" userName="Alex" />);
    expect(screen.getByText("You’re ready, Alex. Meet Ultron.")).toBeTruthy();
    expect(screen.getByText("Use Ultron on this computer")).toBeTruthy();
    unmount();
    render(<ReadyStep character="colossus" userName="Alex" />);
    expect(screen.getByText("You’re ready, Alex. Meet Colossus.")).toBeTruthy();
  });

  it("an unknown id on the Ready step falls back to the default companion's name", () => {
    render(<ReadyStep character="some-plugin" userName="Alex" />);
    expect(screen.getByText("You’re ready, Alex. Meet Familiar.")).toBeTruthy();
  });

  it("a stored choice that setup offers is kept; one it does not offer becomes the default", () => {
    expect(offeredCompanion("ultron")).toBe("ultron");
    expect(offeredCompanion("colossus")).toBe("colossus");
    expect(offeredCompanion("jarvis")).toBe("jarvis");
    expect(offeredCompanion("familiar")).toBe("familiar");
    expect(offeredCompanion("some-plugin")).toBe("familiar");
  });
});
