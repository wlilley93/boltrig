import { createHash } from "node:crypto";
import { lstat, readFile, readdir, readlink } from "node:fs/promises";
import { join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import manifest from "./states.json";

const canonicalStateIds = [
  "new-chat",
  "chat-run",
  "agents",
  "plugins",
  "command-palette",
  "call",
  "settings-you",
] as const;
const additiveStateIds = ["chat-direction"] as const;
const unboundWorkspacePanelSelectors = [
  '.right-rail .rail-group[aria-label="Files"]',
  '.right-rail .rail-group[aria-label="Changes"]',
  '.right-rail .rail-group[aria-label="Git changes"]',
  '.right-rail .rail-group[aria-label="Processes"]',
  '.right-rail .rail-group[aria-label="Terminal"]',
] as const;

type DirectionState = (typeof manifest.states)[number] & {
  required_presence_selectors: string[];
  required_absence_selectors: string[];
  required_visible_selectors: string[];
  required_text: string[];
  required_absent_text: string[];
  required_geometry: Array<{
    selector: string;
    width?: number;
    height?: number;
    y?: number;
  }>;
  required_visible_counts: Array<{ selector: string; count: number }>;
  required_computed_styles: Array<{ selector: string; property: string; value: string }>;
  direction_records: string[];
  reference_digest_manifest: string;
  shipped_digest_manifest: string;
  current_output: string;
  target_reference_paths: string[];
  negative_reference_paths: string[];
};

type ContractState = (typeof manifest.states)[number] & {
  required_presence_selectors: string[];
  required_absence_selectors: string[];
  required_visible_selectors: string[];
  required_text: string[];
  required_exact_text?: Array<{
    selector: string;
    text: string;
  }>;
  required_visible_counts?: Array<{
    selector: string;
    count: number;
  }>;
  required_absent_text: string[];
  required_geometry: Array<{
    selector: string;
    width?: number;
    height?: number;
    x?: number;
    y?: number;
  }>;
  required_computed_styles?: Array<{
    selector: string;
    property: string;
    value: string;
  }>;
  direction_records: string[];
};

const sourceScope = ["apps/worker/src", "apps/worker/tests/visual"] as const;
const repoRootPath = fileURLToPath(new URL("../../../../", import.meta.url));

async function sourceTreeDigest(): Promise<string> {
  const digest = createHash("sha256");
  for (const scope of sourceScope) {
    for (const path of await walk(join(repoRootPath, scope))) {
      const metadata = await lstat(path);
      const relativePath = relative(repoRootPath, path).split(sep).join("/");
      digest.update(`${relativePath}\0`);
      if (metadata.isSymbolicLink()) {
        digest.update(`symlink\0${await readlink(path)}\0`);
      } else {
        digest.update("file\0");
        digest.update(await readFile(path));
        digest.update("\0");
      }
    }
  }
  return digest.digest("hex");
}

async function walk(root: string): Promise<string[]> {
  const paths: string[] = [];
  for (const entry of await readdir(root, { withFileTypes: true })) {
    if (
      entry.name === ".DS_Store"
      || entry.name === "__pycache__"
      || entry.name.endsWith(".pyc")
    ) continue;
    const path = join(root, entry.name);
    if (entry.isDirectory()) paths.push(...await walk(path));
    else if (entry.isFile() || entry.isSymbolicLink()) paths.push(path);
  }
  return paths.sort((left, right) => (left === right ? 0 : left < right ? -1 : 1));
}

describe("console parity evidence manifest", () => {
  it("keeps the seven canonical states in order and appends additive evidence", () => {
    expect(manifest.schema).toBe("boltrig-worker-visual-states.v2");
    expect(manifest.viewport).toEqual({ width: 1440, height: 900 });
    expect(manifest.governed_state_ids).toEqual(canonicalStateIds);
    expect(manifest.additive_state_ids).toEqual(additiveStateIds);
    expect(manifest.current_capture_root).toBe(
      "docs/design/evidence/2026-08-11-console-parity/current",
    );
    expect(manifest.additive_capture_root).toBe(
      "docs/design/evidence/2026-08-11-chat-ui-direction/current",
    );
    expect(manifest.states.slice(0, canonicalStateIds.length).map((state) => state.id))
      .toEqual(canonicalStateIds);
    expect(manifest.states.slice(canonicalStateIds.length).map((state) => state.id))
      .toEqual(additiveStateIds);
    expect(manifest.base_url_note).toContain("replace only this origin and port");
  });

  it("gives every state one deterministic URL, readiness contract and output", () => {
    for (const state of manifest.states) {
      const url = new URL(state.url);
      expect(url.origin).toBe(manifest.base_url);
      expect(url.pathname).toBe("/tests/visual/parity.html");
      expect(url.searchParams.get("state")).toBe(state.id);
      expect(url.searchParams.get("theme")).toBe("dark");
      expect(state.settled_selector).toBe(
        `html[data-visual-ready="${state.id}"]`,
      );
      expect(state.settled_when.length).toBeGreaterThan(40);
      expect(state.required_request_prefixes.length).toBeGreaterThan(0);
      expect(state.known_contract_bound_deviations.length).toBeGreaterThan(0);
      expect(state.output).toBe(state.id === "chat-direction"
        ? "docs/design/evidence/2026-08-11-chat-ui-direction/shipped/chat-direction.png"
        : `docs/design/evidence/2026-08-11-console-parity/shipped/${state.id}.png`);
      if (manifest.governed_state_ids.includes(state.id as typeof canonicalStateIds[number])) {
        expect("current_output" in state ? state.current_output : null).toBe(
          `docs/design/evidence/2026-08-11-console-parity/current/shipped/${state.id}.png`,
        );
      } else {
        expect("current_output" in state ? state.current_output : null).toBe(
          `${manifest.additive_capture_root}/shipped/${state.id}.png`,
        );
      }
    }
  });

  it("gives every governed state one unique durable current-source output", () => {
    const governed = manifest.governed_state_ids.map((id) => (
      manifest.states.find((state) => state.id === id)
    ));
    expect(governed.every(Boolean)).toBe(true);
    const outputs = governed.map((state) => (
      state && "current_output" in state ? state.current_output : null
    ));
    expect(new Set(outputs).size).toBe(canonicalStateIds.length);
    for (const [index, output] of outputs.entries()) {
      expect(output).toBe(
        `${manifest.current_capture_root}/shipped/${canonicalStateIds[index]}.png`,
      );
    }
    const targetNodes = governed.map((state) => state?.figma_node_id);
    const targets = governed.map((state) => state?.target_output);
    expect(targetNodes).toEqual(["13:2", "5:2", "15:2", "14:2", "16:2", "17:2", "22:2"]);
    expect(new Set(targets).size).toBe(canonicalStateIds.length);
    for (const target of targets) {
      expect(target).toMatch(
        /^docs\/design\/evidence\/2026-08-11-console-parity\/figma\/.+\.png$/,
      );
    }
  });

  it("does not require phenotype traffic from the shipped Familiar state", () => {
    const newChat = manifest.states.find((state) => state.id === "new-chat");
    expect(newChat).toBeDefined();
    expect(newChat!.required_request_prefixes).not.toContain("/v1/familiar/phenotype");
    expect(newChat!.settled_when).toContain("not fetched by the idle Familiar");
  });

  it("opens the command palette over the same completed run-thread contract as Chat run", () => {
    const chatRun = manifest.states.find((state) => state.id === "chat-run") as
      | ContractState
      | undefined;
    const palette = manifest.states.find((state) => state.id === "command-palette") as
      | ContractState
      | undefined;

    expect(chatRun).toBeDefined();
    expect(palette).toBeDefined();
    expect(palette!.hash).toBe(chatRun!.hash);
    expect(palette!.required_request_prefixes).toEqual(chatRun!.required_request_prefixes);
    expect(palette!.settled_when).toContain("completed run-thread conversation is active and settled before");
    expect(palette!.known_contract_bound_deviations).toContain(
      "The background is the same completed persisted turn as Chat run; no live HITL, computer-use or spend state is fabricated.",
    );
    expect(palette!.direction_records).toEqual([
      "DIR-0006", "DIR-0010", "DIR-0011", "DIR-0012", "DIR-0015", "DIR-0016", "DIR-0017", "DIR-0018",
    ]);
    expect(palette!.required_presence_selectors).toEqual(expect.arrayContaining([
      ".sidebar.shell-parity",
      "#shell-pinned-tasks.shell-task-group-label",
      "#shell-recent-tasks.shell-task-group-label",
      ".transcript-navigation[aria-label=\"Transcript navigation\"]",
      ".right-rail .chat-rail-glass",
      ".command-palette[data-screen-label=\"Command palette\"]",
      ".command-search input[aria-label=\"Search Worker\"]",
      ".command-row.active",
    ]));
    expect(palette!.required_absence_selectors).toEqual(expect.arrayContaining([
      ".side-status",
      ".side-status-dot",
      ".conversation-search",
      ".side-recents-label",
      ".side-workspace",
      ".message-author",
      ".subagent-fanout",
      ".right-rail [aria-label=\"Conversation title\"]",
      ...unboundWorkspacePanelSelectors,
    ]));
    expect(palette!.required_visible_selectors).toEqual(expect.arrayContaining([
      ".command-palette[data-screen-label=\"Command palette\"]",
      ".command-search",
      ".command-results",
      ".command-row.active",
    ]));
    expect(palette!.required_visible_counts).toContainEqual({
      selector: ".command-group[aria-label=\"Navigation commands\"] > .command-row",
      count: 8,
    });
    expect(palette!.required_visible_counts).toEqual(expect.arrayContaining([
      { selector: ".shell-task-group-label", count: 2 },
      { selector: ".transcript-navigation", count: 1 },
      { selector: ".transcript-navigation > button", count: 2 },
    ]));
    expect(palette!.required_geometry).toEqual(expect.arrayContaining([
      { selector: ".command-palette", x: 660, y: 135, width: 560, height: 335 },
      { selector: ".command-search", x: 661, y: 136, width: 558, height: 48 },
    ]));
    expect(palette!.required_exact_text).toEqual(expect.arrayContaining([
      { selector: "#shell-pinned-tasks", text: "Pinned" },
      { selector: "#shell-recent-tasks", text: "Recents" },
      { selector: ".command-row:nth-child(1) .command-row-label", text: "New chat" },
      { selector: ".command-row:nth-child(6) .command-row-label", text: "Camera and presence settings" },
      { selector: ".command-row:nth-child(8) .command-row-label", text: "Spending settings" },
    ]));
    expect(palette!.required_absent_text).toEqual(expect.arrayContaining([
      "Governed by Boltrig",
      "Conversation settings",
      "Everything responding",
      "This run",
      "acme · production",
    ]));
  });

  it("fails Plugins closed on its visible health, inventory and Figma geometry", () => {
    const plugins = manifest.states.find((state) => state.id === "plugins") as
      | ContractState
      | undefined;

    expect(plugins).toBeDefined();
    expect(plugins!.direction_records).toEqual(["DIR-0004", "DIR-0010", "DIR-0015", "DIR-0016"]);
    expect(plugins!.required_presence_selectors).not.toContain(".sidebar.shell-parity");
    expect(plugins!.required_presence_selectors).toEqual(expect.arrayContaining([
      ".plugins-pane",
      ".plugins-alert[aria-label=\"Connection health issues\"]",
      ".plugins-search input[aria-label=\"Search integrations\"]",
      ".plugins-groups",
    ]));
    expect(plugins!.required_absence_selectors).toEqual(expect.arrayContaining([
      ".side-status",
      ".side-status-dot",
      ".conversation-search",
      ".right-rail",
      ".plugins-api-state",
      ".plugins-row-detail",
    ]));
    expect(plugins!.required_visible_selectors).toEqual(expect.arrayContaining([
      ".plugins-heading h1",
      ".plugins-alert > button",
      ".plugins-inventory-heading",
      ".plugins-filter-button",
      ".plugins-group:first-child > header",
      ".plugins-group:first-child .plugins-row:first-child .plugins-row-toggle",
    ]));
    expect(plugins!.required_text).toContain("9 connected of 43");
    expect(plugins!.required_geometry).toEqual(expect.arrayContaining([
      { selector: ".plugins-pane", x: 401, width: 900 },
      { selector: ".plugins-alert", x: 433, y: 162.5625, width: 836, height: 64.125 },
      { selector: ".plugins-search", y: 277.6875, height: 38 },
      { selector: ".plugins-group:first-child .plugins-row:first-child", height: 57 },
      {
        selector: ".plugins-group:first-child .plugins-row:first-child .plugins-row-toggle",
        height: 56,
      },
    ]));
    expect(plugins!.required_exact_text).toEqual(expect.arrayContaining([
      { selector: ".plugins-heading h1", text: "Plugins" },
      { selector: ".plugins-alert-copy strong", text: "Two need you" },
      { selector: ".plugins-alert > button", text: "Look at both" },
      { selector: ".plugins-inventory-heading h2", text: "Connections" },
    ]));
    expect(plugins!.required_absent_text).toEqual(expect.arrayContaining([
      "Governed by Boltrig",
      "Everything responding",
      "This run",
    ]));
  });

  it("fails New chat and Chat run closed on their Figma plus Codex direction contracts", () => {
    const newChat = manifest.states.find((state) => state.id === "new-chat") as
      | ContractState
      | undefined;
    const chatRun = manifest.states.find((state) => state.id === "chat-run") as
      | ContractState
      | undefined;

    for (const state of [newChat, chatRun]) {
      expect(state).toBeDefined();
      expect(state!.direction_records).toEqual([
        "DIR-0008", "DIR-0009", "DIR-0010", "DIR-0011", "DIR-0012", "DIR-0015", "DIR-0016", "DIR-0017", "DIR-0018",
      ]);
      expect(state!.required_presence_selectors).toContain(".sidebar.shell-parity");
      expect(state!.required_presence_selectors).toEqual(expect.arrayContaining([
        ".shell-task-group[aria-labelledby=\"shell-pinned-tasks\"]",
        ".shell-task-group[aria-labelledby=\"shell-recent-tasks\"]",
        "#shell-pinned-tasks.shell-task-group-label",
        "#shell-recent-tasks.shell-task-group-label",
      ]));
      expect(state!.required_presence_selectors).not.toContain(".conversation-search");
      expect(state!.required_absence_selectors).toEqual(expect.arrayContaining([
        ".side-status",
        ".conversation-search",
        ".side-recents-label",
        ".side-workspace",
        ".message-author",
        ".subagent-fanout",
        ...unboundWorkspacePanelSelectors,
      ]));
      expect(state!.required_absent_text).toEqual(expect.arrayContaining([
        "Governed by Boltrig",
        "Conversation settings",
        "Everything responding",
        "acme · production",
      ]));
    }

    expect(newChat!.required_visible_selectors).toEqual(expect.arrayContaining([
      ".new-chat-transcript .welcome h1",
      ".new-chat-transcript .composer.new-context",
      ".new-chat-transcript button[aria-label=\"Model\"]",
      ".voice-intro",
    ]));
    expect(newChat!.required_geometry).toEqual(expect.arrayContaining([
      { selector: ".new-chat-transcript .welcome", x: 480.5, y: 255.5, width: 745, height: 405 },
      { selector: ".new-chat-transcript .composer.new-context", x: 480.5, y: 382.5, width: 745, height: 122 },
      { selector: ".new-chat-transcript .starters", x: 480.5, y: 526.5, width: 745, height: 134 },
      { selector: ".voice-intro", x: 480.5, y: 315.5, width: 745, height: 57 },
    ]));
    expect(newChat!.required_visible_counts).toContainEqual({
      selector: ".sidebar-footer > button",
      count: 2,
    });
    expect(newChat!.required_visible_counts).toContainEqual({
      selector: ".composer .voice-primary",
      count: 1,
    });
    expect(newChat!.required_visible_counts).toEqual(expect.arrayContaining([
      { selector: ".shell-task-group-label", count: 2 },
      {
        selector: ".shell-task-group[aria-labelledby=\"shell-pinned-tasks\"] .session-row",
        count: 1,
      },
      {
        selector: ".shell-task-group[aria-labelledby=\"shell-recent-tasks\"] .session-row",
        count: 3,
      },
    ]));
    expect(newChat!.required_absence_selectors).toContain(".transcript-navigation");
    expect(newChat!.required_absence_selectors)
      .toContain('.composer-context-item[title*="Project"]');
    expect(newChat!.required_absent_text).toContain("No project selected");
    expect(newChat!.known_contract_bound_deviations).toContain(
      "Project and host selectors are omitted until a canonical task-context field exists; the fixture does not manufacture a selection control.",
    );
    expect(newChat!.required_presence_selectors)
      .toContain(".composer-voice-controller[hidden]");
    expect(newChat!.required_absence_selectors)
      .toContain(".composer-voice-controller:not([hidden])");
    expect(newChat!.required_computed_styles).toContainEqual({
      selector: ".composer-voice-controller",
      property: "display",
      value: "none",
    });
    expect(chatRun!.required_visible_selectors).toEqual(expect.arrayContaining([
      ".session-row.active .session-actions",
      ".transcript-tool-summary",
      ".transcript-subagent-chip",
      ".transcript-navigation[aria-label=\"Transcript navigation\"]",
      ".right-rail .chat-rail-glass",
    ]));
    expect(chatRun!.required_geometry).toContainEqual({
      selector: ".right-rail .chat-rail-glass",
      width: 302,
      y: 16,
    });
    expect(chatRun!.required_visible_counts).toEqual(expect.arrayContaining([
      { selector: ".shell-task-group-label", count: 2 },
      { selector: ".transcript-navigation", count: 1 },
      { selector: ".transcript-navigation > button", count: 2 },
      { selector: ".transcript-tool-summary", count: 1 },
      { selector: ".right-rail .rail-group[aria-label=\"Outputs\"]", count: 1 },
      { selector: ".right-rail .rail-group[aria-label=\"Subagents\"]", count: 1 },
      { selector: ".message.user", count: 1 },
      { selector: ".message.assistant", count: 1 },
      { selector: ".sidebar-footer > button", count: 2 },
      { selector: ".composer .voice-primary", count: 1 },
    ]));
    expect(chatRun!.required_geometry).toEqual(expect.arrayContaining([
      { selector: "#shell-pinned-tasks.shell-task-group-label", height: 18 },
      { selector: "#shell-recent-tasks.shell-task-group-label", height: 18 },
      {
        selector: ".shell-task-group[aria-labelledby=\"shell-pinned-tasks\"] .session-main",
        height: 31,
      },
      {
        selector: ".shell-task-group[aria-labelledby=\"shell-recent-tasks\"] .session-row:not(.active) .session-main",
        height: 31,
      },
      { selector: ".transcript-tool-summary", height: 24 },
      { selector: ".transcript-navigation", width: 63, height: 34 },
    ]));
    expect(chatRun!.required_computed_styles).toEqual(expect.arrayContaining([
      { selector: ".right-rail", property: "background-color", value: "rgba(0, 0, 0, 0)" },
      { selector: ".chat-rail-glass", property: "border-top-width", value: "0px" },
      { selector: ".chat-rail-glass", property: "border-right-width", value: "0px" },
      { selector: ".chat-rail-glass", property: "border-bottom-width", value: "0px" },
      { selector: ".chat-rail-glass", property: "border-left-width", value: "0px" },
      { selector: ".chat-rail-glass", property: "backdrop-filter", value: "blur(22px) saturate(1.25)" },
      { selector: ".transcript-navigation", property: "border-top-width", value: "0px" },
      { selector: ".transcript-navigation", property: "backdrop-filter", value: "blur(18px) saturate(1.25)" },
      { selector: ".sidebar.shell-parity", property: "border-right-width", value: "0px" },
      { selector: ".sidebar.shell-parity", property: "backdrop-filter", value: "blur(22px) saturate(1.05)" },
      { selector: ".composer-voice-controller", property: "display", value: "none" },
    ]));
    expect(chatRun!.required_presence_selectors)
      .toContain(".composer-voice-controller[hidden]");
    expect(chatRun!.required_absence_selectors)
      .toContain(".composer-voice-controller:not([hidden])");
    expect(chatRun!.required_exact_text).toContainEqual({
      selector: ".transcript-tool-summary .transcript-tool-copy",
      text: "Queried data",
    });
    expect(chatRun!.required_absence_selectors).toContain(".transcript-tool-disclosure[open]");
    expect(chatRun!.required_absent_text).toEqual(expect.arrayContaining([
      "script run by",
      "depth 1",
    ]));
  });

  it("fails the additive desktop-chat state closed on the Codex direction contract", () => {
    const direction = manifest.states.find((state) => state.id === "chat-direction") as
      | DirectionState
      | undefined;
    const newChat = manifest.states.find((state) => state.id === "new-chat");

    expect(direction).toBeDefined();
    expect(direction!.hash).toBe("#/chat/direction-thread");
    expect(direction!.required_request_prefixes).toContain(
      "/v1/conversations/direction-thread",
    );
    expect(direction!.direction_records).toEqual([
      "DIR-0008", "DIR-0009", "DIR-0010", "DIR-0011", "DIR-0012", "DIR-0015", "DIR-0016", "DIR-0017", "DIR-0018",
    ]);
    expect(direction!.reference_digest_manifest).toBe(
      "docs/design/evidence/2026-08-11-chat-ui-direction/references.sha256",
    );
    expect(direction!.target_reference_paths).toHaveLength(3);
    expect(direction!.negative_reference_paths).toHaveLength(3);
    expect(direction!.required_visible_selectors).toEqual(expect.arrayContaining([
      ".session-row.active .shell-recent-meta",
      ".session-row.active .session-actions",
      "#shell-pinned-tasks.shell-task-group-label",
      "#shell-recent-tasks.shell-task-group-label",
      ".transcript-navigation[aria-label=\"Transcript navigation\"]",
    ]));
    expect(direction!.required_presence_selectors).toEqual(expect.arrayContaining([
      ".right-rail .rail-group[aria-label=\"Background processes\"]",
      ".right-rail .rail-group[aria-label=\"Computer Use\"]",
      ".right-rail .rail-group[aria-label=\"Sources\"]",
      ".right-rail .rail-agent-stack [data-familiar-body=\"kepler\"]",
      ".right-rail .rail-agent-stack [data-familiar-body=\"pioneer\"]",
      ".right-rail .rail-agent-stack [data-familiar-body=\"voyager\"]",
      ".transcript-tool-summary",
      ".transcript-subagent-chip",
    ]));
    expect(direction!.required_absence_selectors).toEqual(expect.arrayContaining([
      ".side-status",
      ".conversation-search",
      ".side-recents-label",
      ".side-workspace",
      ".right-rail [aria-label=\"Conversation title\"]",
      ...unboundWorkspacePanelSelectors,
    ]));
    expect(direction!.required_text).toContain(
      "Used Figma integration, read files, edited files, ran commands",
    );
    expect(direction!.required_text).toContain("3 done");
    expect(direction!.required_geometry).toEqual(expect.arrayContaining([
      { selector: "#shell-pinned-tasks.shell-task-group-label", height: 18 },
      { selector: "#shell-recent-tasks.shell-task-group-label", height: 18 },
      { selector: ".session-row.active .session-main", height: 44 },
      {
        selector: ".shell-task-group[aria-labelledby=\"shell-recent-tasks\"] .session-row:not(.active) .session-main",
        height: 31,
      },
      { selector: ".transcript-tool-summary", height: 24 },
      { selector: ".transcript-navigation", width: 63, height: 34 },
      { selector: ".right-rail .chat-rail-glass", width: 302, y: 16 },
    ]));
    expect(direction!.required_visible_counts).toEqual(expect.arrayContaining([
      { selector: ".shell-task-group-label", count: 2 },
      { selector: ".transcript-navigation", count: 1 },
      { selector: ".transcript-navigation > button", count: 2 },
      { selector: ".transcript-tool-summary", count: 2 },
      { selector: ".right-rail .rail-group[aria-label=\"Outputs\"]", count: 1 },
      { selector: ".right-rail .rail-group[aria-label=\"Subagents\"]", count: 1 },
      { selector: ".right-rail .rail-group[aria-label=\"Background processes\"]", count: 1 },
      { selector: ".right-rail .rail-group[aria-label=\"Computer Use\"]", count: 1 },
      { selector: ".right-rail .rail-group[aria-label=\"Sources\"]", count: 1 },
      { selector: ".message.user", count: 2 },
      { selector: ".message.assistant", count: 2 },
      { selector: ".sidebar-footer > button", count: 2 },
      { selector: ".composer .voice-primary", count: 1 },
    ]));
    expect(direction!.required_computed_styles).toEqual(expect.arrayContaining([
      { selector: ".right-rail", property: "background-color", value: "rgba(0, 0, 0, 0)" },
      { selector: ".chat-rail-glass", property: "border-top-width", value: "0px" },
      { selector: ".chat-rail-glass", property: "border-right-width", value: "0px" },
      { selector: ".chat-rail-glass", property: "border-bottom-width", value: "0px" },
      { selector: ".chat-rail-glass", property: "border-left-width", value: "0px" },
      { selector: ".chat-rail-glass", property: "backdrop-filter", value: "blur(22px) saturate(1.25)" },
      { selector: ".transcript-navigation", property: "border-top-width", value: "0px" },
      { selector: ".transcript-navigation", property: "backdrop-filter", value: "blur(18px) saturate(1.25)" },
      { selector: ".sidebar.shell-parity", property: "border-right-width", value: "0px" },
      { selector: ".sidebar.shell-parity", property: "backdrop-filter", value: "blur(22px) saturate(1.05)" },
      { selector: ".composer-voice-controller", property: "display", value: "none" },
    ]));
    expect(direction!.required_presence_selectors)
      .toContain(".composer-voice-controller[hidden]");
    expect(direction!.required_absence_selectors)
      .toContain(".composer-voice-controller:not([hidden])");
    expect(direction!.required_absence_selectors).toContain(".transcript-tool-disclosure[open]");
    expect(direction!.required_absent_text).toEqual(expect.arrayContaining([
      "Governed by Boltrig",
      "Conversation settings",
      "Everything responding",
      "acme · production",
      "script run by",
      "depth 1",
    ]));
    expect(newChat?.known_contract_bound_deviations.join(" "))
      .not.toContain("readiness fixture is deliberately degraded");
  });

  it("re-evaluates readiness when the live viewport changes", async () => {
    const source = await import("node:fs/promises").then(({ readFile }) => readFile(
      new URL("./parity.tsx", import.meta.url),
      "utf8",
    ));
    expect(source).toContain('window.addEventListener("resize", evaluateVisualState)');
    expect(source).toContain("window.innerWidth !== manifest.viewport.width");
    expect(source).toContain("window.innerHeight !== manifest.viewport.height");
    expect(source).toContain("window.location.hash !== visualState.hash");
  });

  it("publishes readiness only after two stable painted frames", async () => {
    const source = await import("node:fs/promises").then(({ readFile }) => readFile(
      new URL("./parity.tsx", import.meta.url),
      "utf8",
    ));
    expect(source).toContain('document.fonts.status !== "loaded"');
    expect(source).toContain("visualStableFrames < 2");
    expect(source).toContain("visualContractFingerprint(visualState)");
    expect(source).toContain("__boltrigVisualCaptureContract");
    expect(source).toContain('schema: "boltrig-worker-visual-capture-contract.v1"');
    expect(source).toContain("missingRequestPrefixes: [...latestMissingRequestPrefixes]");
  });

  it("keeps current capture atomic, source-bound and review-neutral", async () => {
    const source = await import("node:fs/promises").then(({ readFile }) => readFile(
      new URL("./capture-current.mjs", import.meta.url),
      "utf8",
    ));
    expect(source).toContain('status: "captured_unreviewed"');
    expect(source).toContain('visualVerdict: "not_assessed"');
    expect(source).toContain("vdsReviewsUpdated: false");
    expect(source).toContain("sourceDigestAfter !== sourceDigestBefore");
    expect(source).toContain("await replaceDirectory(stagingRoot, finalRoot)");
    expect(source).toContain("Evidence capture is all-or-nothing");
    expect(source).toContain("Durable evidence cannot reuse an existing server");
    expect(source).toContain('options.mode !== "smoke" && options.reuseServer');
    expect(source).toContain("state.current_output");
    expect(source).not.toContain("capture-manifest.json\", repoRoot");
  });

  it("keeps additive capture separate, source-bound and review-neutral", async () => {
    const source = await import("node:fs/promises").then(({ readFile }) => readFile(
      new URL("./capture-current.mjs", import.meta.url),
      "utf8",
    ));
    expect(source).toContain('options.mode === "additive-evidence"');
    expect(source).toContain("manifest.additive_state_ids");
    expect(source).toContain("manifest.additive_capture_root");
    expect(source).toContain("Additive evidence capture is all-or-nothing");
    expect(source).toContain("boltrig-console-additive-current-capture-manifest.v1");
    expect(source).toContain('{ captureSet: "additive" }');
    expect(source).toContain('visualVerdict: "not_assessed"');
    expect(source).toContain("vdsReviewsUpdated: false");
  });

  it("keeps current comparison source-bound, atomic and review-neutral", async () => {
    const source = await import("node:fs/promises").then(({ readFile }) => readFile(
      new URL("./compare-current.py", import.meta.url),
      "utf8",
    ));
    expect(source).toContain('"status": "measured_unreviewed"');
    expect(source).toContain('"visualVerdict": "not_assessed"');
    expect(source).toContain('"vdsReviewsUpdated": False');
    expect(source).toContain("current source digest");
    expect(source).toContain("promote_comparison(stage, current_root)");
    expect(source).toContain('destination_diff = current_root / "diff"');
    expect(source).toContain('destination_metrics = current_root / "metrics.json"');
    expect(source).not.toContain('ROOT / "shipped"');
    expect(source).not.toContain('ROOT / "diff"');
  });

  it("requires landmarks and exact-count collections to be fully visible through clipping ancestors", async () => {
    const source = await import("node:fs/promises").then(({ readFile }) => readFile(
      new URL("./parity.tsx", import.meta.url),
      "utf8",
    ));
    expect(source).toContain("state.required_visible_counts ?? []");
    expect(source).toContain("elements.some((element) => !isVisiblyRendered(element))");
    expect(source).toContain("let left = Math.max(0, rect.left)");
    expect(source).toContain("let right = Math.min(window.innerWidth, rect.right)");
    expect(source).toContain("for (let ancestor = element.parentElement; ancestor; ancestor = ancestor.parentElement)");
    expect(source).toContain("/(auto|hidden|clip|scroll)/.test(ancestorStyle.overflowX)");
    expect(source).toContain("/(auto|hidden|clip|scroll)/.test(ancestorStyle.overflowY)");
    expect(source).toContain("right >= rect.right - 1");
    expect(source).toContain("bottom >= rect.bottom - 1");
  });

  it("models persisted assistant receipts without synthetic stream envelopes", async () => {
    const source = await import("node:fs/promises").then(({ readFile }) => readFile(
      new URL("./parity.tsx", import.meta.url),
      "utf8",
    ));
    expect(source).not.toContain('type: "message_start"');
    expect(source).not.toContain('type: "message_end"');
    expect(source).toContain('type: "text_delta"');
    expect(source).toContain('run_id: "run-renewal-review"');
  });

  it("keeps shell, transcript and inspector landmarks migration-compatible", async () => {
    const paritySource = await readFile(new URL("./parity.tsx", import.meta.url), "utf8");
    const inspectorSource = await readFile(new URL(
      "../../src/components/chat/TaskInspector.tsx",
      import.meta.url,
    ), "utf8");

    expect(paritySource).toContain('JSON.stringify(["vendor-invoice-triage"])');
    expect(paritySource).toContain('document.querySelector("#shell-pinned-tasks")');
    expect(paritySource).toContain('document.querySelector("#shell-recent-tasks")');
    expect(paritySource).toContain(
      'document.querySelector(\'.transcript-navigation[aria-label="Transcript navigation"]\')',
    );

    // TaskInspector carries these semantic bridge classes so the visual
    // contract can survive the legacy RightRail -> TaskInspector mount swap
    // without accepting a selector-free frame in between.
    expect(inspectorSource).toContain('"task-inspector right-rail"');
    expect(inspectorSource).toContain('className="task-inspector__surface rail-card chat-rail-glass"');
    expect(inspectorSource).toContain('className="task-inspector__group rail-group"');
    expect(inspectorSource).toContain('className="task-inspector__group-header rail-group-head"');
    expect(inspectorSource).toContain('className="task-inspector__group-body rail-body"');
    expect(inspectorSource).toContain('task-inspector__row rail-row');
    expect(inspectorSource).toContain('className="task-inspector__agent-stack rail-agent-stack"');
    expect(inspectorSource).toContain('data-integration="figma"');

    for (const id of ["chat-run", "chat-direction"] as const) {
      const state = manifest.states.find((candidate) => candidate.id === id) as
        | ContractState
        | undefined;
      expect(state).toBeDefined();
      expect(state!.required_geometry.some(({ selector }) => (
        selector === ".side-recents-label"
      ))).toBe(false);
      expect(state!.required_presence_selectors).toEqual(expect.arrayContaining([
        ".right-rail .chat-rail-glass",
        ".right-rail .rail-group[aria-label=\"Outputs\"]",
        ".right-rail .rail-group[aria-label=\"Subagents\"]",
      ]));
      expect(state!.required_absence_selectors).toEqual(expect.arrayContaining([
        ".conversation-search",
        ".side-recents-label",
        ".side-workspace",
        ".right-rail [aria-label=\"Conversation title\"]",
        ".right-rail [aria-label=\"Conversation\"]",
      ]));
    }
  });

  it("fails the Call fixture closed on its deterministic recovered-call notice", async () => {
    const call = manifest.states.find((state) => state.id === "call") as
      | ContractState
      | undefined;
    expect(call).toBeDefined();
    expect(call!.direction_records).toEqual(["DIR-0005", "DIR-0010", "DIR-0015", "DIR-0016"]);
    expect(call!.required_presence_selectors).toEqual(expect.arrayContaining([
      ".voice-call-title",
      ".voice-call-leave",
      ".voice-call-notice",
      ".voice-call-participants",
      ".voice-call-participant",
      ".voice-call-controls",
    ]));
    expect(call!.required_visible_selectors).toEqual(expect.arrayContaining([
      ".voice-call-title",
      ".voice-call-leave",
      ".voice-call-notice",
      ".voice-call-participants",
      ".voice-call-participant",
      ".voice-call-controls",
      '.voice-call-controls button[aria-pressed="false"]',
      '.voice-call-primary-familiar [data-renderer="webgl2"], .voice-call-primary-familiar [data-renderer="badge"]',
    ]));
    expect(call!.required_geometry).toEqual(expect.arrayContaining([
      {
        selector: ".voice-call-notice",
        x: 1180,
        y: 649,
        width: 236,
        tolerance: 1.5,
      },
      { selector: ".voice-call-primary-familiar", width: 150, height: 150 },
      {
        selector: ".voice-call-primary-familiar .familiar-stage",
        width: 150,
        height: 150,
      },
    ]));
    expect(call!.required_computed_styles).toEqual(expect.arrayContaining([
      {
        selector: ".voice-call-primary-familiar .familiar-stage-canvas",
        property: "position",
        value: "absolute",
      },
      {
        selector: ".voice-call-primary-familiar .familiar-stage-canvas",
        property: "width",
        value: "184px",
      },
      {
        selector: ".voice-call-primary-familiar .familiar-stage-canvas",
        property: "height",
        value: "184px",
      },
    ]));
    expect(call!.required_text).toEqual(expect.arrayContaining([
      "Renewal outreach · you and the chief of staff",
      "Leave",
      "A voice call from this conversation can be resumed.",
      "Mute",
    ]));
    expect(call!.required_exact_text).toEqual(expect.arrayContaining([
      {
        selector: ".session-row.active .session-title > span:first-child",
        text: "Renewal outreach",
      },
      {
        selector: ".voice-call-title",
        text: "Renewal outreach · you and the chief of staff",
      },
      { selector: ".voice-call-leave", text: "Leave" },
      {
        selector: '.voice-call-controls button[aria-pressed="false"]',
        text: "Mute",
      },
    ]));
    expect(call!.settled_when).toContain("visibly pinned recovery notice");

    const source = await import("node:fs/promises").then(({ readFile }) => readFile(
      new URL("./parity.tsx", import.meta.url),
      "utf8",
    ));
    expect(source).toContain('if (visualState.id === "call")');
    expect(source).toContain(
      'document.documentElement.dataset.visualPinRecoveredCallNotice = "true"',
    );
    expect(source).toContain('document.querySelector(".voice-call-notice")');
    expect(source).toContain("satisfies ConversationResponse");
    expect(source).not.toContain("conversation: { id: \"voice-thread\"");
  });

  it("keeps the Settings Look card on the three-row Figma geometry", () => {
    const settings = manifest.states.find((state) => state.id === "settings-you") as
      | ContractState
      | undefined;
    expect(settings).toBeDefined();
    expect(settings!.direction_records).toEqual(["DIR-0007", "DIR-0015"]);
    expect(settings!.required_absence_selectors).toContain(
      '.settings-you-pane [aria-label="Companion"]',
    );
    expect(settings!.required_absent_text).toContain("Companion");
    expect(settings!.required_text).toEqual(expect.arrayContaining([
      "Theme",
      "Density",
      "Text size",
      "3 more, for when you need them",
      "Reaching you",
    ]));
    expect(settings!.required_geometry).toEqual(expect.arrayContaining([
      {
        selector: ".settings-you-pane > .settings-group:nth-of-type(2) > .console-table",
        x: 523,
        y: 168,
        width: 656,
        height: 208,
        tolerance: 1.5,
      },
      {
        selector: ".settings-you-pane > .settings-group:nth-of-type(3) > .console-section-title",
        x: 523,
        y: 404,
        width: 656,
        height: 16,
        tolerance: 1.5,
      },
    ]));
  });

  it("fails Agents closed on the framed fleet canvas geometry", () => {
    const agents = manifest.states.find((state) => state.id === "agents") as
      | ContractState
      | undefined;
    expect(agents).toBeDefined();
    expect(agents!.direction_records).toEqual(["DIR-0003", "DIR-0010", "DIR-0015", "DIR-0016"]);
    expect(agents!.required_visible_selectors).toEqual(expect.arrayContaining([
      ".agents-fleet-topbar .console-seg",
      ".agents-fleet-topbar .console-primary",
      ".fleet-authority-key",
      ".fleet-canvas",
    ]));
    expect(agents!.required_geometry).toEqual(expect.arrayContaining([
      { selector: ".agents-fleet-topbar", x: 266, y: 0, width: 1174, height: 48 },
      { selector: ".fleet-summary", x: 284, y: 62, width: 1138, height: 34 },
      { selector: ".fleet-authority-key", x: 284, y: 96, width: 1138, height: 28 },
      { selector: ".fleet-canvas", x: 284, y: 136, width: 1138, height: 746 },
    ]));
  });

  it("binds the additive direction to a durable 1440 by 900 shipped capture", async () => {
    const direction = manifest.states.find((state) => state.id === "chat-direction") as
      | DirectionState
      | undefined;
    expect(direction).toBeDefined();
    expect(direction!.shipped_digest_manifest).toBe(
      "docs/design/evidence/2026-08-11-chat-ui-direction/shipped.sha256",
    );

    const repoRoot = new URL("../../../../", import.meta.url);
    const capture = await readFile(new URL(direction!.output, repoRoot));
    const digestManifest = await readFile(
      new URL(direction!.shipped_digest_manifest, repoRoot),
      "utf8",
    );
    const digest = createHash("sha256").update(capture).digest("hex");

    expect([...capture.subarray(0, 8)]).toEqual([137, 80, 78, 71, 13, 10, 26, 10]);
    expect(capture.readUInt32BE(16)).toBe(manifest.viewport.width);
    expect(capture.readUInt32BE(20)).toBe(manifest.viewport.height);
    expect(digestManifest.trim()).toBe(`${digest}  shipped/chat-direction.png`);
  });

  it("binds current additive evidence to its exact source and review-neutral receipt", async () => {
    const direction = manifest.states.find((state) => state.id === "chat-direction") as
      | DirectionState
      | undefined;
    expect(direction).toBeDefined();

    const repoRoot = new URL("../../../../", import.meta.url);
    const receipt = JSON.parse(await readFile(new URL(
      `${manifest.additive_capture_root}/capture-manifest.json`,
      repoRoot,
    ), "utf8")) as {
      schema: string;
      captureSet: string;
      status: string;
      visualVerdict: string;
      vdsReviewsUpdated: boolean;
      viewport: { width: number; height: number; deviceScaleFactor: number };
      sourceBinding: {
        scope: string[];
        digestBeforeCapture: string;
        digestAfterCapture: string;
        sourceUnchangedDuringCapture: boolean;
      };
      states: Array<{
        state: string;
        output: string;
        sha256: string;
        width: number;
        height: number;
        captureContract: {
          ready: boolean;
          contractMisses: string[];
          fixtureMisses: string[];
        };
      }>;
    };
    expect(receipt.schema).toBe("boltrig-console-additive-current-capture-manifest.v1");
    expect(receipt.captureSet).toBe("additive");
    expect(receipt.status).toBe("captured_unreviewed");
    expect(receipt.visualVerdict).toBe("not_assessed");
    expect(receipt.vdsReviewsUpdated).toBe(false);
    expect(receipt.viewport).toEqual({ width: 1440, height: 900, deviceScaleFactor: 1 });
    expect(receipt.sourceBinding.scope).toEqual(sourceScope);
    expect(receipt.sourceBinding.sourceUnchangedDuringCapture).toBe(true);
    expect(receipt.sourceBinding.digestBeforeCapture)
      .toBe(receipt.sourceBinding.digestAfterCapture);
    expect(receipt.sourceBinding.digestAfterCapture).toBe(await sourceTreeDigest());
    expect(receipt.states).toHaveLength(1);

    const row = receipt.states[0]!;
    expect(row.state).toBe("chat-direction");
    expect(row.output).toBe(direction!.current_output);
    expect(row.width).toBe(1440);
    expect(row.height).toBe(900);
    expect(row.captureContract.ready).toBe(true);
    expect(row.captureContract.contractMisses).toEqual([]);
    expect(row.captureContract.fixtureMisses).toEqual([]);

    const capture = await readFile(new URL(direction!.current_output, repoRoot));
    const digest = createHash("sha256").update(capture).digest("hex");
    const digestManifest = await readFile(new URL(
      `${manifest.additive_capture_root}/shipped.sha256`,
      repoRoot,
    ), "utf8");
    expect([...capture.subarray(0, 8)]).toEqual([137, 80, 78, 71, 13, 10, 26, 10]);
    expect(capture.readUInt32BE(16)).toBe(1440);
    expect(capture.readUInt32BE(20)).toBe(900);
    expect(row.sha256).toBe(digest);
    expect(digestManifest.trim()).toBe(`${digest}  shipped/chat-direction.png`);
  });

  it("keeps the existing console captures explicitly historical and stale", async () => {
    const repoRoot = new URL("../../../../", import.meta.url);
    const captureManifest = JSON.parse(await readFile(
      new URL(
        "docs/design/evidence/2026-08-11-console-parity/capture-manifest.json",
        repoRoot,
      ),
      "utf8",
    )) as {
      captureStatus: string;
      currentSourceBinding: { status: string; invalidatedAt: string; reason: string };
    };
    const readme = await readFile(new URL(
      "docs/design/evidence/2026-08-11-console-parity/README.md",
      repoRoot,
    ), "utf8");

    expect(captureManifest.captureStatus).toBe("complete");
    expect(captureManifest.currentSourceBinding.status).toBe("stale");
    expect(captureManifest.currentSourceBinding.invalidatedAt).toMatch(/Z$/);
    expect(captureManifest.currentSourceBinding.reason).toContain(
      "must not be presented as evidence of the current working tree",
    );
    expect(readme).toContain("retains the historical 06:41–06:42 UTC Worker comparison");
    expect(readme).toContain("Fresh source-bound evidence for the");
    expect(readme).toContain("root-level 06:41–06:42 UTC captures remain historical");
    expect(readme).not.toContain("This directory binds the current Worker implementation");
  });
});
