import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const workerCss = readFileSync(
  new URL("../src/styles.css", import.meta.url),
  "utf8",
);

describe("composer run status styling", () => {
  it("centres an expandable compact step receipt above the composer", () => {
    expect(workerCss).toMatch(/\.run-progress\s*\{[^}]*width:\s*min\(745px/);
    expect(workerCss).toMatch(/\.run-progress-pill\s*\{[^}]*min-height:\s*36px/);
    expect(workerCss).toMatch(/\.run-progress-list\s*\{[^}]*bottom:\s*calc\(100% \+ 8px\)/);
    expect(workerCss).toContain("@media (prefers-reduced-motion: reduce)");
  });

  it("keeps queued instructions in a bounded stack of thin rows", () => {
    expect(workerCss).toMatch(/\.queued-messages\s*\{[^}]*width:\s*min\(745px/);
    expect(workerCss).toMatch(/\.queued-messages\s*\{[^}]*overflow-y:\s*auto/);
    expect(workerCss).toMatch(/\.queued-message\s*\{[^}]*min-height:\s*29px/);
    expect(workerCss).toMatch(/\.queued-message-copy p\s*\{[^}]*white-space:\s*nowrap/);
    expect(workerCss).toMatch(/\.queued-message-handle\s*\{[^}]*cursor:\s*grab/);
    expect(workerCss).toMatch(/\.queued-message-handle:focus-visible\s*\{[^}]*outline:/);
  });
});
