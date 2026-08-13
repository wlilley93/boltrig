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
const shellSource = readFileSync(join(sourceRoot, "components/Shell.tsx"), "utf-8");
const taskListSource = readFileSync(
  join(sourceRoot, "components/shell/TaskList.tsx"),
  "utf-8",
);
const settingsSource = readFileSync(
  join(sourceRoot, "components/SettingsSurface.tsx"),
  "utf-8",
);
const operationsSettingsSource = readFileSync(
  join(sourceRoot, "components/settings/OperationsSettingsSection.tsx"),
  "utf-8",
);

describe("shell rollout boundary", () => {
  it("keeps one route-preserving shell bootstrap with extracted navigation and tasks", () => {
    expect(appSource).toContain('import { AppFrame } from "./components/shell/AppFrame"');
    expect(appFrameSource).toContain('import { Sidebar } from "../Shell"');
    expect(routeSurfaceSource).toContain('import("../ChatView")');
    expect(appFrameSource).toContain('import("../CommandPalette")');
    expect(shellSource).toContain('from "./shell/ShellNav"');
    expect(shellSource).toContain('from "./shell/TaskList"');
    expect(shellSource).toContain("<ShellNav");
    expect(shellSource).toContain("<TaskList");
  });

  it("keeps presentation storage behind its adapter instead of re-growing Shell", () => {
    expect(shellSource).not.toContain("localStorage");
    expect(taskListSource).not.toContain("localStorage");
    expect(taskListSource).toContain('from "./shellPreferences"');
    expect(taskListSource).not.toContain("searchConversations");
  });

  it("keeps mobile settings and operational evidence behind route-time chunks", () => {
    expect(routeSurfaceSource).toContain('import("../MobileSettings")');
    expect(routeSurfaceSource).toContain('import("../settings/SearchResults")');
    expect(routeSurfaceSource).not.toContain('import { MobileSettings } from "../MobileSettings"');
    expect(settingsSource).not.toContain('from "./OperationsView"');
    expect(operationsSettingsSource).toContain('import("../OperationsView")');
  });
});
