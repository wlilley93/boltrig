import { AgentNode } from "./AgentNode";
import type { AgentModel } from "@/panels/agents/model";

export function OrgChart({
  chief,
  heads,
  workers,
  selectedAgent,
  onSelect,
}: {
  chief: AgentModel | undefined;
  heads: AgentModel[];
  workers: AgentModel[];
  selectedAgent: AgentModel | undefined;
  onSelect: (name: string) => void;
}) {
  return (
    <div className="ag-chart" aria-label="Agent org chart">
      {chief && (
        <div className="ag-chart__row ag-chart__row--chief">
          <AgentNode
            agent={chief}
            selected={selectedAgent?.name === chief.name}
            onSelect={() => onSelect(chief.name)}
          />
        </div>
      )}

      {heads.length > 0 && (
        <div className="ag-chart__row ag-chart__row--heads">
          {heads.map((agent) => (
            <AgentNode
              key={agent.name}
              agent={agent}
              selected={selectedAgent?.name === agent.name}
              onSelect={() => onSelect(agent.name)}
            />
          ))}
        </div>
      )}

      {workers.length > 0 && (
        <div className="ag-worker-band">
          <div className="ag-worker-band__head">
            <strong>Worker pool</strong>
            <span>
              Ephemeral profiles are chosen per task and discarded after the run.
            </span>
          </div>
          <div className="ag-chart__row ag-chart__row--workers">
            {workers.map((agent) => (
              <AgentNode
                key={agent.name}
                agent={agent}
                selected={selectedAgent?.name === agent.name}
                onSelect={() => onSelect(agent.name)}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
