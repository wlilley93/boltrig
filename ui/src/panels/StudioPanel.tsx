// Round Three authoring hub. Four sub-studios behind internal sub-tabs (no
// router): Skills, Router authoring, Adapter Studio and Workflow Studio.
// Authoring requires a permitting role; the server is the real gate (403), but
// the panel also shows a notice for non-author identities so the surface is
// honest. Generated adapters / MCP servers land inert (activated: false) and a
// reviewer must activate them (SEC-22). test-spawn returns effective_grants so
// an author can see the child never escalates past their own grants (SEC-29).
//
// Each sub-studio owns its own local state and lives in ./studio/*, so this
// file is just the tab chrome and the author-role notice.

import { useState } from "react";

import { useIdentity } from "../identity";
import { PageIntro } from "./ux";
import { AdapterStudio } from "./studio/AdapterStudio";
import { RouterStudio } from "./studio/RouterStudio";
import { SkillsStudio } from "./studio/SkillsStudio";
import { WorkflowStudio } from "./studio/WorkflowStudio";

const AUTHOR_ROLES: ReadonlySet<string> = new Set([
  "org-admin",
  "department-head",
  "manager",
  "lead",
  "integrator",
]);

type StudioTab = "skills" | "router" | "adapters" | "workflows";

const STUDIO_TABS: ReadonlyArray<{ id: StudioTab; label: string }> = [
  { id: "skills", label: "Skills" },
  { id: "router", label: "Router authoring" },
  { id: "adapters", label: "Adapter Studio" },
  { id: "workflows", label: "Workflow Studio" },
];

export function StudioPanel() {
  const identity = useIdentity();
  const [sub, setSub] = useState<StudioTab>("skills");
  const isAuthor = AUTHOR_ROLES.has(identity.role);

  return (
    <section className="panel">
      <PageIntro
        title="Studio"
        lead="Where you compose what agents can do: skills, capability (nouns, verbs and what runs them), adapters, and workflows."
        how="Everything you build here is data, not code. Skills give agents instructions + permissions; Router wires a verb to an adapter or agent; Adapters turn an external service into governed verbs; Workflows chain verbs into a flow."
      />

      {!isAuthor && (
        <p className="notice warn">
          This identity (role: <code>{identity.role}</code>) is not an author
          role, so the server will reject writes here with 403. Authoring
          requires one of: org-admin, department-head, manager, lead,
          integrator.
        </p>
      )}

      <nav className="subtabs" aria-label="Studio sections">
        {STUDIO_TABS.map((t) => (
          <button
            key={t.id}
            className={`subtab ${sub === t.id ? "subtab--active" : ""}`}
            onClick={() => setSub(t.id)}
          >
            {t.label}
          </button>
        ))}
      </nav>

      {sub === "skills" && <SkillsStudio />}
      {sub === "router" && <RouterStudio />}
      {sub === "adapters" && <AdapterStudio />}
      {sub === "workflows" && <WorkflowStudio />}
    </section>
  );
}
