export function AgentCounts({
  chief,
  headsCount,
  workersCount,
  verbCount,
}: {
  chief: unknown;
  headsCount: number;
  workersCount: number;
  verbCount: number | undefined;
}) {
  return (
    <div className="ag-counts" aria-label="Agent counts">
      <span>{chief ? "1" : "0"} chief</span>
      <span>{headsCount} departments</span>
      <span>{workersCount} worker profiles</span>
      {verbCount !== undefined && <span>{verbCount} scoped verbs visible</span>}
    </div>
  );
}
