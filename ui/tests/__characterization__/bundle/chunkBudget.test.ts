import { describe, expect, it } from "vitest";

import { oversizedChunks } from "../../../config/chunkBudget";

describe("JavaScript chunk budget", () => {
  it("accepts chunks at the byte limit and ignores assets", () => {
    expect(
      oversizedChunks(
        {
          "entry.js": { type: "chunk", fileName: "entry.js", code: "x".repeat(500_000) },
          "style.css": { type: "asset", fileName: "style.css" },
        },
        500_000,
      ),
    ).toEqual([]);
  });

  it("reports every chunk over the byte limit", () => {
    expect(
      oversizedChunks(
        {
          "entry.js": { type: "chunk", fileName: "entry.js", code: "x".repeat(500_001) },
          "lazy.js": { type: "chunk", fileName: "lazy.js", code: "£".repeat(250_001) },
        },
        500_000,
      ),
    ).toEqual([
      { fileName: "entry.js", bytes: 500_001 },
      { fileName: "lazy.js", bytes: 500_002 },
    ]);
  });
});
