import { useMemo } from "react";
import { api } from "@/api/client";
import { useFetch } from "@/useFetch";

export function useWorkflowData() {
  const workflows = useFetch(() => api.workflows(), []);
  const caps = useFetch(() => api.capabilities(), []);
  const verbs = useMemo(() => caps.data?.verbs ?? [], [caps.data]);
  const verbsById = useMemo(
    () => new Map(verbs.map((v) => [v.id, v])),
    [verbs],
  );
  return { workflows, caps, verbs, verbsById };
}
