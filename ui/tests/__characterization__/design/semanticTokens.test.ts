import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

const RAW_COLOR = /["'`](?:#[0-9a-f]{3,8}|rgba?\(\s*\d)/gi;

function sourceFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const target = path.join(dir, entry.name);
    if (entry.isDirectory()) return sourceFiles(target);
    return /\.tsx?$/.test(entry.name) ? [target] : [];
  });
}

describe("semantic design-token boundary", () => {
  it("keeps raw color literals out of TypeScript components", () => {
    const root = path.resolve(process.cwd(), "src");
    const offenders = sourceFiles(root).flatMap((file) => {
      const source = readFileSync(file, "utf8");
      return [...source.matchAll(RAW_COLOR)].map((match) => {
        const line = source.slice(0, match.index).split("\n").length;
        return `${path.relative(root, file)}:${line} ${match[0].slice(1)}`;
      });
    });

    expect(offenders).toEqual([]);
  });
});
