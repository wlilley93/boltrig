import { useEffect, useState } from "react";

import { navigate } from "../routes";
import { useRouteSelection } from "../useRouteSelection";
import { CreateMethodIcon, GovernedCreateModal } from "./GovernedCreateModal";
import { AdaptersBuild } from "./build/AdaptersBuild";
import { AgentTabsStrip } from "./build/AgentTabsStrip";
import { ActionsTable } from "./build/ActionsTable";
import { CapabilityRunner } from "./build/CapabilityRunner";
import { ModelEndpointsBuild } from "./build/ModelEndpointsBuild";
import { RecentlyChanged } from "./build/RecentlyChanged";
import { RegistryBuild } from "./build/RegistryBuild";
import { SkillsBuild } from "./build/SkillsBuild";
import { SkillsTable } from "./build/SkillsTable";
import { SpawnRulesBuild } from "./build/SpawnRulesBuild";

import "./build/build.css";
import "./build/BuildParity.css";

// The decided target's Build surface: Skills and Actions are read-first tables
// under the shared Agents | Skills | Actions | Knowledge strip, with authoring
// kept behind row-open (and behind the remaining governed tabs, which the
// design gives no home but which must stay reachable - losing them would lose
// governed authoring). The tab is carried in the hash (#/build/<tab>) so the
// strip on other surfaces can deep-link here.

type BuildTab =
  | "actions"
  | "skills"
  | "run"
  | "registry"
  | "adapters"
  | "models"
  | "routing";

// The disclosed routes hold the advanced authoring surfaces only. Skills and
// Actions are reached from AgentTabsStrip — listing them twice gave the screen
// two highlighted "Skills" buttons that did the same thing.
const ADVANCED_TABS: ReadonlyArray<readonly [BuildTab, string]> = [
  ["run", "Run"],
  ["registry", "Registry"],
  ["adapters", "Adapters"],
  ["models", "Models"],
  ["routing", "Routing"],
];

const TAB_COPY: Record<BuildTab, { title: string; lead: string }> = {
  actions: {
    title: "Actions",
    lead: "Everything Boltrig knows how to do, and what each action may touch. "
      + "Adding a plugin adds words here — it never adds permission.",
  },
  skills: {
    title: "Skills",
    lead: "How to do things, written down and versioned. An agent can only be "
      + "spawned with the skills its profile supports.",
  },
  run: {
    title: "Run a capability",
    lead: "Execute one governed verb with full receipts. High-consequence calls "
      + "still pause for approval.",
  },
  registry: {
    title: "Registry",
    lead: "Author nouns, verbs and bindings as data. Activation and "
      + "high-consequence changes still pass through the kernel.",
  },
  adapters: {
    title: "Adapters",
    lead: "Generated adapters stay inert until reviewed and activated.",
  },
  models: {
    title: "Models",
    lead: "Model endpoints the kernel may route completions through.",
  },
  routing: {
    title: "Routing",
    lead: "Spawn rules that decide which profile picks up new work.",
  },
};

function asBuildTab(selection: string | null): BuildTab {
  if (
    selection === "actions"
    || selection === "skills"
    || (selection && ADVANCED_TABS.some(([id]) => id === selection))
  ) {
    return selection as BuildTab;
  }
  return "actions";
}

export function BuildView() {
  const [selection, setSelection] = useRouteSelection("build");
  const tab = asBuildTab(selection);
  const advancedTab = ADVANCED_TABS.some(([id]) => id === tab);
  const [advancedOpen, setAdvancedOpen] = useState(advancedTab);
  // Row-open drops into the full governed authoring surface for that record;
  // null means the read-first table, "" means a fresh record.
  const [openSkillId, setOpenSkillId] = useState<string | null>(null);
  const [openVerbId, setOpenVerbId] = useState<string | null>(null);
  const [creating, setCreating] = useState<"actions" | "skills" | null>(null);

  useEffect(() => {
    setOpenSkillId(null);
    setOpenVerbId(null);
    setCreating(null);
    if (advancedTab) setAdvancedOpen(true);
  }, [advancedTab, tab]);

  const copy = TAB_COPY[tab];
  const advancedDisclosure = (
    <div className="build-advanced-disclosure">
      <button
        aria-controls="build-advanced-sections"
        aria-expanded={advancedOpen}
        className="build-advanced-toggle"
        onClick={() => setAdvancedOpen((open) => !open)}
        type="button"
      >
        <svg aria-hidden fill="none" height="12" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" viewBox="0 0 24 24" width="12">
          <polyline points="9 18 15 12 9 6" />
        </svg>
        <span>Advanced authoring</span>
        {advancedTab && <span className="build-advanced-current">{copy.title}</span>}
      </button>
      {advancedOpen && (
        <nav aria-label="Advanced build sections" className="console-seg build-advanced-seg" id="build-advanced-sections">
          {ADVANCED_TABS.map(([id, label]) => (
            <button
              aria-current={tab === id ? "page" : undefined}
              data-active={tab === id ? "true" : undefined}
              key={id}
              onClick={() => setSelection(id)}
              type="button"
            >
              {label}
            </button>
          ))}
        </nav>
      )}
    </div>
  );
  return (
    <div className="page">
      <div className="console-page">
        <AgentTabsStrip active={tab === "skills" || tab === "actions" ? tab : null} />
        <div className="console-head">
          <div>
            <h1>{copy.title}</h1>
            <p>{copy.lead}</p>
          </div>
          {tab === "actions" && (
            <button className="console-primary" onClick={() => setCreating("actions")} type="button">
              <PlusIcon />
              <span>Add a plugin</span>
            </button>
          )}
          {tab === "skills" && openSkillId === null && (
            <button className="console-primary" onClick={() => setCreating("skills")} type="button">
              <PlusIcon />
              <span>Record a skill</span>
            </button>
          )}
        </div>
        {advancedTab && advancedDisclosure}
        {tab === "actions" && (
          openVerbId === null
            ? <ActionsTable onOpen={setOpenVerbId} />
            : (
              <>
                <div className="build-back-row">
                  <button className="build-back" onClick={() => setOpenVerbId(null)} type="button">
                    ← Back to the actions list
                  </button>
                </div>
                <RegistryBuild initialVerbId={openVerbId || null} />
              </>
            )
        )}
        {tab === "skills" && (
          openSkillId === null
            ? <SkillsTable onOpen={setOpenSkillId} />
            : (
              <>
                <div className="build-back-row">
                  <button className="build-back" onClick={() => setOpenSkillId(null)} type="button">
                    ← Back to the skills list
                  </button>
                </div>
                <SkillsBuild initialSkillId={openSkillId || null} />
              </>
            )
        )}
        {tab === "run" && <CapabilityRunner />}
        {tab === "registry" && <RegistryBuild />}
        {tab === "adapters" && <AdaptersBuild />}
        {tab === "models" && <ModelEndpointsBuild />}
        {tab === "routing" && <SpawnRulesBuild />}
        <RecentlyChanged />
        {!advancedTab && advancedDisclosure}
      </div>
      {creating === "skills" && (
        <GovernedCreateModal
          lead="A skill is how to do something. Show boltrig once and every agent inherits it."
          methods={[
            {
              available: false,
              description: "The clearest teacher is a reply you rewrote. boltrig reads the difference and keeps the lesson.",
              icon: <CreateMethodIcon kind="copy" />,
              tag: "Recommended",
              title: "From work you corrected",
              unavailableReason: "The current API does not expose correction-derived skill learning.",
            },
            {
              available: true,
              description: "State the rule in your own words. Best for things you would tell a new colleague on day one.",
              icon: <CreateMethodIcon kind="describe" />,
              onSelect: () => {
                setCreating(null);
                setOpenSkillId("");
              },
              title: "Write it down",
            },
            {
              available: false,
              description: "Work through it once while boltrig watches, and it keeps the steps as know-how.",
              icon: <CreateMethodIcon kind="empty" />,
              title: "Record yourself doing it",
              unavailableReason: "The current API does not expose observed-work recording.",
            },
          ]}
          onClose={() => setCreating(null)}
          title="Record a skill"
        />
      )}
      {creating === "actions" && (
        <GovernedCreateModal
          lead="A plugin teaches boltrig new things it can do. It never hands out permission."
          methods={[
            {
              available: true,
              description: "Pick from the systems boltrig already knows how to talk to. You supply the key.",
              icon: <CreateMethodIcon kind="system" />,
              onSelect: () => {
                setCreating(null);
                navigate("integrations");
              },
              tag: "Recommended",
              title: "Choose a system",
            },
            {
              available: true,
              description: "For anything that speaks a standard boltrig understands. Its actions arrive checked like the rest.",
              icon: <CreateMethodIcon kind="address" />,
              onSelect: () => {
                setCreating(null);
                setSelection("adapters");
              },
              title: "Point at an address",
            },
            {
              available: true,
              description: "If a tool you already run offers its own actions, they appear here, gated the same way.",
              icon: <CreateMethodIcon kind="tools" />,
              onSelect: () => {
                setCreating(null);
                setSelection("adapters");
              },
              title: "Use another app's tools",
            },
          ]}
          onClose={() => setCreating(null)}
          title="Add a plugin"
        />
      )}
    </div>
  );
}

function PlusIcon() {
  return (
    <svg aria-hidden fill="none" height="14" stroke="currentColor" strokeLinecap="round" strokeWidth="2" viewBox="0 0 24 24" width="14">
      <line x1="12" x2="12" y1="5" y2="19" /><line x1="5" x2="19" y1="12" y2="12" />
    </svg>
  );
}
