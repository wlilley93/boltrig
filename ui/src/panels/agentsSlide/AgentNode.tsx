import { navigate } from "@/router";
import { budgetPct, type AgentModel } from "@/panels/agents/model";

export function kindLabel(kind: string): string {
  if (kind === "chief") return "chief of staff";
  if (kind === "head") return "department head";
  return "worker profile";
}

export function AgentNode({
  agent,
  selected,
  onSelect,
}: {
  agent: AgentModel;
  selected: boolean;
  onSelect: () => void;
}) {
  const pct = budgetPct(agent.budget);
  const open = () => navigate(`/agents/${encodeURIComponent(agent.name)}`);
  return (
    <button
      type="button"
      className={`ag-node ag-node--${agent.kind} ${selected ? "ag-node--selected" : ""}`}
      aria-pressed={selected}
      onClick={onSelect}
      onDoubleClick={open}
      onKeyDown={(e) => {
        if (e.key === "Enter" && selected) {
          e.preventDefault();
          open();
        }
      }}
      title={`Open ${agent.name}`}
    >
      <span className="ag-node__kind">{kindLabel(agent.kind)}</span>
      <strong className="ag-node__name">{agent.name}</strong>
      {agent.department && <span className="ag-node__dept">{agent.department}</span>}
      <span className="ag-node__facts">
        <span>{agent.runtime}</span>
        <span>{agent.model_endpoint ?? "default model"}</span>
        <span>depth {agent.max_depth}</span>
      </span>
      <span className="ag-node__chips">
        <span className="badge">{agent.cost_tier}</span>
        <span className="badge">{agent.matchedSkills.length} skills</span>
        <span className="badge">{agent.effectiveVerbs.length} verbs</span>
        {agent.boundVerbs.length > 0 && (
          <span className="badge badge--conseq-low">{agent.boundVerbs.length} bound</span>
        )}
      </span>
      {pct !== null && (
        <span className="ag-budget" title="Department budget used">
          <span className="ag-budget__fill" style={{ width: `${pct}%` }} />
        </span>
      )}
    </button>
  );
}
