import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const ROUTES = [
  "home",
  "chat",
  "inbox",
  "runs",
  "work",
  "agents",
  "account",
  "build",
  "channels",
  "evaluations",
  "automations",
  "knowledge",
  "memory",
  "integrations",
  "operate",
  "organisation",
  "settings",
] as const;

test("built Worker is the task-first Boltrig surface and retains Operator escape", async ({
  page,
}) => {
  await page.goto("/#/chat");

  await expect(page.getByRole("complementary", { name: "Worker navigation" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "What needs doing?" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Open Operator" })).toHaveAttribute(
    "href",
    "/operator/",
  );

  // The decided target's sidebar carries four surfaces and no second group.
  // Inbox, Runs, Work, Knowledge and Memory stay reachable from the account
  // menu and the command palette, which the palette test below exercises.
  for (const label of ["Chat", "Agents", "Plugins", "Routines"]) {
    await expect(page.getByRole("button", { name: label, exact: true })).toBeVisible();
  }
  for (const gone of ["Inbox", "Runs", "Work", "Knowledge", "Memory"]) {
    await expect(page.getByRole("button", { name: gone, exact: true })).toHaveCount(0);
  }
});

test("Worker chat streams through the governed kernel", async ({ page }) => {
  await page.goto("/#/chat");

  const composer = page.getByRole("textbox", { name: "Task instructions" });
  await expect(composer).toBeVisible();
  await composer.fill("hello from the Worker e2e smoke");
  await page.getByRole("button", { name: /^Send/ }).click();

  await expect(page.locator(".message.assistant").last()).toContainText(
    "(no runtime configured)",
  );
});

test("Worker command palette navigates across the primary surface", async ({ page }) => {
  await page.goto("/#/chat");

  const opener = page.getByRole("button", { name: "Open command palette" });
  await opener.click();
  const palette = page.getByRole("dialog", { name: "Worker commands" });
  const search = palette.getByRole("combobox", { name: "Search Worker" });
  const results = palette.getByRole("listbox", { name: "Worker command results" });
  await expect(palette).toBeVisible();
  await expect(search).toBeFocused();
  await expect(results).toBeVisible();
  await expect(search).toHaveAttribute(
    "aria-activedescendant",
    "worker-command-option-0",
  );
  const { violations } = await new AxeBuilder({ page })
    .include(".command-palette")
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  expect(blockingViolations(violations)).toEqual([]);
  await search.press("Shift+Tab");
  await expect(palette.getByRole("option", {
    name: /Settings Configure Worker preferences/,
  })).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(search).toBeFocused();

  await search.fill("canonical work");
  await palette.getByRole("option", {
    name: /Work Browse canonical work and project dependencies/,
  }).click();

  await expect(page).toHaveURL(/#\/work$/);
  await expect(page.getByRole("heading", { name: "Work", exact: true })).toBeVisible();
});

test("compact task details stays out of the tab order until opened", async ({ page }) => {
  await page.setViewportSize({ width: 900, height: 760 });
  await page.goto("/#/chat");

  const trigger = page.getByRole("button", { name: "Task details" });
  const sheet = page.locator("#worker-task-details");
  await expect(trigger).toBeVisible();
  await expect(sheet).toHaveAttribute("inert", "");

  await page.getByRole("textbox", { name: "Task instructions" }).focus();
  await page.keyboard.press("Tab");
  expect(await page.evaluate(() => (
    document.activeElement?.closest("#worker-task-details") === null
  ))).toBe(true);

  await trigger.click();
  await expect(page.getByRole("dialog", { name: "Task details" })).toBeVisible();
  await expect(sheet).not.toHaveAttribute("inert", "");
  await expect(page.getByRole("button", { name: "Close task details" })).toBeFocused();

  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog", { name: "Task details" })).toBeHidden();
  await expect(sheet).toHaveAttribute("inert", "");
  await expect(trigger).toBeFocused();

  await page.setViewportSize({ width: 390, height: 760 });
  await expect(trigger).toBeVisible();
  const mobileTriggerBox = await trigger.boundingBox();
  expect(mobileTriggerBox).not.toBeNull();
  expect((mobileTriggerBox?.x ?? 390) + (mobileTriggerBox?.width ?? 1)).toBeLessThanOrEqual(390);
  await trigger.click();
  await expect(page.getByRole("dialog", { name: "Task details" })).toBeVisible();
  await page.getByRole("button", { name: "Dismiss task details" }).click({
    position: { x: 5, y: 20 },
  });
  await expect(sheet).toHaveAttribute("inert", "");
});

test("Worker approves a canonical Inbox decision and converges its global count", async ({
  page,
}) => {
  const seeded = await page.request.post("/v1/_e2e/seed-hitl");
  expect(seeded.ok()).toBeTruthy();

  await page.goto("/#/chat");
  await expect(page.getByRole("button", {
    name: "1 pending decisions",
    exact: true,
  })).toBeVisible();
  await expect(page.getByLabel("1 pending decisions", { exact: true })).toBeVisible();
  await expect(page.getByLabel(/Signed in as e2e-worker/)).toBeVisible();

  await page.getByRole("button", { name: "1 pending decisions", exact: true }).click();
  await expect(page).toHaveURL(/#\/inbox$/);

  const decision = page.getByRole("article").filter({
    hasText: "Approve the e2e outbound update?",
  });
  await expect(decision).toBeVisible();
  await decision.getByRole("button", { name: "approve", exact: true }).click();
  await expect(
    decision.getByRole("button", { name: "Confirm approve" }),
  ).toBeVisible();
  await expect(decision).toBeVisible();

  await decision.getByRole("button", { name: "Confirm approve" }).click();
  await expect(decision).toBeHidden();
  await expect(page.getByRole("button", {
    name: "Open Inbox, 0 pending decisions",
  })).toBeVisible();
  await expect(page.getByText("Nothing waiting")).toBeVisible();

  await page.getByRole("button", { name: "Refresh" }).click();
  await expect(page.getByText("Nothing waiting")).toBeVisible();
  const pending = await page.request.get("/v1/hitl");
  expect(pending.ok()).toBeTruthy();
  expect((await pending.json()).requests).toEqual([]);
});

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

    expect(blockingViolations(blocking)).toEqual([]);
  });
}

function blockingViolations(
  violations: Array<{
    id: string;
    impact?: string | null;
    help: string;
    nodes: Array<{ target?: unknown; html?: string }>;
  }>,
): string[] {
  return violations
    .filter(({ impact }) => impact === "serious" || impact === "critical")
    .map(({ id, impact, help, nodes }) =>
      `${impact ?? "unknown"} ${id}: ${help} (${nodes.length} node(s): ${
        nodes.map(({ target, html }) => (
          JSON.stringify(target ?? html ?? "unknown")
        )).join(", ")
      })`
    );
}
