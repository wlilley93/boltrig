import { expect, test } from "@playwright/test";

test("ratified open surfaces expose their settled task models", async ({ page }) => {
  await page.goto("/#/knowledge");
  await expect(page.getByRole("tab", { name: "Library" })).toHaveAttribute("aria-selected", "true");
  await page.getByRole("tab", { name: "Search" }).click();
  await expect(page.getByLabel("Search Knowledge")).toBeVisible();

  await page.goto("/#/memory");
  await expect(page.getByRole("tab", { name: "Recall" })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("radiogroup", { name: "Search mode" })).toBeVisible();

  await page.goto("/#/insight");
  await expect(page.getByRole("radio", { name: "Overview" })).toBeChecked();
  await page.getByRole("radio", { name: "Audit" }).click();
  const auditForm = page.locator(".form").filter({ hasText: "Audit search" });
  await expect(auditForm.getByRole("button", { name: "Search" })).toBeVisible();

  await page.goto("/#/eval");
  await expect(page.getByRole("radio", { name: "Run cases" })).toBeChecked();
  await page.getByRole("radio", { name: "Create case" }).click();
  await expect(page.getByText("Advanced: edit case input as JSON")).toBeVisible();
  await expect(page.getByRole("button", { name: "Request case change" })).toBeVisible();

  await page.goto("/#/admin");
  await page.getByRole("radio", { name: "Organisation & workspaces" }).click();
  await expect(page.getByRole("tab", { name: "Members" })).toHaveAttribute("aria-selected", "true");
  await page.getByRole("tab", { name: "Workspaces" }).click();
  await expect(page.locator("#organisation-panel-workspaces")).toBeVisible();

  await page.goto("/#/agents");
  await page.getByRole("button", { name: "New agent" }).click();
  await expect(page.getByRole("heading", { name: "Create agent profile" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Request agent creation" })).toBeVisible();
});

test("production build does not expose the design prototype as a third client", async ({ page }) => {
  await page.goto("/#/prototype/home");
  await expect(page.locator(".proto-shell")).toHaveCount(0);
  await expect(page.getByRole("navigation", { name: "Console zones" })).toBeVisible();
});
