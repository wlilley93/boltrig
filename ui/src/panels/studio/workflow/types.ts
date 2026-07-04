import type {
  CapabilitiesResponse,
  WorkflowSummary,
  WorkflowsResponse,
} from "@/api/types";
import type { FetchState } from "@/useFetch";

// A ready-made {value, label} for the shared Select. The four action forms all
// pick from the same list of workflow ids, so the parent computes it once.
export type WorkflowOption = { value: string; label: string };

export interface WfFormProps {
  wfOptions: WorkflowOption[];
}

export interface SidebarProps {
  workflows: FetchState<WorkflowsResponse>;
  caps: FetchState<CapabilitiesResponse>;
}
