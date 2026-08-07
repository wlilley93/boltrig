import type {
  AgentCapabilityInfo,
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
    // Decision 0012: codex is the only target agent runtime, so it is also the
    // only honest default. This read "hermes" until 2026-08-06, which meant a
    // spec arriving without a runtime was labelled in the console as a lane the
    // kernel would refuse at intake (_SUPPORTED_RUNTIMES = {codex, script}).
    runtime: str(r.runtime) ?? "codex",
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

export function mergeCapabilityProfiles(
  configured: AgentSpec[],
  profiles: AgentCapabilityInfo[],
): AgentSpec[] {
  const merged = new Map(configured.map((agent) => [agent.name, agent]));
  for (const profile of profiles) {
    if (merged.has(profile.name)) continue;
    merged.set(profile.name, {
      name: profile.name,
      kind: "worker",
      runtime: profile.runtime,
      model_endpoint: profile.model_endpoint ?? undefined,
      cost_tier: profile.cost_tier,
      max_depth: profile.max_depth,
      supported_skills: [...profile.supported_skills],
      is_ephemeral: profile.is_ephemeral,
    });
  }
  return [...merged.values()];
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
  // Seeded with the runtimes intake actually accepts. It seeded "hermes" and
  // "pi" until 2026-08-06: pi has been GONE since [2026] VJS-PC 20 L1 and hermes
  // was removed on the Principal's direction, so the console was offering two
  // lanes that no longer exist. Specs' own runtimes still union in, so a legacy
  // lane re-wired via BOLTRIG_ENABLE_LEGACY_RUNTIMES still shows up if in use.
  return [...new Set(["codex", "script", ...specs.map((a) => a.runtime)])].sort();
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
