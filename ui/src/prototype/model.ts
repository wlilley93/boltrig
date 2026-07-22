export type PrototypeScreen =
  | "home"
  | "chat"
  | "goals"
  | "work"
  | "agents"
  | "automations"
  | "runs"
  | "approvals";

export type Selection = {
  kind: "goal" | "project" | "work" | "agent" | "worker" | "automation" | "run" | "approval" | "node" | "conversation";
  id: string;
};

export interface PrototypeConversation {
  id: string;
  title: string;
  updated: string;
  actor: string;
  state: "live" | "unread" | "settled";
  runId?: string;
}

export interface Goal {
  id: string;
  title: string;
  outcome: string;
  status: "on-track" | "at-risk" | "blocked" | "achieved";
  progress: number;
  owner: string;
  target: string;
  budget: string;
  spent: string;
}

export interface Project {
  id: string;
  goalId: string;
  title: string;
  status: "active" | "blocked" | "completed";
  confidence: number;
  owner: string;
}

export interface DurableAgent {
  id: string;
  name: string;
  title: string;
  tier: 1 | 2;
  department: string;
  status: "active" | "paused" | "degraded";
  reportsTo?: string;
  activeWork: number;
  budgetUsed: number;
  nextHeartbeat: string;
  capabilities: string[];
}

export interface EphemeralWorker {
  id: string;
  name: string;
  parentAgent: string;
  runId: string;
  status: "running" | "waiting" | "completed";
  purpose: string;
  age: string;
  cost: string;
  step: string;
  expires: string;
  grants: string[];
}

export interface WorkItem {
  id: string;
  title: string;
  goalId?: string;
  projectId?: string;
  owner: string;
  worker?: string;
  status: "pending" | "in-flight" | "blocked" | "awaiting-human" | "done";
  priority: "urgent" | "high" | "normal";
  due: string;
  dependency?: string;
  aligned: boolean;
  artifact?: string;
}

export interface Run {
  id: string;
  title: string;
  workId: string;
  agentId: string;
  status: "running" | "waiting" | "completed" | "paused";
  cost: string;
  duration: string;
  steps: { label: string; status: "done" | "running" | "waiting" | "pending" }[];
}

export interface Approval {
  id: string;
  title: string;
  requestedBy: string;
  runId: string;
  consequence: "high" | "medium";
  status: "pending" | "approved" | "rejected";
  verb: string;
  stakes: string;
}

export const goals: Goal[] = [
  {
    id: "goal-beta",
    title: "Launch the governed automation beta",
    outcome: "Ten design partners run dependable automations with visible controls and recovery.",
    status: "at-risk",
    progress: 68,
    owner: "agent-product",
    target: "30 Sep 2026",
    budget: "£12,000",
    spent: "£7,840",
  },
  {
    id: "goal-evidence",
    title: "Build a continuous customer evidence loop",
    outcome: "Every roadmap decision links to current, reviewed customer evidence.",
    status: "on-track",
    progress: 82,
    owner: "agent-research",
    target: "15 Aug 2026",
    budget: "£4,000",
    spent: "£2,110",
  },
  {
    id: "goal-readiness",
    title: "Prove production readiness",
    outcome: "Release, restore, identity, model, and runtime seams are verified in the target environment.",
    status: "blocked",
    progress: 54,
    owner: "agent-operations",
    target: "31 Aug 2026",
    budget: "£8,000",
    spent: "£4,920",
  },
];

export const projects: Project[] = [
  { id: "project-evidence", goalId: "goal-beta", title: "Customer evidence and release readiness", status: "active", confidence: 74, owner: "agent-research" },
  { id: "project-runtime", goalId: "goal-beta", title: "Runtime and recovery proof", status: "blocked", confidence: 58, owner: "agent-operations" },
  { id: "project-pilot", goalId: "goal-evidence", title: "Design partner pilot", status: "active", confidence: 86, owner: "agent-product" },
];

export const agents: DurableAgent[] = [
  { id: "agent-bolt", name: "Bolt", title: "Chief of Staff", tier: 1, department: "Organisation", status: "active", activeWork: 7, budgetUsed: 62, nextHeartbeat: "in 4 min", capabilities: ["work.delegate", "goal.review", "budget.read", "workflow.trigger"] },
  { id: "agent-product", name: "Product", title: "Product Lead", tier: 2, department: "Product", status: "active", reportsTo: "agent-bolt", activeWork: 4, budgetUsed: 48, nextHeartbeat: "in 11 min", capabilities: ["work.plan", "memory.recall", "eval.run"] },
  { id: "agent-research", name: "Research", title: "Evidence Lead", tier: 2, department: "Research", status: "active", reportsTo: "agent-bolt", activeWork: 6, budgetUsed: 71, nextHeartbeat: "in 7 min", capabilities: ["web.fetch", "memory.remember", "work.delegate"] },
  { id: "agent-operations", name: "Operations", title: "Operations Lead", tier: 2, department: "Operations", status: "degraded", reportsTo: "agent-bolt", activeWork: 3, budgetUsed: 84, nextHeartbeat: "held", capabilities: ["workflow.execute", "channel.send", "health.read"] },
];

export const workers: EphemeralWorker[] = [
  { id: "worker-a19f", name: "Research Scout T3-A19F", parentAgent: "agent-research", runId: "run-2048", status: "running", purpose: "Find current evidence from design-partner interviews", age: "6m 12s", cost: "£0.84", step: "Reviewing interview 8 of 12", expires: "in 23 min", grants: ["memory.recall", "web.fetch"] },
  { id: "worker-b720", name: "Interview Synthesiser T3-B720", parentAgent: "agent-research", runId: "run-2048", status: "running", purpose: "Cluster objections and identify repeated evidence", age: "4m 51s", cost: "£0.63", step: "Merging evidence clusters", expires: "in 25 min", grants: ["memory.recall", "memory.remember"] },
  { id: "worker-c042", name: "Release Checker T3-C042", parentAgent: "agent-operations", runId: "run-2044", status: "waiting", purpose: "Verify the candidate release evidence", age: "18m 03s", cost: "£1.44", step: "Waiting for human approval", expires: "in 12 min", grants: ["health.read", "audit.search"] },
];

export const workItems: WorkItem[] = [
  { id: "work-142", title: "Synthesize design-partner interviews", goalId: "goal-beta", projectId: "project-evidence", owner: "agent-research", worker: "worker-a19f", status: "in-flight", priority: "high", due: "Today", aligned: true, artifact: "Evidence digest - Week 29" },
  { id: "work-143", title: "Verify off-box restore drill", goalId: "goal-readiness", projectId: "project-runtime", owner: "agent-operations", status: "blocked", priority: "urgent", due: "18 Jul", dependency: "Production backup credentials", aligned: true },
  { id: "work-144", title: "Review public beta narrative", goalId: "goal-beta", projectId: "project-evidence", owner: "agent-product", status: "awaiting-human", priority: "high", due: "Tomorrow", aligned: true },
  { id: "work-145", title: "Triage unsorted feedback", owner: "agent-product", status: "pending", priority: "normal", due: "22 Jul", aligned: false },
  { id: "work-139", title: "Map pilot success criteria", goalId: "goal-evidence", projectId: "project-pilot", owner: "agent-product", status: "done", priority: "normal", due: "Done 14 Jul", aligned: true, artifact: "Pilot scorecard v2" },
];

export const runs: Run[] = [
  { id: "run-2048", title: "Customer evidence synthesis", workId: "work-142", agentId: "agent-research", status: "running", cost: "£1.47", duration: "11m 03s", steps: [
    { label: "Lease aligned work", status: "done" }, { label: "Load scoped evidence", status: "done" }, { label: "Spawn research workers", status: "done" }, { label: "Merge findings", status: "running" }, { label: "Human review", status: "pending" },
  ] },
  { id: "run-2044", title: "Release readiness verification", workId: "work-143", agentId: "agent-operations", status: "waiting", cost: "£2.18", duration: "28m 41s", steps: [
    { label: "Check candidate", status: "done" }, { label: "Validate evidence", status: "done" }, { label: "Approve publication", status: "waiting" }, { label: "Publish receipt", status: "pending" },
  ] },
  { id: "run-2039", title: "Pilot success criteria", workId: "work-139", agentId: "agent-product", status: "completed", cost: "£0.92", duration: "7m 18s", steps: [
    { label: "Collect constraints", status: "done" }, { label: "Draft scorecard", status: "done" }, { label: "Review output", status: "done" },
  ] },
];

export const approvals: Approval[] = [
  { id: "approval-77", title: "Publish customer-facing beta summary", requestedBy: "agent-product", runId: "run-2044", consequence: "high", status: "pending", verb: "channel.send", stakes: "This publishes an externally visible statement to the design-partner channel." },
  { id: "approval-76", title: "Retain interview evidence for 90 days", requestedBy: "agent-research", runId: "run-2048", consequence: "medium", status: "pending", verb: "memory.remember", stakes: "This keeps derived customer evidence beyond the default short-term retention window." },
];

export const conversations: PrototypeConversation[] = [
  { id: "conversation-evidence", title: "Turn research into a weekly evidence brief", updated: "Now", actor: "Bolt", state: "live", runId: "run-2048" },
  { id: "conversation-readiness", title: "Prepare the production readiness review", updated: "24 min", actor: "Operations", state: "unread", runId: "run-2044" },
  { id: "conversation-pilot", title: "Define the design-partner pilot", updated: "Yesterday", actor: "Product", state: "settled", runId: "run-2039" },
  { id: "conversation-memory", title: "What did customers say about approvals?", updated: "Monday", actor: "Research", state: "settled" },
];

export function byId<T extends { id: string }>(rows: T[], id: string): T | undefined {
  return rows.find((row) => row.id === id);
}
