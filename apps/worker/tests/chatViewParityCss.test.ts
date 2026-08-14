import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const css = readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), "../src/components/chat/ChatViewParity.css"),
  "utf-8",
);
const workerCss = readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), "../src/styles.css"),
  "utf-8",
);
const chatCss = readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), "../src/components/chat/chat.css"),
  "utf-8",
);

describe("Chat parity geometry", () => {
  it("keeps the Codex-dark Chat canvas neutral without overriding the shared rail tint", () => {
    expect(css).toContain(':root[data-theme="dark"] .surface:has(.chat-layout)');
    expect(css).toContain("background: #171717");
    expect(css).not.toContain(".sidebar.shell-parity");
  });

  it("keeps the active composer compact without changing New or closed states", () => {
    expect(css).toContain(
      ".chat-main > .composer.conversation-context:not(.closed) textarea",
    );
    expect(css).toContain("height: 37px");
    expect(css).toContain("min-height: 37px");
    expect(css).toContain(".chat-main .composer .composer-tools .icon-button");
    expect(css).toContain("width: 28px");
    expect(css).toContain(".chat-main .composer-frame:focus-within");
    expect(css).toContain(".chat-main .transcript:focus-visible");
    expect(css).toContain("border-color: var(--accent)");
  });

  it("sizes either New-chat companion at the canonical 30px", () => {
    expect(css).toContain(".voice-intro > .familiar-stage.conversation");
    expect(css).toContain(".voice-intro > .jarvis-stage");
    expect(css).toContain("width: 30px");
    expect(css).toMatch(/\.voice-intro > \.jarvis-stage\s*\{[^}]*height:\s*30px[^}]*min-height:\s*30px/);
  });

  it("keeps the semantic New-chat h1 on the decided centred 28px treatment", () => {
    expect(workerCss).toMatch(/\.welcome h1,\s*\n\.welcome h2\s*\{[^}]*margin:\s*0/);
    expect(workerCss).toMatch(/\.welcome h1,\s*\n\.welcome h2\s*\{[^}]*font-size:\s*28px/);
    expect(workerCss).toMatch(/\.welcome h1,\s*\n\.welcome h2\s*\{[^}]*text-align:\s*center/);
    expect(workerCss).toMatch(/\.welcome h1,\s*\n\.welcome h2\s*\{[^}]*height:\s*38px/);
    expect(workerCss).toMatch(/\.welcome h1,\s*\n\.welcome h2\s*\{[^}]*line-height:\s*34px/);
    expect(workerCss).toMatch(/\.new-chat-transcript \.welcome\s*\{[^}]*transform:\s*none/);
    expect(chatCss).toMatch(/\.transcript\.new-chat-transcript\s*\{[^}]*justify-content:\s*stretch/);
    expect(chatCss).toMatch(/\.new-chat-transcript \.welcome\s*\{[^}]*grid-template-rows:\s*minmax\(0, 1fr\) auto/);
    expect(workerCss).not.toContain(".welcome .starter-card");
  });

  it("uses the canonical inner turn gutter and section rhythm", () => {
    expect(css).toContain(".transcript:not(.new-chat-transcript) > .message");
    expect(css).toContain("padding-left: 24px");
    expect(css).toContain(".message.assistant > .message-content");
    expect(css).toContain("gap: 24px");
    expect(css).toContain("font-size: 14.5px");
  });

  it("keeps the desktop Chat header controls at their target geometry", () => {
    expect(css).toContain(".chat-header .chat-header-sub");
    expect(css).toContain("font-size: 12.5px");
    expect(css).toContain(".chat-header .chat-header-actions > .icon-button");
  });
});
