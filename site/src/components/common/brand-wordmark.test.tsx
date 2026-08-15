// @vitest-environment happy-dom

import { readFileSync } from "node:fs";
import { join } from "node:path";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { BrandWordmark } from "./brand-wordmark";

afterEach(cleanup);

describe("Boltrig wordmark", () => {
  it("uses text-only in-site branding", () => {
    const { container } = render(<BrandWordmark />);

    expect(screen.getByText("Boltrig")).toBeTruthy();
    expect(container.querySelector("svg")).toBeNull();
  });

  it("retains the concentric mark only for standalone browser assets", () => {
    const header = readFileSync(join(process.cwd(), "src/components/common/site-header.tsx"), "utf8");
    const telemetry = readFileSync(
      join(process.cwd(), "src/components/brain/brain-telemetry.tsx"),
      "utf8",
    );
    const icon = readFileSync(join(process.cwd(), "src/app/icon.svg"), "utf8");
    const manifest = JSON.parse(
      readFileSync(join(process.cwd(), "public/manifest.json"), "utf8"),
    ) as { icons: Array<{ purpose?: string; sizes: string }>; name: string };

    expect(header).toContain("<BrandWordmark");
    expect(header).not.toContain("<svg");
    expect(telemetry).not.toContain("// GOVERNED");
    expect(icon).toContain("<circle");
    expect(icon).not.toContain("<path");
    expect(manifest.name).toBe("Boltrig");
    expect(manifest.icons).toContainEqual(expect.objectContaining({
      purpose: "any maskable",
      sizes: "192x192",
    }));
  });
});
