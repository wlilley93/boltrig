import type {
  BudgetItem,
  ConfigSectionResponse,
  SkillSummary,
  VerbInfo,
  WorkItem,
} from "../../api/types";
import type { DeckCol } from "../../deck/Deck";
import { grantMatches } from "../uxForm";

export type AgentKind = "chief" | "head" | "worker";

export interface AgentSpec {
  name: string;
  kind: AgentKind;
  department?: string;
  runtime: string;
  model_endpoint?: string;
  cost_tier: string;
  max_depth: number;
  supported_skills: string[];
  is_ephemeral: boolean;
}

export interface AgentModel extends AgentSpec {
  matchedSkills: SkillSummary[];
  effectiveGrants: string[];
  effectiveVerbs: VerbInfo[];
  boundVerbs: VerbInfo[];
  budget?: BudgetItem;
  workItems: WorkItem[];
}

export interface ModelEndpointOption {
  id: string;
  kind?: string;
  model?: string;
  data_class?: string;
  base_url?: string;
}

export function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function str(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value : undefined;
}

function num(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function strList(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((s): s is string => typeof s === "string" && s.trim().length > 0)
    : [];
}

export function deniedOf(res: ConfigSectionResponse | null): string | null {
  if (!res) return null;
  if (res.status === "denied" || res.error) {
    return res.reason ?? res.error ?? "admin_forbidden";
  }
  return null;
}

function specFromRaw(raw: unknown, kind: AgentKind): AgentSpec | null {
  const r = asRecord(raw);
  const name = str(r?.name);
  if (!r || !name) return null;
  return {
    name,
    kind,
    department: str(r.department),
    runtime: str(r.runtime) ?? "hermes",
    model_endpoint: str(r.model_endpoint),
    cost_tier: str(r.cost_tier) ?? "standard",
    max_depth: num(r.max_depth, kind === "chief" ? 4 : 2),
    supported_skills: strList(r.supported_skills),
    is_ephemeral: kind === "worker",
  };
}

export function readAgentSpecs(
  hierarchy: ConfigSectionResponse | null,
  pool: ConfigSectionResponse | null,
): AgentSpec[] {
  const h = asRecord(hierarchy?.value);
  const chief = specFromRaw(h?.tier1, "chief");
  const heads = (Array.isArray(h?.tier2) ? h?.tier2 : [])
    .map((item) => specFromRaw(item, "head"))
    .filter((a): a is AgentSpec => a !== null);
  const workers = (Array.isArray(pool?.value) ? pool?.value : [])
    .map((item) => specFromRaw(item, "worker"))
    .filter((a): a is AgentSpec => a !== null);
  return [...(chief ? [chief] : []), ...heads, ...workers];
}

export function agentColumns(specs: AgentSpec[]): DeckCol[] {
  return specs.map((agent) => ({
    key: agent.name,
    label: agent.name,
    path: `/agents/${encodeURIComponent(agent.name)}`,
  }));
}

export function skillMatches(pattern: string, skillId: string): boolean {
  if (pattern === "*") return true;
  if (pattern.endsWith("/*")) return skillId.startsWith(pattern.slice(0, -1));
  if (pattern.endsWith("*")) return skillId.startsWith(pattern.slice(0, -1));
  return pattern === skillId;
}

export function matchesAny(patterns: string[], skillId: string): boolean {
  return patterns.some((pattern) => skillMatches(pattern, skillId));
}

export function enrichAgents(
  specs: AgentSpec[],
  skills: SkillSummary[],
  verbs: VerbInfo[],
  budgets: BudgetItem[],
  work: WorkItem[],
): AgentModel[] {
  return specs.map((agent) => {
    const matchedSkills = skills.filter((skill) =>
      matchesAny(agent.supported_skills, skill.id),
    );
    const effectiveGrants = [
      ...new Set(matchedSkills.flatMap((skill) => skill.tool_grants ?? [])),
    ].sort();
    const effectiveVerbs = verbs
      .filter((verb) => effectiveGrants.some((grant) => grantMatches(grant, verb.id)))
      .sort((a, b) => a.id.localeCompare(b.id));
    const boundVerbs = verbs
      .filter(
        (verb) =>
          verb.binding?.target_type === "agent" &&
          verb.binding.target_ref === agent.name,
      )
      .sort((a, b) => a.id.localeCompare(b.id));
    const budget =
      agent.department !== undefined
        ? budgets.find(
            (b) => b.scope_type === "department" && b.id === agent.department,
          )
        : undefined;
    const workItems =
      agent.kind === "chief"
        ? work
        : agent.department
          ? work.filter((item) => item.owner_member === agent.department)
          : [];
    return {
      ...agent,
      matchedSkills,
      effectiveGrants,
      effectiveVerbs,
      boundVerbs,
      budget,
      workItems,
    };
  });
}

export function readModelEndpoints(
  models: ConfigSectionResponse | null,
): ModelEndpointOption[] {
  const m = asRecord(models?.value);
  const endpoints = Array.isArray(m?.endpoints) ? m?.endpoints : [];
  const parsed: ModelEndpointOption[] = [];
  for (const item of endpoints) {
    const r = asRecord(item);
    const id = str(r?.id);
    if (!r || !id) continue;
    parsed.push({
      id,
      kind: str(r.kind),
      model: str(r.model),
      data_class: str(r.data_class),
      base_url: str(r.base_url),
    });
  }
  return parsed;
}

export function runtimeOptions(specs: AgentSpec[]): string[] {
  return [...new Set(["hermes", "pi", ...specs.map((a) => a.runtime)])].sort();
}

export function budgetPct(budget?: BudgetItem): number | null {
  if (!budget) return null;
  if (budget.token_limit && budget.token_limit > 0) {
    return Math.min(100, Math.round((budget.spent_tokens / budget.token_limit) * 100));
  }
  if (budget.cost_limit_micros && budget.cost_limit_micros > 0) {
    return Math.min(100, Math.round((budget.spent_micros / budget.cost_limit_micros) * 100));
  }
  return null;
}
