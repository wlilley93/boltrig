import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";
import { Deck, type DeckRow } from "@/deck/Deck";

describe("Deck", () => {
  it("renders the active cell", () => {
    window.location.hash = "#/chat";
    const rows: DeckRow[] = [
      {
        id: "chat",
        label: "Chat",
        cols: [{ key: "main", label: "Main", path: "/chat" }],
      },
    ];
    const { container } = render(
      <Deck
        rows={rows}
        active={{ rowId: "chat", colKey: "main" }}
        render={() => <div data-testid="cell">Cell</div>}
      />,
    );
    expect(container.querySelector('[data-testid="cell"]')).toBeTruthy();
  });

  it("renders chevrons for adjacent slides", () => {
    window.location.hash = "#/settings/account";
    const rows: DeckRow[] = [
      {
        id: "settings",
        label: "Settings",
        cols: [
          { key: "account", label: "Account", path: "/settings/account" },
          { key: "appearance", label: "Appearance", path: "/settings/appearance" },
        ],
      },
    ];
    const { container } = render(
      <Deck
        rows={rows}
        active={{ rowId: "settings", colKey: "account" }}
        render={() => <div data-testid="cell">Cell</div>}
      />,
    );
    expect(container.querySelector(".deck__chevron--right")).toBeTruthy();
  });

  it("keeps a visited keep-alive cell mounted", () => {
    window.location.hash = "#/chat";
    const rows: DeckRow[] = [
      {
        id: "chat",
        label: "Chat",
        cols: [{ key: "main", label: "Main", path: "/chat" }],
      },
    ];
    const { container, rerender } = render(
      <Deck
        rows={rows}
        active={{ rowId: "chat", colKey: "main" }}
        keepAlive={["chat:main"]}
        render={(rowId, colKey) => (
          <div data-testid={`cell-${rowId}-${colKey}`}>Cell</div>
        )}
      />,
    );
    rerender(
      <Deck
        rows={rows}
        active={{ rowId: "chat", colKey: "main" }}
        keepAlive={["chat:main"]}
        render={(rowId, colKey) => (
          <div data-testid={`cell-${rowId}-${colKey}`}>Cell</div>
        )}
      />,
    );
    expect(container.querySelector('[data-testid="cell-chat-main"]')).toBeTruthy();
  });
});
