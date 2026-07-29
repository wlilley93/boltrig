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
