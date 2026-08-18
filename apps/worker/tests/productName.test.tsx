// @vitest-environment happy-dom

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

afterEach(cleanup);

// Each case re-imports the module so the once-per-load memo and the cache are
// fresh. A shared module here would make the tests order-dependent, and the
// first one to run would decide what the rest observed.
async function load() {
  vi.resetModules();
  return {
    productName: await import("../src/productName"),
    BrandWordmark: (await import("../src/components/BrandWordmark")).BrandWordmark,
  };
}

function respond(body: unknown, ok = true) {
  return vi.fn().mockResolvedValue({ ok, json: async () => body });
}

describe("the name this deployment presents under", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.restoreAllMocks();
  });

  it("shows Boltrig before the kernel has answered", async () => {
    const { BrandWordmark } = await load();
    render(<BrandWordmark />);
    expect(screen.getByText("Boltrig")).toBeTruthy();
  });

  it("renames the wordmark to Opbox Agents when the kernel says so", async () => {
    vi.stubGlobal("fetch", respond({ product_name: "Opbox Agents", pulse: true }));
    const { productName, BrandWordmark } = await load();
    render(<BrandWordmark />);
    productName.bootstrapProductName();
    // THE COUNTEREXAMPLE THIS FILE EXISTS FOR. Every other wordmark assertion
    // in this suite is satisfied by a component that hardcodes "Boltrig", so
    // none of them can fail when the rename breaks.
    await waitFor(() => expect(screen.getByText("Opbox Agents")).toBeTruthy());
  });

  it("asks the kernel once however many wordmarks are mounted", async () => {
    const fetchMock = respond({ product_name: "Opbox Agents" });
    vi.stubGlobal("fetch", fetchMock);
    const { productName, BrandWordmark } = await load();
    render(
      <>
        <BrandWordmark />
        <BrandWordmark />
        <BrandWordmark />
      </>,
    );
    productName.bootstrapProductName();
    productName.bootstrapProductName();
    await waitFor(() => expect(screen.getAllByText("Opbox Agents")).toHaveLength(3));
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("serves the cached name first, so only a first visit can show the wrong one", async () => {
    window.localStorage.setItem("boltrig.product-name", "Opbox Agents");
    const { BrandWordmark } = await load();
    render(<BrandWordmark />);
    // No await: the point is that it is right on the FIRST paint.
    expect(screen.getByText("Opbox Agents")).toBeTruthy();
  });

  it("ignores a cached name the kernel could never have sent", async () => {
    // localStorage is writable by anything sharing the origin and the wordmark
    // is not a place to render arbitrary text.
    window.localStorage.setItem("boltrig.product-name", "<script>Evil Corp</script>");
    const { BrandWordmark } = await load();
    render(<BrandWordmark />);
    expect(screen.getByText("Boltrig")).toBeTruthy();
  });

  it("keeps the last good name when the kernel is unreachable", async () => {
    window.localStorage.setItem("boltrig.product-name", "Opbox Agents");
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("ECONNREFUSED")));
    const { productName, BrandWordmark } = await load();
    render(<BrandWordmark />);
    productName.bootstrapProductName();
    await waitFor(() => expect(screen.getByText("Opbox Agents")).toBeTruthy());
  });

  it("falls back to Boltrig when the kernel answers with something unexpected", async () => {
    vi.stubGlobal("fetch", respond({ product_name: "Totally Other Product" }));
    const { productName, BrandWordmark } = await load();
    render(<BrandWordmark />);
    productName.bootstrapProductName();
    await waitFor(() => expect(screen.getByText("Boltrig")).toBeTruthy());
  });
});
