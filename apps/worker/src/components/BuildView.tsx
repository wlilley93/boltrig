import { useEffect, useState } from "react";

import { useRouteSelection } from "../useRouteSelection";
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

// The lower strip holds the authoring surfaces only. Skills and Actions are
// reached from the AgentTabsStrip above it — listing them twice gave the
// screen two highlighted "Skills" buttons that did the same thing.
const BUILD_TABS: ReadonlyArray<readonly [BuildTab, string]> = [
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
  if (selection && BUILD_TABS.some(([id]) => id === selection)) {
    return selection as BuildTab;
  }
  return "actions";
}

export function BuildView() {
  const [selection, setSelection] = useRouteSelection("build");
  const tab = asBuildTab(selection);
  // Row-open drops into the full governed authoring surface for that record;
  // null means the read-first table, "" means a fresh record.
  const [openSkillId, setOpenSkillId] = useState<string | null>(null);
  const [openVerbId, setOpenVerbId] = useState<string | null>(null);

  useEffect(() => {
    setOpenSkillId(null);
    setOpenVerbId(null);
  }, [tab]);

  const copy = TAB_COPY[tab];
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
            <a className="console-primary" href="#/integrations">
              <PlusIcon />
              <span>Add a plugin</span>
            </a>
          )}
          {tab === "skills" && openSkillId === null && (
            <button className="console-primary" onClick={() => setOpenSkillId("")} type="button">
              <PlusIcon />
              <span>Record a skill</span>
            </button>
          )}
        </div>
        <nav aria-label="Build sections" className="console-seg">
          {BUILD_TABS.map(([id, label]) => (
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
      </div>
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
