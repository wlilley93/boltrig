import type { RunRow } from "@/api/types";

export const ALL_STATUS_FILTER = "all-statuses";
export const ALL_OWNER_FILTER = "all-owners";
export const NO_OWNER_FILTER = "owner:none";

export interface RunFilters {
  query: string;
  status: string;
  owner: string;
}

export interface RunStatusCount {
  status: string;
  count: number;
}

export function statusFilterValue(status: string): string {
  return `status:${status}`;
}

export function ownerFilterValue(owner: string | null | undefined): string {
  return owner && owner.trim() ? `owner:${owner}` : NO_OWNER_FILTER;
}

export function runStatusCounts(rows: ReadonlyArray<RunRow>): RunStatusCount[] {
  const counts = new Map<string, number>();
  for (const row of rows) {
    counts.set(row.status, (counts.get(row.status) ?? 0) + 1);
  }
  return Array.from(counts, ([status, count]) => ({ status, count })).sort((a, b) =>
    a.status.localeCompare(b.status),
  );
}

export function runOwners(rows: ReadonlyArray<RunRow>): Array<string | null> {
  const owners = new Set<string>();
  let hasNoOwner = false;
  for (const row of rows) {
    if (row.owner && row.owner.trim()) owners.add(row.owner);
    else hasNoOwner = true;
  }
  const result: Array<string | null> = Array.from(owners).sort((a, b) =>
    a.localeCompare(b),
  );
  if (hasNoOwner) result.push(null);
  return result;
}

function containsQuery(row: RunRow, query: string): boolean {
  const needle = query.trim().toLowerCase();
  if (!needle) return true;
  return [row.intent, row.run_id ?? "", row.work_item].some((value) =>
    value.toLowerCase().includes(needle),
  );
}

export function filterRunRows(
  rows: ReadonlyArray<RunRow>,
  filters: RunFilters,
): RunRow[] {
  return rows.filter(
    (row) =>
      containsQuery(row, filters.query) &&
      (filters.status === ALL_STATUS_FILTER ||
        filters.status === statusFilterValue(row.status)) &&
      (filters.owner === ALL_OWNER_FILTER ||
        filters.owner === ownerFilterValue(row.owner)),
  );
}
