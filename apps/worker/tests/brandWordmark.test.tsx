// @vitest-environment happy-dom

import { readFileSync } from "node:fs";
import { join } from "node:path";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { BrandWordmark } from "../src/components/BrandWordmark";

afterEach(cleanup);

describe("Boltrig wordmark", () => {
  it("renders the wordmark without adding the standalone app mark", () => {
    const { container } = render(<BrandWordmark />);

    expect(screen.getByText("Boltrig")).toBeTruthy();
    expect(container.querySelector("svg")).toBeNull();
    expect(container.textContent).not.toContain("ϟ");
  });

  it("keeps in-product brand call sites wordmark-led", () => {
    const auth = readFileSync(join(process.cwd(), "src/components/auth/AuthShell.tsx"), "utf8");
    const onboarding = readFileSync(
      join(process.cwd(), "src/components/onboarding/OnboardingGate.tsx"),
      "utf8",
    );
    const lockup = readFileSync(
      join(process.cwd(), "src/components/onboarding/BrandLockup.tsx"),
      "utf8",
    );

    expect(auth).toContain("<BrandWordmark");
    // And the MARK, on the same surface. Every auth screen -- sign-in, the 2FA
    // prompt and its setup, both password resets, invite acceptance, the desktop
    // bridge -- renders through this one AuthCard, so asserting the pairing here
    // is what keeps all nine on one header rather than eight and an exception.
    expect(auth).toContain("<BrandMark");
    // Onboarding reaches the wordmark THROUGH the lockup, which is the single
    // place mark and wordmark are paired. Asserting the gate goes through it,
    // rather than that the gate mentions the wordmark itself, is what stops the
    // two onboarding headers drifting into two different brands.
    expect(onboarding).toContain("<BrandLockup");
    expect(lockup).toContain("<BrandWordmark");
    expect(`${auth}\n${onboarding}\n${lockup}`).not.toContain("ϟ");
    expect(`${auth}\n${onboarding}\n${lockup}`).not.toContain("bolt-mark");
  });

  it("draws the mark's core in one colour, in both places that draw it", () => {
    // The desktop icons are rasterised FROM public/favicon.svg (4b392a21), so
    // the favicon and BrandMark.tsx are the only two hand-written copies of the
    // core -- and a change to one alone is how the tree grew a third shade of
    // the mark the last time. This pins them together rather than pinning the
    // value, so a future rebrand edits two files and the test follows.
    const mark = readFileSync(join(process.cwd(), "src/components/BrandMark.tsx"), "utf8");
    const favicon = readFileSync(join(process.cwd(), "public/favicon.svg"), "utf8");

    const inMark = /const CORE = "(#[0-9A-Fa-f]{6})"/.exec(mark)?.[1];
    const inFavicon = /<circle[^>]*r="5\.0"[^>]*fill="(#[0-9A-Fa-f]{6})"/.exec(favicon)?.[1];

    expect(inMark).toBeTruthy();
    expect(inFavicon).toBeTruthy();
    expect(inFavicon?.toUpperCase()).toBe(inMark?.toUpperCase());
  });

  it("binds browser tabs and installs to the standalone mark assets", () => {
    const html = readFileSync(join(process.cwd(), "index.html"), "utf8");
    const manifest = JSON.parse(
      readFileSync(join(process.cwd(), "public/manifest.webmanifest"), "utf8"),
    ) as { icons: Array<{ sizes: string }>; name: string };

    expect(html).toContain("%BASE_URL%favicon.svg");
    expect(html).toContain("%BASE_URL%apple-touch-icon.png");
    expect(html).toContain("%BASE_URL%manifest.webmanifest");
    expect(manifest.name).toBe("Boltrig");
    expect(manifest.icons.map((icon) => icon.sizes)).toEqual(["192x192", "512x512"]);
  });
});
