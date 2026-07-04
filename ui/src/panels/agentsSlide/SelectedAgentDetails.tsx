import { navigate } from "@/router";
import { GrantList } from "@/panels/uxFlow";
import { InfoCallout, StatusBadge, CONSEQUENCE } from "@/panels/ux";
import { kindLabel } from "./AgentNode";
import type { AgentModel } from "@/panels/agents/model";

export function SelectedAgentDetails({ agent }: { agent: AgentModel | undefined }) {
  if (!agent) return null;
  return (
    <>
      <aside className="ag-facts" aria-label="Selected agent">
        <div>
          <span className="badge">{kindLabel(agent.kind)}</span>{" "}
          <code>{agent.name}</code>
          <span className="ag-facts__muted">
            {" "}
            {agent.runtime} / {agent.model_endpoint ?? "default"} / depth {agent.max_depth}
          </span>
        </div>
        <div className="ag-facts__metrics">
          <span>{agent.matchedSkills.length} matched skills</span>
          <span>{agent.effectiveGrants.length} grants</span>
          <span>{agent.effectiveVerbs.length} callable verbs</span>
          <span>{agent.workItems.length} work items</span>
        </div>
        <button
          type="button"
          className="btn btn--sm"
          onClick={() => navigate(`/agents/${encodeURIComponent(agent.name)}`)}
        >
          Open agent
        </button>
      </aside>

      {agent.effectiveGrants.length > 0 && (
        <div className="ag-anchor-grants">
          <span className="muted">Selected effective grants</span>
          <GrantList grants={agent.effectiveGrants.slice(0, 8)} />
        </div>
      )}

      {agent.boundVerbs.some((verb) => verb.consequence === "high") && (
        <InfoCallout tone="consequence" title="High consequence bindings">
          This selected agent fulfils at least one high-consequence verb. The
          kernel still pauses those calls for approval.
        </InfoCallout>
      )}

      {agent.boundVerbs.slice(0, 3).map((verb) => (
        <span className="ag-bound-preview" key={verb.id}>
          <code>{verb.id}</code>
          <StatusBadge value={verb.consequence} glossary={CONSEQUENCE} />
        </span>
      ))}
    </>
  );
}
