import { expect, test } from "@playwright/test";

test("approval requires selection and an explicit confirmation", async ({ page }) => {
  const seeded = await page.request.post("/v1/_e2e/seed-hitl");
  expect(seeded.ok()).toBeTruthy();

  await page.goto("/#/approvals");
  await expect(page.getByText("Approve the e2e outbound update?")).toBeVisible();

  await page.getByRole("button", { name: "approve", exact: true }).click();
  await expect(page.getByRole("button", { name: "Confirm approve" })).toBeVisible();
  // Selecting is only the arm step: the pending card remains in place.
  await expect(page.getByText("Approve the e2e outbound update?")).toBeVisible();

  await page.getByRole("button", { name: "Confirm approve" }).click();
  await expect(page.getByText("Approve the e2e outbound update?")).toBeHidden();
});
