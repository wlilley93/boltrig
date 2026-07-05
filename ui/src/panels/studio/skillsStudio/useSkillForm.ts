import { useState } from "react";

import { api } from "@/api/client";
import type { StatusAck } from "@/api/types";
import { csvToList, errText, parseJson } from "@/panels/shared";

export interface SkillFormState {
  id: string;
  setId: (v: string) => void;
  version: string;
  setVersion: (v: string) => void;
  fragment: string;
  setFragment: (v: string) => void;
  grants: string;
  setGrants: (v: string) => void;
  ctxReq: string;
  setCtxReq: (v: string) => void;
  busy: boolean;
  error: string | null;
  ack: StatusAck | null;
  upsert: () => Promise<void>;
  addGrant: (id: string) => void;
}

export function useSkillForm(onSaved: () => void): SkillFormState {
  const [id, setId] = useState("");
  const [version, setVersion] = useState("1.0.0");
  const [fragment, setFragment] = useState("");
  const [grants, setGrants] = useState("");
  const [ctxReq, setCtxReq] = useState("{}");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ack, setAck] = useState<StatusAck | null>(null);

  async function upsert() {
    if (!id.trim()) {
      setError("Skill id is required.");
      return;
    }
    let contextRequirements: Record<string, unknown>;
    try {
      contextRequirements = parseJson<Record<string, unknown>>(ctxReq, {});
    } catch (err) {
      setError(`context_requirements: ${errText(err)}`);
      return;
    }
    setBusy(true);
    setError(null);
    setAck(null);
    try {
      const res = await api.upsertSkill({
        id: id.trim(),
        version: version.trim() || "1.0.0",
        prompt_fragment: fragment,
        tool_grants: csvToList(grants),
        context_requirements: contextRequirements,
      });
      setAck(res);
      if (res.status === "ok") onSaved();
    } catch (err) {
      setError(errText(err));
    } finally {
      setBusy(false);
    }
  }

  function addGrant(gid: string) {
    const have = csvToList(grants);
    if (!have.includes(gid)) setGrants([...have, gid].join(", "));
  }

  return {
    id, setId, version, setVersion, fragment, setFragment, grants, setGrants,
    ctxReq, setCtxReq, busy, error, ack, upsert, addGrant,
  };
}
