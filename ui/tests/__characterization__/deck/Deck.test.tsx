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
});
