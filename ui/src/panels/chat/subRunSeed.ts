// Sub-run seeded conversation content (CHAT-DESIGN-BRIEF sec 11, lines 308-329).
// Pure data module. getSubAgentData(agentId) returns a realistic message + tool
// receipt set per agent so the sub-run sidebar has content when no live run
// stream is attached. Bolt and Head of Engineering are tier 1/2; the other four
// are tier-3 workers with descriptive role names per the brief.

export type SeededToolStatus = "ok" | "running" | "error" | "pending";

export interface SeededMessage {
  id: string;
  text: string;
  time: string;
}

export interface SeededTool {
  id: string;
  verb: string;
  status: SeededToolStatus;
  detail: string;
}

export interface SeededAgentData {
  messages: SeededMessage[];
  tools: SeededTool[];
}

// Agent ids covered by the brief (sec 11, lines 317-324). The first two match
// the ChatAgent ids in constants.ts; the rest are tier-3 workers that carry
// descriptive role names rather than formal department titles.
export const SUB_RUN_AGENT_IDS = [
  "bolt",
  "head-eng",
  "release-manager",
  "deps-checker",
  "changelog-writer",
  "notifier",
] as const;
export type SubRunAgentId = (typeof SUB_RUN_AGENT_IDS)[number];

// Bolt (Chief of Staff): delegation overview of the active release run.
function boltData(): SeededAgentData {
  return {
    messages: [
      {
        id: "bolt-m1",
        text: "Delegating the 2.14 release run. Engineering leads the build, the Release Manager cuts the tag, and the Changelog Writer drafts the notes.",
        time: "just now",
      },
    ],
    tools: [
      { id: "bolt-t1", verb: "delegate", status: "ok", detail: "Head of Engineering owns the build" },
      { id: "bolt-t2", verb: "assign", status: "ok", detail: "Release Manager owns the tag cut" },
    ],
  };
}

// Head of Engineering: coordination plus worker spawning for the run.
function headEngData(): SeededAgentData {
  return {
    messages: [
      {
        id: "eng-m1",
        text: "Coordinating the 2.14 build. I've spawned Deps Checker and Changelog Writer as workers and am gating the merge on their results.",
        time: "just now",
      },
    ],
    tools: [
      { id: "eng-t1", verb: "spawn worker", status: "ok", detail: "Deps Checker" },
      { id: "eng-t2", verb: "spawn worker", status: "running", detail: "Changelog Writer" },
    ],
  };
}

// Release Manager (tier-3): tag read, PR create, channel notify.
function releaseManagerData(): SeededAgentData {
  return {
    messages: [
      {
        id: "rm-m1",
        text: "Cutting release 2.14. I've read the existing tags, opened the release PR against main, and notified the release channel.",
        time: "just now",
      },
    ],
    tools: [
      { id: "rm-t1", verb: "git tag read", status: "ok", detail: "v2.14.0 not yet present" },
      { id: "rm-t2", verb: "pr create", status: "ok", detail: "PR #482 against main" },
      { id: "rm-t3", verb: "channel notify", status: "ok", detail: "#releases" },
    ],
  };
}

// Deps Checker (tier-3): manifest read, compatibility verify.
function depsCheckerData(): SeededAgentData {
  return {
    messages: [
      {
        id: "dc-m1",
        text: "Checking dependencies for 2.14. I've read the locked manifest and verified compatibility against the declared set; no conflicts found.",
        time: "just now",
      },
    ],
    tools: [
      { id: "dc-t1", verb: "manifest read", status: "ok", detail: "pnpm-lock.yaml" },
      { id: "dc-t2", verb: "compatibility verify", status: "ok", detail: "0 advisories, 0 breaks" },
    ],
  };
}

// Changelog Writer (tier-3): commit log read, changelog PR creation.
function changelogWriterData(): SeededAgentData {
  return {
    messages: [
      {
        id: "cw-m1",
        text: "Drafting the 2.14 changelog. I've read the commit log since the last tag and opened a PR against the docs repo with the rendered notes.",
        time: "just now",
      },
    ],
    tools: [
      { id: "cw-t1", verb: "commit log read", status: "ok", detail: "42 commits since v2.13.0" },
      { id: "cw-t2", verb: "changelog pr create", status: "ok", detail: "docs#91" },
    ],
  };
}

// Notifier (tier-3): pending / waiting state, blocked on upstream agents.
function notifierData(): SeededAgentData {
  return {
    messages: [
      {
        id: "nf-m1",
        text: "Holding in pending. I'm waiting on the Release Manager tag and the Changelog Writer PR before I post the announcement.",
        time: "just now",
      },
    ],
    tools: [
      { id: "nf-t1", verb: "status read", status: "pending", detail: "waiting on release-manager" },
      { id: "nf-t2", verb: "wait gate", status: "running", detail: "blocked: tag + changelog" },
    ],
  };
}

// Generic fallback for any agent id without bespoke seeded content (e.g. tier-2
// leads not enumerated in sec 11). Keeps the sidebar from rendering empty.
function defaultData(): SeededAgentData {
  return {
    messages: [
      {
        id: "default-m1",
        text: "Standing by. No live run stream is attached; a summary of this agent's last activity is shown here.",
        time: "just now",
      },
    ],
    tools: [],
  };
}

const REGISTRY: Record<string, () => SeededAgentData> = {
  bolt: boltData,
  "head-eng": headEngData,
  "release-manager": releaseManagerData,
  "deps-checker": depsCheckerData,
  "changelog-writer": changelogWriterData,
  notifier: notifierData,
};

/**
 * Returns the seeded sub-run conversation content for an agent. When a live run
 * stream is attached the caller renders that instead; this is the fallback.
 */
export function getSubAgentData(agentId: string): SeededAgentData {
  const build = REGISTRY[agentId];
  return build ? build() : defaultData();
}
