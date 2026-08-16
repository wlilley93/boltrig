// @vitest-environment happy-dom

import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ familiarPhenotype: vi.fn() }));

vi.mock("../src/client", () => ({ client: api }));

import { useStagePhenotype } from "../src/components/chat/useStagePhenotype";

describe("Stage phenotype ownership", () => {
  beforeEach(() => {
    api.familiarPhenotype.mockResolvedValue({ state: "resting" });
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      value: "visible",
    });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.clearAllMocks();
  });

  it("does not poll for a character that cannot read the phenotype", async () => {
    const hook = renderHook(({ enabled }) => useStagePhenotype(enabled), {
      initialProps: { enabled: false },
    });
    await act(async () => undefined);
    expect(api.familiarPhenotype).not.toHaveBeenCalled();
    expect(hook.result.current.phenotype).toBeNull();

    hook.rerender({ enabled: true });
    await waitFor(() => expect(api.familiarPhenotype).toHaveBeenCalledOnce());
    hook.rerender({ enabled: false });
    await waitFor(() => expect(hook.result.current.phenotype).toBeNull());
  });
});
