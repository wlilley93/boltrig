import { afterEach, describe, it, expect } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { FilesPanel } from "@/panels/chat/FilesPanel";
import type { ChatAttachment, ChatMessage } from "@/api/types";

describe("FilesPanel", () => {
  afterEach(() => {
    cleanup();
  });

  it("renders all three sections: This session, Pinned, and Recent", () => {
    const attachment: ChatAttachment = {
      name: "plan.md",
      size: 1024,
      media_type: "text/markdown",
    } as ChatAttachment;
    render(
      <FilesPanel
        attachments={[attachment]}
        messages={[] as ChatMessage[]}
        onClose={() => undefined}
      />,
    );

    const sections = screen.getAllByText(/^(This session|Pinned|Recent)$/);
    expect(sections.length).toBe(3);
    expect(screen.getByText("This session")).toBeTruthy();
    expect(screen.getByText("Pinned")).toBeTruthy();
    expect(screen.getByText("Recent")).toBeTruthy();
  });

  it("shows the View all link in the footer", () => {
    render(
      <FilesPanel
        attachments={[] as ChatAttachment[]}
        messages={[] as ChatMessage[]}
        onClose={() => undefined}
      />,
    );
    expect(screen.getByRole("button", { name: "View all" })).toBeTruthy();
  });

  it("renders Recent rows dimmer and without a download icon", () => {
    render(
      <FilesPanel
        attachments={[] as ChatAttachment[]}
        messages={[] as ChatMessage[]}
        onClose={() => undefined}
      />,
    );

    // A known Recent placeholder row should be dimmed.
    const recentName = screen.getByText("release-notes.md");
    const recentRow = recentName.closest(".file-row");
    expect(recentRow).toBeTruthy();
    expect(recentRow?.classList.contains("file-row--dim")).toBe(true);
    // No download button on Recent rows.
    expect(recentRow?.querySelector('button[aria-label^="Download "]')).toBeNull();
  });

  it("keeps the download icon on This session and Pinned rows", () => {
    const attachment: ChatAttachment = {
      name: "plan.md",
      size: 1024,
      media_type: "text/markdown",
    } as ChatAttachment;
    render(
      <FilesPanel
        attachments={[attachment]}
        messages={[] as ChatMessage[]}
        onClose={() => undefined}
      />,
    );

    // This session row keeps its download button.
    const sessionName = screen.getByText("plan.md");
    const sessionRow = sessionName.closest(".file-row");
    expect(sessionRow?.querySelector('button[aria-label="Download plan.md"]')).toBeTruthy();

    // Pinned rows keep their download buttons too.
    const pinnedName = screen.getByText("architecture.md");
    const pinnedRow = pinnedName.closest(".file-row");
    expect(pinnedRow?.querySelector('button[aria-label="Download architecture.md"]')).toBeTruthy();
    expect(pinnedRow?.classList.contains("file-row--dim")).toBe(false);
  });
});
