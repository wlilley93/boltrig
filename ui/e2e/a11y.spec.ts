// Accessibility smoke over the built console. Axe runs against each canonical
// zone (plus deep readiness) after its real in-memory API requests settle.

import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const ROUTES = ["home", "chat", "runs", "build", "operate", "health"] as const;

for (const route of ROUTES) {
  test(`${route} has no serious or critical accessibility violations`, async ({ page }) => {
    await page.goto(`/#/${route}`);
    await page.waitForLoadState("networkidle");

    const { violations } = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
      .analyze();
    const blocking = violations.filter(
      ({ impact }) => impact === "serious" || impact === "critical",
    );

    expect(
      blocking,
      blocking
        .map(
          ({ id, impact, help, nodes }) =>
            `${impact ?? "unknown"} ${id}: ${help} (${nodes.length} node(s))`,
        )
        .join("\n"),
    ).toEqual([]);
  });
}
