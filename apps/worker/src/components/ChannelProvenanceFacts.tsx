import type {
  ChannelMessageProvenance,
  RunRow,
  WorkItem,
} from "@wlilley93/boltrig-web-sdk";

export function originLabel(value: {
  source?: string | null;
  provenance?: ChannelMessageProvenance | null;
}): string {
  return value.provenance?.display_label || value.source || "Boltrig";
}

function Fact({ label, value }: { label: string; value: string }) {
  return <div><dt>{label}</dt><dd>{value}</dd></div>;
}

function ProvenanceFacts({ provenance }: { provenance?: ChannelMessageProvenance | null }) {
  if (!provenance) return null;
  const from = provenance.from.label || provenance.from.subject || "Authenticated sender";
  const to = provenance.to.label || provenance.to.address || "Unassigned";
  return <>
    <Fact label="Origin" value={provenance.display_label} />
    <Fact label="From" value={from} />
    <Fact label="Routed to" value={to} />
  </>;
}

export function RunFacts({ run }: { run: RunRow }) {
  return <>
    <Fact label="Run" value={run.run_id ?? "Not started"} />
    <Fact label="Status" value={run.status} />
    <Fact label="Owner" value={run.owner ?? "Unassigned"} />
    <Fact label="Work item" value={run.work_item} />
    <ProvenanceFacts provenance={run.provenance} />
  </>;
}

export function WorkFacts({ item }: { item: WorkItem }) {
  return <>
    <Fact label="ID" value={item.id} />
    <Fact label="Status" value={item.status.replaceAll("_", " ")} />
    <Fact label="Owner" value={item.owner_member ?? "Unassigned"} />
    <Fact label="Confidence" value={item.confidence == null ? "—" : `${Math.round(item.confidence * 100)}%`} />
    <Fact label="Source" value={item.source ?? "Boltrig"} />
    <Fact label="Shape" value={item.convergent ? "Convergent goal" : "Non-convergent work"} />
    <Fact label="Parent" value={item.parent_id ?? "Root"} />
    <Fact label="Hatchet run" value={item.hatchet_run_id ?? "None"} />
    <Fact label="On behalf of" value={item.on_behalf_of ?? "Self"} />
    <ProvenanceFacts provenance={item.provenance} />
  </>;
}
