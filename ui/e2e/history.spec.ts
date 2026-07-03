// History smoke (US-CONV-09 / US-CONV-10): the conversation rail searches and
// paginates against the real kernel. Hermetic like the chat smoke: no model
// keys, the deterministic "(no runtime configured)" reply seeds a conversation
// whose title we then search for. Asserts the search flips the rail to results,
// a non-matching term shows the calm empty state, and clearing the box restores
// the paginated list (with the seeded conversation still present).

import { expect, test } from "@playwright/test";

test("conversation search filters the rail and clearing restores the list", async ({
  page,
}) => {
  await page.goto("/#/chat");

  const composer = page.getByPlaceholder("Message the orchestrator...");
  await expect(composer).toBeVisible();

  // Seed a conversation: the kernel titles it from the first line of the message.
  await composer.fill("apricot pagination probe");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.locator(".chat-msg--assistant").last()).toContainText(
    "(no runtime configured)",
  );

  const rail = page.locator(".chat__rail");
  // The seeded conversation shows in the paginated list.
  await expect(
    rail.locator(".conv-item__title", { hasText: "apricot" }),
  ).toBeVisible();

  // Searching flips the rail to results and matches the seeded conversation.
  const search = page.getByPlaceholder("Search conversations");
  await search.fill("apricot");
  await expect(rail.getByText("Search results")).toBeVisible();
  await expect(
    rail.locator(".conv-item__title", { hasText: "apricot" }),
  ).toBeVisible();

  // A non-matching term shows the empty state (the endpoint is still called;
  // only an empty query is suppressed).
  await search.fill("zzznomatchzzz");
  await expect(rail.getByText("No matches")).toBeVisible();

  // Clearing the box restores the paginated list immediately.
  await search.fill("");
  await expect(rail.getByText("Conversations", { exact: true })).toBeVisible();
  await expect(
    rail.locator(".conv-item__title", { hasText: "apricot" }),
  ).toBeVisible();
});
