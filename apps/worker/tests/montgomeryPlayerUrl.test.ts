// @vitest-environment happy-dom
//
// SEPARATE FROM THE DRIVE TESTS, which are pure logic and run in node. This
// file needs a DOM for one reason: a same-origin player path is resolved
// against `location.origin`, so "which origin" is the thing under test and
// there has to be one.
import { describe, expect, it } from "vitest";
import { validatedPlayerUrl } from "../src/components/montgomery/FrameGraphRenderer";

describe("where his player may be", () => {
  it("accepts a same-origin path and resolves it against this origin", () => {
    const url = validatedPlayerUrl("/companion/montgomery/");
    expect(url).toBe(`${location.origin}/companion/montgomery/`);
  });

  it("accepts loopback, for the desktop app where localhost is the user's machine", () => {
    expect(validatedPlayerUrl("http://localhost:8902")).toBe("http://localhost:8902/");
    expect(validatedPlayerUrl("http://127.0.0.1:8902")).toBe("http://127.0.0.1:8902/");
  });

  it("refuses a protocol-relative path, which reads as one and is not", () => {
    // `//evil.example` is another HOST. It starts with a slash, so a naive
    // same-origin check waves it through and the postMessage target origin
    // becomes somebody else's.
    expect(validatedPlayerUrl("//evil.example/companion/")).toBeNull();
  });

  it("refuses a remote origin, credentials, a query and a fragment", () => {
    expect(validatedPlayerUrl("https://evil.example/player")).toBeNull();
    expect(validatedPlayerUrl("http://user:pw@localhost:8902")).toBeNull();
    expect(validatedPlayerUrl("http://localhost:8902?x=1")).toBeNull();
    expect(validatedPlayerUrl("http://localhost:8902#f")).toBeNull();
    expect(validatedPlayerUrl("/companion/?x=1")).toBeNull();
    expect(validatedPlayerUrl("not a url")).toBeNull();
  });
});

describe("the desktop check he restates", () => {
  it("agrees with desktop.ts, which is the definition", async () => {
    // Restated rather than imported, to keep the desktop module out of the
    // character registry's import graph. That makes it a second copy, and this
    // is the thing that stops the two drifting apart in silence.
    const fs = await import("node:fs");
    const probe = '"__TAURI_INTERNALS__" in window';
    expect(fs.readFileSync("src/components/montgomery/montgomerySource.ts", "utf8"))
      .toContain(probe);
    expect(fs.readFileSync("src/desktop.ts", "utf8")).toContain(probe);
  });

  it("takes the same-origin branch off the desktop, which is where the web is", () => {
    // happy-dom carries no __TAURI_INTERNALS__, so this is the hosted branch.
    expect("__TAURI_INTERNALS__" in window).toBe(false);
    expect(validatedPlayerUrl("/companion/montgomery/"))
      .toBe(`${location.origin}/companion/montgomery/`);
  });
});
