import { expect, test } from "@playwright/test";

const authorHeaders = {
  "x-boltrig-tenant": "default",
  "x-boltrig-subject": "e2e-author",
  "x-boltrig-grants": "*",
  "x-boltrig-role": "org-admin",
};

const reviewerHeaders = {
  ...authorHeaders,
  "x-boltrig-subject": "e2e-security-reviewer",
};

test("reviews and activates an inert adapter through the two-person gate", async ({
  page,
}) => {
  const generated = await page.request.post("/v1/adapters/generate", {
    headers: authorHeaders,
    data: {
      adapter_id: "e2e-openapi",
      spec: {
        openapi: "3.0.0",
        info: { title: "E2E API", version: "1.0.0" },
        paths: {
          "/widgets": {
            get: {
              operationId: "widget.list",
              responses: { 200: { description: "ok" } },
            },
          },
        },
      },
    },
  });
  expect(generated.ok()).toBeTruthy();

  await page.goto("/#/studio");
  await page.getByRole("button", { name: "Adapter Studio" }).click();

  const row = page.getByRole("article", { name: "Adapter e2e-openapi" });
  await expect(row).toBeVisible();
  await expect(row.getByText("inert", { exact: true })).toBeVisible();
  await expect(row.getByText("health: unknown", { exact: true })).toBeVisible();

  await row.getByRole("button", { name: "Review" }).click();
  await row.getByRole("button", { name: "Source" }).click();
  await expect(row.getByText(/class E2eOpenapiAdapter/)).toBeVisible();

  await row.getByRole("button", { name: "Activate" }).click();
  await expect(page.getByRole("button", { name: "Confirm activation" })).toBeVisible();
  await page.getByRole("button", { name: "Confirm activation" }).click();
  await expect(row.getByText("Paused for approval")).toBeVisible();

  const requestId = (await row.locator(".ux-pending__id code").textContent())?.trim();
  expect(requestId).toBeTruthy();
  const approved = await page.request.post(
    `/v1/hitl/${encodeURIComponent(requestId ?? "")}/respond`,
    {
      headers: reviewerHeaders,
      data: { decision: "approve", notes: "Reviewed in the e2e activation flow." },
    },
  );
  expect(approved.ok()).toBeTruthy();

  await expect(row.getByText("Activated and published 1 verb(s).")).toBeVisible({
    timeout: 20_000,
  });
  await expect(
    row.getByLabel("Adapter state").getByText("active", { exact: true }),
  ).toBeVisible();
  await expect(row.getByRole("button", { name: "Active" })).toBeDisabled();
});
