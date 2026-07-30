// The console mounts with its stack: one built artefact serves at "/" and under
// any sub-path (<tenant-host>/boltrig/) with no rebuild and no per-mount image.
// See docs/GOAL-console-mounts-with-its-stack.md.
//
// Two limbs, and the second is the one that matters:
//
//   1. mountPrefix is a pure function over a pathname - cheap to table-test.
//   2. BASE, the value that actually reaches the wire, is derived from it at
//      module load. A derivation that is right in a unit test and wrong in the
//      module that ships is the failure this file exists to prevent, so the
//      second describe asserts the URL `fetch` is really called with.
//
// The root case is a NEGATIVE CONTROL, not a nicety. A derivation that prefixed
// everything (or returned the raw pathname) would satisfy every sub-path
// assertion here and silently break app.boltrig.io, which is the deployment we
// already have. It has been observed red: with the previous one-line
// `import.meta.env.VITE_API_BASE ?? ""`, the sub-path cases fail and the root
// cases pass; with a naive `pathname` derivation, the root cases fail. Only a
// correct derivation turns both green.

import { afterEach, describe, expect, it, vi } from "vitest";

import { mountPrefix } from "@/api/transport";

describe("mountPrefix (pure)", () => {
  it("derives nothing at the root, so the standalone console is unchanged", () => {
    // The negative control. app.boltrig.io serves at "/" and must keep calling
    // /v1/... with no prefix at all.
    expect(mountPrefix("/")).toBe("");
    expect(mountPrefix("")).toBe("");
  });

  it("derives the mount when the console is served under a sub-path", () => {
    expect(mountPrefix("/boltrig/")).toBe("/boltrig");
    expect(mountPrefix("/boltrig")).toBe("/boltrig");
  });

  it("ignores a trailing document name, which is not part of the mount", () => {
    // Without this, /boltrig/index.html derives "/boltrig/index.html" and every
    // API call 404s - a failure that only appears when someone types the full
    // document path, so it would ship.
    expect(mountPrefix("/boltrig/index.html")).toBe("/boltrig");
    expect(mountPrefix("/index.html")).toBe("");
  });

  it("handles a nested mount, since the convention fixes /boltrig but not its parent", () => {
    expect(mountPrefix("/apps/boltrig/")).toBe("/apps/boltrig");
  });
});

describe("BASE (the value that ships)", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.resetModules();
    vi.restoreAllMocks();
  });

  // Re-import transport with a chosen pathname, then drive a real request and
  // return the URL fetch received. This reads the shipped constant, not a
  // re-implementation of it.
  async function urlFetchedFrom(pathname: string): Promise<string> {
    vi.resetModules();
    vi.stubGlobal("location", { ...window.location, pathname });
    const fetchSpy = vi
      .fn()
      .mockResolvedValue(new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetchSpy);

    const { request } = await import("@/api/transport");
    await request("/v1/skills");
    return String(fetchSpy.mock.calls[0][0]);
  }

  it("prefixes every call with the mount when served under a sub-path", async () => {
    expect(await urlFetchedFrom("/boltrig/")).toBe("/boltrig/v1/skills");
  });

  it("adds no prefix at the root", async () => {
    expect(await urlFetchedFrom("/")).toBe("/v1/skills");
  });
});

describe("VITE_API_BASE pins the prefix, for the mounts derivation gets wrong", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    // AND the envs. unstubAllGlobals does NOT undo stubEnv, so without this the
    // pinned VITE_API_BASE="" leaks into the next test and the negative control
    // below passes for the wrong reason. It caught exactly that on first run -
    // which is what a negative control is for.
    vi.unstubAllEnvs();
    vi.resetModules();
    vi.restoreAllMocks();
  });

  // WHY THIS ESCAPE HATCH IS LOAD-BEARING, not decoration.
  //
  // Deriving from pathname is right when the EDGE STRIPS the prefix: a tenant
  // mount at <host>/boltrig reaches the container as / and /v1, so pathname is
  // the mount and the derived prefix is correct.
  //
  // It is WRONG where the console sits at a real path while the kernel is proxied
  // at the root. That is exactly how the worker image packages this build
  // (apps/worker/Dockerfile serves it at /operator/ and proxies /v1/ at the root),
  // and the failure is the worst available shape: a derived "/operator" prefix
  // sends every call to /operator/v1/..., which that image's try_files answers
  // with the operator's own index.html at HTTP 200. Not a 404 - a 200 full of
  // HTML. Every request "succeeds" and returns the wrong thing.
  //
  // So the packaging pins VITE_API_BASE to empty, and this test is what stops
  // anyone "simplifying" the derivation into something that ignores it.
  it("an explicitly empty VITE_API_BASE beats the derivation", async () => {
    vi.resetModules();
    vi.stubEnv("VITE_API_BASE", "");
    vi.stubGlobal("location", { ...window.location, pathname: "/operator/" });
    const fetchSpy = vi.fn().mockResolvedValue(new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetchSpy);

    const { request } = await import("@/api/transport");
    await request("/v1/skills");
    expect(String(fetchSpy.mock.calls[0][0])).toBe("/v1/skills");
  });

  it("and the negative control: unset, /operator/ DOES derive a prefix", async () => {
    // The hazard, stated as an assertion. If this ever returns "/v1/skills" the
    // derivation has been changed and the comment above has gone stale.
    vi.resetModules();
    vi.stubGlobal("location", { ...window.location, pathname: "/operator/" });
    const fetchSpy = vi.fn().mockResolvedValue(new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetchSpy);

    const { request } = await import("@/api/transport");
    await request("/v1/skills");
    expect(String(fetchSpy.mock.calls[0][0])).toBe("/operator/v1/skills");
  });
});
