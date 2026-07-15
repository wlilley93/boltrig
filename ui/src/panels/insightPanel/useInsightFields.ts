import { useState } from "react";

import { api } from "@/api/client";
import type {
  AuditExportResponse,
  AuditRow,
  CapabilitiesResponse,
  CostResponse,
  RunRow,
  RunsResponse,
} from "@/api/types";
import { useFetch, type FetchState } from "@/useFetch";

export interface InsightFields {
  cost: FetchState<CostResponse>;
  runs: FetchState<RunsResponse>;
  caps: FetchState<CapabilitiesResponse>;
  refresh: () => void;
  actor: string;
  setActor: (v: string) => void;
  verb: string;
  setVerb: (v: string) => void;
  run: string;
  setRun: (v: string) => void;
  resource: string;
  setResource: (v: string) => void;
  status: string;
  setStatus: (v: string) => void;
  since: string;
  setSince: (v: string) => void;
  until: string;
  setUntil: (v: string) => void;
  stream: "audit" | "security";
  setStream: (v: "audit" | "security") => void;
  eventType: string;
  setEventType: (v: string) => void;
  searchBusy: boolean;
  setSearchBusy: (v: boolean) => void;
  searchError: string | null;
  setSearchError: (v: string | null) => void;
  rows: AuditRow[] | null;
  setRows: (v: AuditRow[] | null) => void;
  searchScope: string;
  setSearchScope: (v: string) => void;
  exported: AuditExportResponse | null;
  setExported: (v: AuditExportResponse | null) => void;
  exportError: string | null;
  setExportError: (v: string | null) => void;
  exportBusy: boolean;
  setExportBusy: (v: boolean) => void;
  costData: CostResponse | null;
  runRows: RunRow[];
  actorOptions: { value: string; label: string }[];
  verbOptions: { value: string; label: string }[];
}

export function useInsightFields(): InsightFields {
  const cost = useFetch(() => api.cost(), []);
  const runs = useFetch(() => api.runs(), []);
  const caps = useFetch(() => api.capabilities(), []);

  const [actor, setActor] = useState("");
  const [verb, setVerb] = useState("");
  const [run, setRun] = useState("");
  const [resource, setResource] = useState("");
  const [status, setStatus] = useState("");
  const [since, setSince] = useState("");
  const [until, setUntil] = useState("");
  const [stream, setStream] = useState<"audit" | "security">("audit");
  const [eventType, setEventType] = useState("");
  const [searchBusy, setSearchBusy] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [rows, setRows] = useState<AuditRow[] | null>(null);
  const [searchScope, setSearchScope] = useState<string>("");
  const [exported, setExported] = useState<AuditExportResponse | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);
  const [exportBusy, setExportBusy] = useState(false);

  const costData = cost.data;
  const runRows: RunRow[] = runs.data?.runs ?? [];
  const actorOptions = [
    { value: "", label: "Any actor" },
    ...Object.keys(costData?.by_actor ?? {}).map((a) => ({ value: a, label: a })),
  ];
  const verbOptions = [
    { value: "", label: "Any action" },
    ...(caps.data?.verbs ?? []).map((v) => ({ value: v.id, label: v.id })),
  ];

  function refresh() {
    cost.reload();
    runs.reload();
  }

  return {
    cost, runs, caps, refresh, actor, setActor, verb, setVerb, run, setRun,
    resource, setResource, status, setStatus, since, setSince, until, setUntil,
    stream, setStream, eventType, setEventType,
    searchBusy, setSearchBusy, searchError, setSearchError, rows, setRows,
    searchScope, setSearchScope, exported, setExported, exportError,
    setExportError, exportBusy, setExportBusy, costData, runRows, actorOptions,
    verbOptions,
  };
}
