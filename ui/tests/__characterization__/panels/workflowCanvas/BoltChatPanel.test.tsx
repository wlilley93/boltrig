import { afterEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { consumeComposerPrefill } from "@/composerPrefill";
import { BoltChatPanel } from "@/panels/workflowCanvas/BoltChatPanel";

afterEach(() => {
  cleanup();
  consumeComposerPrefill();
  window.location.hash = "";
});

describe("BoltChatPanel", () => {
  it("hands a reviewable draft to Chat without changing or publishing the canvas", () => {
    render(
      <BoltChatPanel
        open
        onToggle={() => undefined}
        workflowId="release"
        steps={[{ id: "fetch", parents: [], action: "web.fetch", params: { url: "https://example.com" } }]}
      />,
    );

    expect(screen.getByText(/nothing is published or changed automatically/i)).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Proposed workflow change"), {
      target: { value: "Add an approval before fetch" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Continue in Chat" }));

    expect(window.location.hash).toContain("/chat");
    const prompt = consumeComposerPrefill();
    expect(prompt).toContain('workflow "release"');
    expect(prompt).toContain("Add an approval before fetch");
    expect(prompt).toContain('"action": "web.fetch"');
    expect(prompt).toContain("canvas has not been changed");
  });

  it("does not create a request from an empty draft", () => {
    render(<BoltChatPanel open onToggle={() => undefined} workflowId="" steps={[]} />);
    expect(screen.getByRole("button", { name: "Continue in Chat" }).hasAttribute("disabled")).toBe(true);
    expect(consumeComposerPrefill()).toBeNull();
  });
});
