import type { InvokeResult, SkillSummary } from "../../api/types";
import type { ChipOption } from "../uxForm";
import type { AgentModel } from "../agents/model";

export interface AgentParams extends Record<string, unknown> {
  name: string;
  runtime: string;
  supported_skills: string[];
  max_depth: number;
  is_ephemeral: boolean;
  cost_tier: string;
  model_endpoint?: string;
}

export function toParams(agent: AgentModel): AgentParams {
  return {
    name: agent.name,
    runtime: agent.runtime,
    supported_skills: [...agent.supported_skills],
    max_depth: agent.max_depth,
    is_ephemeral: agent.is_ephemeral,
    cost_tier: agent.cost_tier,
    model_endpoint: agent.model_endpoint,
  };
}

export function stable(value: unknown): string {
  return JSON.stringify(value);
}

export function skillScope(skill: SkillSummary): string {
  const slash = skill.id.indexOf("/");
  return slash > 0 ? skill.id.slice(0, slash) : "skills";
}

export function buildSkillOptions(allSkills: SkillSummary[]): ChipOption[] {
  const groups = [...new Set(allSkills.map((skill) => skillScope(skill)))].sort();
  return [
    { value: "*", label: "All skills", hint: "Match every current and future skill." },
    ...groups.map((group) => ({
      value: `${group}/*`,
      label: `${group}/*`,
      hint: `Match every skill under ${group}.`,
    })),
    ...allSkills.map((skill) => ({
      value: skill.id,
      label: skill.id,
      hint: `${skill.version} / ${skill.tool_grants.length} grant(s)`,
    })),
  ];
}

export function classifyResult(result: InvokeResult): string | null {
  if (result.status === "denied" || result.status === "error") return result.reason;
  return null;
}
