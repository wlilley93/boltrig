import type { NamedAgentView } from "@wlilley93/boltrig-web-sdk";

import "./AgentChip.css";

interface AgentChipProps {
  agents: NamedAgentView[];
  value: string;
  disabled?: boolean;
  disabledReason?: string;
  onChange(value: string): void;
}

/** Human-readable next-responder selection; addresses remain transport data. */
export function AgentChip({ agents, value, disabled, disabledReason, onChange }: AgentChipProps) {
  if (agents.length === 0) return null;
  const enabled = agents.filter((agent) => agent.enabled);
  const selected = agents.find((agent) => agent.address === value);
  const fallback = enabled.find((agent) => agent.default_for_intake);
  const label = selected?.name ?? fallback?.name ?? "Choose agent";
  return (
    <label className="agent-chip" title={disabled ? disabledReason : `Next response: ${label}`}>
      <span aria-hidden className="agent-chip-dot" />
      <span className="agent-chip-prefix">To</span>
      <select aria-label="Agent for the next turn" disabled={disabled} value={value}
        onChange={(event) => onChange(event.target.value)}>
        {!fallback && <option value="">Choose agent</option>}
        {enabled.map((agent) => (
          <option key={agent.address} value={agent.address}>{agent.name}</option>
        ))}
      </select>
    </label>
  );
}
