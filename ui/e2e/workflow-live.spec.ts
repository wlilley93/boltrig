import { expect, test } from "@playwright/test";

const REVIEWER_HEADERS = {
  "x-boltrig-tenant": "default",
  "x-boltrig-subject": "e2e-reviewer",
  "x-boltrig-tier": "human",
  "x-boltrig-role": "org-admin",
  "x-boltrig-grants": "*",
};

test("workflow canvas follows one governed run from approval to terminal state", async ({
  page,
}) => {
  const seeded = await page.request.post("/v1/_e2e/seed-workflow");
  expect(seeded.ok()).toBeTruthy();

  await page.goto("/#/automations/e2e-live-workflow");
  await expect(page.locator(".wf3-header__name")).toHaveValue(
    "e2e-live-workflow",
  );
  await expect(page.locator(".wf3-node")).toHaveCount(2);

  await page.getByRole("button", { name: "Run", exact: true }).click();
  await expect(page.getByText("Paused for approval")).toBeVisible();
  await expect(page.getByText("Live run")).toBeVisible();

  const pending = await page.request.get("/v1/hitl", {
    headers: REVIEWER_HEADERS,
  });
  expect(pending.ok()).toBeTruthy();
  const requests = (await pending.json()).requests as Array<{
    id: string;
    verb?: string;
  }>;
  const approval = requests.find(
    (request) => request.verb === "control.workflow.execute",
  );
  expect(approval).toBeTruthy();

  const approved = await page.request.post(
    `/v1/hitl/${approval!.id}/respond`,
    {
      headers: REVIEWER_HEADERS,
      data: { decision: "approve", notes: "e2e live-canvas release" },
    },
  );
  expect(approved.ok()).toBeTruthy();

  await expect(page.getByText("stream closed")).toBeVisible({ timeout: 15_000 });
  await expect(page.locator(".wf3-node__card--ok")).toHaveCount(2);
  // One authored edge renders as its bezier plus arrowhead. A horizontal SVG
  // path has a zero-height DOM box, so Playwright's visibility heuristic calls
  // it hidden even though the stroke is painted; assert the semantic run state.
  await expect(page.locator(".wf3-edge--ok")).toHaveCount(2);
});
