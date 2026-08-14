// @vitest-environment happy-dom

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AttachmentStatus } from "../src/components/chat/ComposerAttachments";

afterEach(cleanup);

describe("composer attachments", () => {
  it("shows an image thumbnail and keeps removal explicit", () => {
    const file = {
      name: "reference.png",
      media_type: "image/png",
      data: "aW1hZ2U=",
      size: 5,
    };
    const remove = vi.fn();
    render(
      <AttachmentStatus
        attachmentLimits={{
          max_count: 8,
          max_bytes: 262_144,
          max_total_bytes: 1_048_576,
          model_readable_media_types: ["image/*"],
        }}
        fileError=""
        files={[file]}
        onRemove={remove}
      />,
    );

    const image = document.querySelector<HTMLImageElement>(".composer-attachment-visual img");
    expect(image?.src).toBe("data:image/png;base64,aW1hZ2U=");
    expect(screen.getByText("reference.png")).toBeTruthy();
    expect(screen.getByText("model-readable")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Remove reference.png" }));
    expect(remove).toHaveBeenCalledWith(file);
  });
});
