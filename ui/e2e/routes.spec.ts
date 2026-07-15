// Console-shell smoke: the built SPA exposes the canonical five-zone
// navigation, the discoverable command palette can navigate between pages,
// and a deep-linked Run inspector closes back to the Runs explorer. The
// Playwright harness supplies a real in-memory kernel, so these checks exercise
// the shipped artifact without credentials, model keys, or external services.

import { expect, test } from "@playwright/test";

const ZONES = [
  { label: "Home", path: "home" },
  { label: "Chat", path: "chat" },
  { label: "Runs", path: "runs" },
  { label: "Build", path: "build" },
  { label: "Operate", path: "operate" },
] as const;

for (const zone of ZONES) {
  test(`${zone.label} renders in the five-zone console shell`, async ({ page }) => {
    await page.goto(`/#/${zone.path}`);

    const navigation = page.getByRole("navigation", { name: "Console zones" });
    await expect(navigation).toBeVisible();
    await expect(page.locator(".app__main")).toBeVisible();
    await expect(
      navigation.getByRole("button", { name: zone.label, exact: true }),
    ).toHaveAttribute("aria-current", "page");

    for (const item of ZONES) {
      await expect(
        navigation.getByRole("button", { name: item.label, exact: true }),
      ).toBeVisible();
    }

    // Let lazy panels finish their initial real-kernel requests before the
    // shared web-server lifecycle moves to the next test.
    await page.waitForLoadState("networkidle");
  });
}

test("command palette navigates to a console page", async ({ page }) => {
  await page.goto("/#/home");
  await page.getByRole("button", { name: "Open command palette" }).click();

  const palette = page.getByRole("dialog", { name: "Command palette" });
  await expect(palette).toBeVisible();

  await palette.getByRole("combobox", { name: "Command palette search" }).fill("Runs");
  await palette.getByRole("option", { name: /^Runs\b/ }).click();

  await expect(page).toHaveURL(/#\/runs$/);
  await expect(
    page
      .getByRole("navigation", { name: "Console zones" })
      .getByRole("button", { name: "Runs", exact: true }),
  ).toHaveAttribute("aria-current", "page");
  await expect(palette).toBeHidden();
});

test("command palette remains the topmost keyboard modal over a Run drawer", async ({
  page,
}) => {
  await page.goto("/#/runs/e2e-focus-run");
  const inspector = page.getByRole("dialog", { name: "Run details" });
  const closeInspector = inspector.getByRole("button", {
    name: "Close run inspector",
  });
  await expect(inspector).toBeVisible();
  await closeInspector.focus();

  await page.keyboard.press("Control+k");
  const palette = page.getByRole("dialog", { name: "Command palette" });
  const search = palette.getByRole("combobox", {
    name: "Command palette search",
  });
  await expect(search).toBeFocused();

  await page.keyboard.press("Shift+Tab");
  expect(
    await palette.evaluate((element) => element.contains(document.activeElement)),
  ).toBe(true);

  await page.keyboard.press("Escape");
  await expect(palette).toBeHidden();
  await expect(inspector).toBeVisible();
  await expect(closeInspector).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(inspector.getByRole("button", { name: "All runs" })).toBeFocused();
});

test("closing a deep-linked Run inspector returns to the Runs explorer", async ({ page }) => {
  await page.goto("/#/runs/e2e-missing-run");

  const inspector = page.getByRole("dialog", { name: "Run details" });
  await expect(inspector).toBeVisible();
  await expect(inspector.getByText("e2e-missing-run", { exact: true })).toBeVisible();
  await expect(
    inspector.getByText("Run not found, or not in your visibility scope."),
  ).toBeVisible();

  await inspector.getByRole("button", { name: "Close run inspector" }).click();

  await expect(inspector).toBeHidden();
  await expect(page).toHaveURL(/#\/runs$/);
  await expect(
    page
      .getByRole("navigation", { name: "Console zones" })
      .getByRole("button", { name: "Runs", exact: true }),
  ).toHaveAttribute("aria-current", "page");
});
