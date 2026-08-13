import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const sourceRoot = join(dirname(fileURLToPath(import.meta.url)), "../src");
const appSource = readFileSync(join(sourceRoot, "App.tsx"), "utf-8");
const appFrameSource = readFileSync(
  join(sourceRoot, "components/shell/AppFrame.tsx"),
  "utf-8",
);
const routeSurfaceSource = readFileSync(
  join(sourceRoot, "components/shell/AppRouteSurface.tsx"),
  "utf-8",
);
const chatSource = readFileSync(join(sourceRoot, "components/ChatView.tsx"), "utf-8");
const inspectorSource = readFileSync(
  join(sourceRoot, "components/chat/TaskInspector.tsx"),
  "utf-8",
);
const inspectorModelSource = readFileSync(
  join(sourceRoot, "components/chat/TaskInspectorModel.ts"),
  "utf-8",
);

describe("chat presentation boundaries", () => {
  it("keeps the route-heavy chat and command surfaces outside the initial app chunk", () => {
    expect(routeSurfaceSource).toContain('import("../ChatView")');
    expect(appFrameSource).toContain('import("../CommandPalette")');
    expect(appSource).not.toContain('import { ChatView } from "./components/ChatView"');
    expect(appSource).not.toContain('import { CommandPalette } from "./components/CommandPalette"');
  });

  it("keeps viewport and task-inspector behavior outside the ChatView monolith", () => {
    expect(chatSource).toContain('from "./chat/TaskInspector"');
    expect(chatSource).toContain('from "./chat/useChatModelOptions"');
    expect(chatSource).toContain('from "./chat/useChatProjection"');
    expect(chatSource).toContain('from "./chat/useTranscriptViewport"');
    expect(chatSource).toContain("<TaskInspector");
    expect(chatSource).toContain("<TranscriptNavigation");
    expect(chatSource).not.toContain("function RightRail(");
    expect(chatSource).not.toContain("function RailGroup(");
    expect(chatSource).not.toContain("followTranscriptRef");
  });

  it("keeps the inspector a lossy callback surface instead of a second backend", () => {
    expect(inspectorSource).not.toContain("client.");
    expect(inspectorModelSource).not.toContain("tool.args");
    expect(inspectorModelSource).not.toContain("tool.result");
    expect(inspectorModelSource).not.toContain("attachment.data");
    expect(inspectorModelSource).not.toContain("subagent.task");
  });
});
