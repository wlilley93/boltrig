import { useEffect, useRef, useState } from "react";
import {
  BoltrigApiError,
  type AgentCapabilityAuthorInfo,
  type SkillSummary,
} from "@wlilley93/boltrig-web-sdk";

import { client } from "../../client";
import { Unavailable } from "../Shell";

import "./build.css";

// The read-first Skills table (design lines 851-875, tab "skills"). The list
// comes from client.skills(); the description sub-line only exists on the
// per-skill detail record so it is hydrated with a bounded fan-out and the row
// falls back to its grant summary while (or if) that detail is missing. The
// "Inherited by" column is a client-side join against the agent roster's
// supported_skills ceilings - the same patterns the spawn gate enforces. The
// design's provenance ("Work you approved") and "Used N x" columns have no
// data source anywhere, so they are omitted rather than invented.

type TableState = "loading" | "ready" | "denied" | "unavailable";

const DETAIL_FAN_OUT_CAP = 40;

function skillPatternMatches(pattern: string, skillId: string): boolean {
  if (pattern === "*" || pattern === skillId) return true;
  if (pattern.endsWith("*")) return skillId.startsWith(pattern.slice(0, -1));
  return false;
}

function inheritedBy(
  skillId: string,
  agents: AgentCapabilityAuthorInfo[] | null,
): string {
  if (agents === null) return "Roster unavailable";
  if (agents.length === 0) return "No agents visible";
  const count = agents.filter((agent) => (
    agent.supported_skills.some((pattern) => skillPatternMatches(pattern, skillId))
  )).length;
  if (count === 0) return "No agents";
  if (count === agents.length) return agents.length === 1 ? "The only agent" : `All ${count} agents`;
  return `${count} of ${agents.length} agents`;
}

export function SkillsTable({ onOpen }: { onOpen(skillId: string): void }) {
  const [skills, setSkills] = useState<SkillSummary[]>([]);
  const [state, setState] = useState<TableState>("loading");
  // null = the roster request failed, so the join is reported as unavailable
  // instead of rendering a zero that would read as "no agent inherits this".
  const [agents, setAgents] = useState<AgentCapabilityAuthorInfo[] | null>(null);
  const [descriptions, setDescriptions] = useState<Record<string, string>>({});
  const loaded = useRef(false);

  useEffect(() => {
    let cancelled = false;
    void client.skills()
      .then(async (result) => {
        if (cancelled) return;
        setSkills(result.skills);
        loaded.current = true;
        setState("ready");
        const sample = result.skills.slice(0, DETAIL_FAN_OUT_CAP);
        const details = await Promise.allSettled(
          sample.map((skill) => client.skill(skill.id)),
        );
        if (cancelled) return;
        const found: Record<string, string> = {};
        details.forEach((outcome) => {
          if (outcome.status === "fulfilled" && outcome.value.skill.description) {
            found[outcome.value.skill.id] = outcome.value.skill.description;
          }
        });
        setDescriptions(found);
      })
      .catch((reason) => {
        if (cancelled || loaded.current) return;
        setState(
          reason instanceof BoltrigApiError && (reason.status === 401 || reason.status === 403)
            ? "denied"
            : "unavailable",
        );
      });
    void client.agentCapabilities()
      .then((result) => {
        if (!cancelled) setAgents(result.agent_capabilities);
      })
      .catch(() => {
        if (!cancelled) setAgents(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (state === "loading") {
    return <Unavailable title="Loading skills">Reading the approved skill library.</Unavailable>;
  }
  if (state === "denied") {
    return <Unavailable title="Skills access denied">Your current role cannot read the skill library.</Unavailable>;
  }
  if (state === "unavailable") {
    return <Unavailable title="Skills unavailable">The skill library could not be reached.</Unavailable>;
  }
  if (skills.length === 0) {
    return <Unavailable title="No skills visible">Record the first skill if your role has authoring access.</Unavailable>;
  }

  return (
    <div className="console-table-wrap">
      <div className="console-table">
        <div className="console-table-head">
          <span aria-hidden className="console-pip" style={{ background: "transparent" }} />
          <span style={{ flex: 1 }}>Skill</span>
          <span className="console-cell">Inherited by</span>
          <span className="console-far">Version</span>
        </div>
        {skills.map((skill) => (
          <button
            className="console-row"
            key={`${skill.id}@${skill.version}`}
            onClick={() => onOpen(skill.id)}
            type="button"
          >
            <span aria-hidden className="console-pip" data-tone={skill.is_active ? "low" : "off"} />
            <span className="console-row-main">
              <span className="console-row-title">
                <span>{skill.id}</span>
                {skill.extends && <span className="console-tech">extends {skill.extends}</span>}
              </span>
              <span className="console-row-sub">
                {descriptions[skill.id]
                  ?? `${skill.tool_grants.length} bounded grants · ${skill.locale}${skill.status === "archived" ? " · archived" : ""}`}
              </span>
            </span>
            <span className="console-cell">{inheritedBy(skill.id, agents)}</span>
            <span className="console-far">v{skill.version}</span>
          </button>
        ))}
      </div>
      <p className="console-foot">
        An agent can only be spawned with skills its profile supports, so the
        inherited-by count is computed from those profiles, nothing else. Facts
        live in Knowledge, where they can be quoted, corrected and deleted.
      </p>
    </div>
  );
}
