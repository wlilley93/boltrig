// The one smoke ([2026] VJS-COUNTY 2, D3): load the chat surface, send a
// message, and assert the kernel's deterministic no-runtime reply renders.
// This proves the built SPA boots, the dev-identity headers authenticate
// against the real kernel, and POST /v1/chat streams end to end, with zero
// model keys and zero credentials (contract: boltrig/fleet/chat.py, the
// "(no runtime configured)" text_delta when no turn executor is wired).

import { expect, test } from "@playwright/test";

test("chat turn renders the deterministic '(no runtime configured)' reply", async ({
  page,
}) => {
  await page.goto("/#/chat");

  const composer = page.getByPlaceholder("Type a message");
  await expect(composer).toBeVisible();

  await composer.fill("hello from the e2e smoke");
  await page.getByRole("button", { name: "Send" }).click();

  await expect(page.locator(".chat-msg--assistant").last()).toContainText(
    "(no runtime configured)",
  );
});
