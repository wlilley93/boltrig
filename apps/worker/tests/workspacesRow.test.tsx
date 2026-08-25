// @vitest-environment happy-dom

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

/** The way back out of the agent console.
 *
 *  "/" opens this console once a team box is answering, which is the right
 *  default - people want their agent. But everything ABOUT the box lives on the
 *  other side: the address a desktop client connects to, the team, and adding
 *  another. Without this door, arriving here is one-way for exactly the people
 *  who have a box.
 */

const api = vi.hoisted(() => ({
  meSettings: vi.fn(),
  putMeSettings: vi.fn(),
}));

vi.mock("../src/client", () => ({ client: api, isDesktop: false }));

const { CompactYouSection } = await import("../src/components/settings/CompactSections");

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function account() {
  return {
    profile: {
      id: "usr_1",
      display_name: "Will",
      email: "will@example.com",
      role: "owner",
    },
    settings: {},
  };
}

describe("the workspaces door", () => {
  it("points at the workspace view on this origin", async () => {
    api.meSettings.mockResolvedValue(account());
    render(<CompactYouSection />);
    const door = await screen.findByRole("link", { name: "Open" });

    // SAME ORIGIN, so the session cookie travels with an ordinary navigation
    // and the person arrives already signed in. An absolute URL to another host
    // would drop the cookie and land them on a sign-in page they have already
    // passed.
    expect(door.getAttribute("href")).toBe("/?workspace");

    // A QUERY, NOT A PATH. The workspace console reads its own mount off the
    // document's directory, so at /workspace it addresses its API at
    // /workspace/api/... - measured live, that rendered "Boltrig is
    // unreachable. Unexpected response (200)."
    expect(door.getAttribute("href")).not.toContain("/workspace/");
  });

  it("is a link and not a button", async () => {
    // Middle-click, open-in-new-tab and the hover destination all come from
    // being an anchor. A button that navigates takes all three away and gives
    // nothing back - it only ever looked the same, which the class already
    // handles.
    api.meSettings.mockResolvedValue(account());
    render(<CompactYouSection />);
    const door = await screen.findByRole("link", { name: "Open" });
    expect(door.tagName).toBe("A");
    expect(door).toHaveProperty("className", "settings-kit-button");
  });

  it("renders even though nothing verifies the room behind it", async () => {
    // It probes for nothing on purpose. There is no call that can fail, and a
    // door that hides itself when it cannot check the other side is worse than
    // one that opens onto a page explaining why.
    api.meSettings.mockResolvedValue(account());
    render(<CompactYouSection />);
    expect(await screen.findByText("Your workspaces")).toBeTruthy();
  });
});
