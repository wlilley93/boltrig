import { navigate } from "../../routes";

import "./build.css";

// The decided target folds Agents, Skills, Actions and Knowledge under one
// segmented strip (design AGENT_TABS). The worker keeps them on their existing
// hash routes, so the strip is navigation, not state: Agents and Knowledge are
// routes of their own, and Skills / Actions are read-first tabs of the Build
// route reached as #/build/skills and #/build/actions.
const TABS = [
  ["agents", "Agents"],
  ["skills", "Skills"],
  ["actions", "Actions"],
  ["knowledge", "Knowledge"],
] as const;

export type AgentTabId = (typeof TABS)[number][0];

export function AgentTabsStrip({ active }: { active: AgentTabId | null }) {
  return (
    <nav aria-label="Agents, Skills, Actions and Knowledge" className="console-seg">
      {TABS.map(([id, label]) => (
        <button
          aria-current={active === id ? "page" : undefined}
          data-active={active === id ? "true" : undefined}
          key={id}
          onClick={() => {
            if (id === "agents") navigate("agents");
            else if (id === "knowledge") navigate("knowledge");
            else navigate("build", id);
          }}
          type="button"
        >
          {label}
        </button>
      ))}
    </nav>
  );
}
