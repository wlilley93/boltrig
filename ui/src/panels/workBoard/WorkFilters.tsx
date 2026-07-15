import type { WorkStatus } from "@/api/types";
import { Field, Select, WORK_STATUS } from "@/panels/ux";
import {
  ALL_STATUSES,
  WORK_STATUS_ORDER,
  type WorkFiltersState,
  type WorkView,
} from "./model";

export function WorkFilters({
  filters,
  onChange,
  owners,
  sources,
  view,
  onViewChange,
}: {
  filters: WorkFiltersState;
  onChange: (next: WorkFiltersState) => void;
  owners: Array<{ value: string; label: string }>;
  sources: Array<{ value: string; label: string }>;
  view: WorkView;
  onViewChange: (view: WorkView) => void;
}) {
  const patch = (next: Partial<WorkFiltersState>) => onChange({ ...filters, ...next });
  return (
    <section className="work-filters" aria-label="Work queue controls">
      <div className="seg work-filters__views" role="group" aria-label="View">
        {(["project", "linear", "board"] as WorkView[]).map((value) => (
          <button
            key={value}
            type="button"
            className={`btn btn--seg ${view === value ? "btn--seg-on" : ""}`}
            aria-pressed={view === value}
            onClick={() => onViewChange(value)}
          >
            {value[0].toUpperCase() + value.slice(1)}
          </button>
        ))}
      </div>
      <div className="work-filters__grid">
        <Field label="Search" htmlFor="work-search" wide>
          <input
            id="work-search"
            type="search"
            value={filters.query}
            placeholder="Intent, ID, owner, or parent"
            onChange={(event) => patch({ query: event.target.value })}
          />
        </Field>
        <Field label="Status" htmlFor="work-status">
          <Select
            id="work-status"
            value={filters.status}
            onChange={(status) => patch({ status })}
            options={[
              { value: ALL_STATUSES, label: "All statuses" },
              ...WORK_STATUS_ORDER.map((status: WorkStatus) => ({
                value: status,
                label: WORK_STATUS[status]?.label ?? status,
              })),
            ]}
          />
        </Field>
        <Field label="Owner" htmlFor="work-owner">
          <Select
            id="work-owner"
            value={filters.owner}
            onChange={(owner) => patch({ owner })}
            options={[{ value: "all-owners", label: "All owners" }, ...owners]}
          />
        </Field>
        <Field label="Source" htmlFor="work-source">
          <Select
            id="work-source"
            value={filters.source}
            onChange={(source) => patch({ source })}
            options={[{ value: "all-sources", label: "All sources" }, ...sources]}
          />
        </Field>
        <Field label="Convergence" htmlFor="work-convergent">
          <Select
            id="work-convergent"
            value={filters.convergent}
            onChange={(value) => patch({ convergent: value as WorkFiltersState["convergent"] })}
            options={[
              { value: "all", label: "All work" },
              { value: "yes", label: "Convergent goals" },
              { value: "no", label: "Open-ended work" },
            ]}
          />
        </Field>
      </div>
    </section>
  );
}
