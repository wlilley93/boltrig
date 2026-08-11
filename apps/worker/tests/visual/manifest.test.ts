import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";

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
  direction_records: string[];
  reference_digest_manifest: string;
  shipped_digest_manifest: string;
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

describe("console parity evidence manifest", () => {
  it("keeps the seven canonical states in order and appends additive evidence", () => {
    expect(manifest.schema).toBe("boltrig-worker-visual-states.v2");
    expect(manifest.viewport).toEqual({ width: 1440, height: 900 });
    expect(manifest.governed_state_ids).toEqual(canonicalStateIds);
    expect(manifest.additive_state_ids).toEqual(additiveStateIds);
    expect(manifest.current_capture_root).toBe(
      "docs/design/evidence/2026-08-11-console-parity/current",
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
    expect(palette!.direction_records).toEqual(["DIR-0006"]);
    expect(palette!.required_presence_selectors).toEqual(expect.arrayContaining([
      ".sidebar.shell-parity",
      ".conversation-search",
      ".right-rail .chat-rail-glass",
      ".command-palette[data-screen-label=\"Command palette\"]",
      ".command-search input[aria-label=\"Search Worker\"]",
      ".command-row.active",
    ]));
    expect(palette!.required_absence_selectors).toEqual(expect.arrayContaining([
      ".side-status",
      ".side-status-dot",
      ".message-author",
      ".subagent-fanout",
      ".right-rail [aria-label=\"Conversation title\"]",
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
    expect(palette!.required_geometry).toEqual(expect.arrayContaining([
      { selector: ".command-palette", x: 660, y: 135, width: 560, height: 335 },
      { selector: ".command-search", x: 661, y: 136, width: 558, height: 48 },
    ]));
    expect(palette!.required_exact_text).toEqual(expect.arrayContaining([
      { selector: ".command-row:nth-child(1) .command-row-label", text: "New chat" },
      { selector: ".command-row:nth-child(8) .command-row-label", text: "Keyboard shortcuts settings" },
    ]));
    expect(palette!.required_absent_text).toEqual(expect.arrayContaining([
      "Governed by Boltrig",
      "Conversation settings",
      "Everything responding",
      "This run",
    ]));
  });

  it("fails Plugins closed on its visible health, inventory and Figma geometry", () => {
    const plugins = manifest.states.find((state) => state.id === "plugins") as
      | ContractState
      | undefined;

    expect(plugins).toBeDefined();
    expect(plugins!.direction_records).toEqual(["DIR-0004"]);
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
      expect(state!.direction_records).toEqual(["DIR-0008", "DIR-0009"]);
      expect(state!.required_presence_selectors).toContain(".sidebar.shell-parity");
      expect(state!.required_presence_selectors).toContain(".conversation-search");
      expect(state!.required_absence_selectors).toEqual(expect.arrayContaining([
        ".side-status",
        ".message-author",
        ".subagent-fanout",
      ]));
      expect(state!.required_absent_text).toEqual(expect.arrayContaining([
        "Governed by Boltrig",
        "Conversation settings",
        "Everything responding",
      ]));
    }

    expect(newChat!.required_visible_selectors).toEqual(expect.arrayContaining([
      ".new-chat-transcript .welcome h1",
      ".new-chat-transcript .composer.new-context",
      ".new-chat-transcript button[aria-label=\"Model profile\"]",
      ".voice-intro",
    ]));
    expect(newChat!.required_geometry).toEqual(expect.arrayContaining([
      { selector: ".new-chat-transcript .welcome", x: 521, y: 250.5, width: 660, height: 338 },
      { selector: ".new-chat-transcript .composer.new-context", x: 521, y: 310.5, width: 660, height: 122 },
      { selector: ".new-chat-transcript .starters", x: 521, y: 454.5, width: 660, height: 134 },
      { selector: ".voice-intro", x: 521, y: 823, width: 660, height: 57 },
    ]));
    expect(chatRun!.required_visible_selectors).toEqual(expect.arrayContaining([
      ".session-row.active .session-actions",
      ".transcript-tool-summary",
      ".transcript-subagent-chip",
      ".right-rail .chat-rail-glass",
    ]));
    expect(chatRun!.required_geometry).toContainEqual({
      selector: ".right-rail .chat-rail-glass",
      width: 302,
      height: 153.5,
      y: 16,
    });
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
    expect(direction!.direction_records).toEqual(["DIR-0008", "DIR-0009"]);
    expect(direction!.reference_digest_manifest).toBe(
      "docs/design/evidence/2026-08-11-chat-ui-direction/references.sha256",
    );
    expect(direction!.target_reference_paths).toHaveLength(3);
    expect(direction!.negative_reference_paths).toHaveLength(3);
    expect(direction!.required_visible_selectors).toEqual(expect.arrayContaining([
      ".conversation-search",
      ".session-row.active .shell-recent-meta",
      ".session-row.active .session-actions",
    ]));
    expect(direction!.required_presence_selectors).toEqual(expect.arrayContaining([
      ".right-rail [aria-label=\"Background processes\"]",
      ".right-rail [aria-label=\"Computer Use\"]",
      ".right-rail [aria-label=\"Sources\"]",
      ".right-rail .rail-agent-stack [data-familiar-body=\"kepler\"]",
      ".right-rail .rail-agent-stack [data-familiar-body=\"pioneer\"]",
      ".right-rail .rail-agent-stack [data-familiar-body=\"voyager\"]",
      ".transcript-tool-summary",
      ".transcript-subagent-chip",
    ]));
    expect(direction!.required_absence_selectors).toEqual(expect.arrayContaining([
      ".side-status",
      ".right-rail [aria-label=\"Conversation title\"]",
    ]));
    expect(direction!.required_text).toContain(
      "Used Figma integration, read files, edited files, ran commands",
    );
    expect(direction!.required_text).toContain("3 done");
    expect(direction!.required_geometry).toEqual(expect.arrayContaining([
      { selector: ".conversation-search", width: 245, height: 31 },
      { selector: ".session-row.active .session-main", height: 44 },
      { selector: ".right-rail .chat-rail-glass", width: 302, height: 471, y: 16 },
    ]));
    expect(direction!.required_absent_text).toEqual(expect.arrayContaining([
      "Governed by Boltrig",
      "Conversation settings",
      "Everything responding",
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
    expect(source).toContain("state.current_output");
    expect(source).not.toContain("capture-manifest.json\", repoRoot");
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

  it("fails the Call fixture closed on its deterministic recovered-call notice", async () => {
    const call = manifest.states.find((state) => state.id === "call") as
      | ContractState
      | undefined;
    expect(call).toBeDefined();
    expect(call!.direction_records).toEqual(["DIR-0005"]);
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
    expect(settings!.direction_records).toEqual(["DIR-0007"]);
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
    expect(agents!.direction_records).toEqual(["DIR-0003"]);
    expect(agents!.required_visible_selectors).toEqual(expect.arrayContaining([
      ".agents-fleet-topbar .console-seg",
      ".agents-fleet-topbar .console-primary",
      ".fleet-authority-key",
      ".fleet-canvas",
    ]));
    expect(agents!.required_geometry).toEqual(expect.arrayContaining([
      { selector: ".agents-fleet-topbar", x: 262, y: 0, width: 1178, height: 48 },
      { selector: ".fleet-summary", x: 280, y: 62, width: 1142, height: 34 },
      { selector: ".fleet-authority-key", x: 280, y: 96, width: 1142, height: 28 },
      { selector: ".fleet-canvas", x: 280, y: 136, width: 1142, height: 746 },
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
    expect(readme).toContain("records the historical 06:41–06:42 UTC Worker comparison");
    expect(readme).toContain("It does not bind the current Worker source.");
    expect(readme).toContain("Do not use the existing shipped images, diffs or");
    expect(readme).not.toContain("This directory binds the current Worker implementation");
  });
});
