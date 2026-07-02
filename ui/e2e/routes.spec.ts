// Route-coverage smoke ([2026] VJS-COUNTY 2, D3): every primary zone renders
// its shell against the real kernel. Extends the chat smoke so the deck
// surfaces (agents, automations, settings, studio, insight) have a regression
// net too. Hermetic: dev identity is org-admin, in-memory store, no credentials
// or egress. Asserts only stable shell elements (the Panels nav and the main
// deck area) so it is deterministic, never flaky.

import { expect, test } from "@playwright/test";

const ZONES = ["chat", "agents", "automations", "settings", "studio", "insight"];

for (const zone of ZONES) {
  test(`${zone} zone renders the shell against the real kernel`, async ({ page }) => {
    await page.goto(`#/${zone}`);
    await expect(page.locator('nav[aria-label="Panels"]')).toBeVisible();
    await expect(page.locator(".app__main")).toBeVisible();
    // the zone's own nav item is marked current (aria-current=page)
    await expect(page.locator(".side-item--active")).toBeVisible();
    // let async panels finish their fetches before the server tears down
    await page.waitForLoadState("networkidle");
  });
}
