import { useState } from "react";

import type { StatusAck } from "@/api/types";
import { csvToList, errText, parseJson } from "@/panels/shared";
import {
  outputRecord,
  useControlMutation,
  type ControlMutationState,
} from "@/panels/uxFlow";

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
  mutation: ControlMutationState;
  upsert: () => Promise<void>;
  addGrant: (id: string) => void;
}

export function useSkillForm(onSaved: () => void): SkillFormState {
  const [id, setId] = useState("");
  const [version, setVersion] = useState("1.0.0");
  const [fragment, setFragment] = useState("");
  const [grants, setGrants] = useState("");
  const [ctxReq, setCtxReq] = useState("{}");
  const [validationError, setValidationError] = useState<string | null>(null);
  const [ack, setAck] = useState<StatusAck | null>(null);
  const mutation = useControlMutation({
    verb: "control.skill.upsert",
    onApplied: (output) => {
      setAck({ ...outputRecord(output), status: "ok" });
      onSaved();
    },
  });

  async function upsert() {
    if (!id.trim()) {
      setValidationError("Skill id is required.");
      return;
    }
    let contextRequirements: Record<string, unknown>;
    try {
      contextRequirements = parseJson<Record<string, unknown>>(ctxReq, {});
    } catch (err) {
      setValidationError(`context_requirements: ${errText(err)}`);
      return;
    }
    setValidationError(null);
    setAck(null);
    await mutation.invoke({
      id: id.trim(),
      version: version.trim() || "1.0.0",
      prompt_fragment: fragment,
      tool_grants: csvToList(grants),
      context_requirements: contextRequirements,
    });
  }

  function addGrant(gid: string) {
    const have = csvToList(grants);
    if (!have.includes(gid)) setGrants([...have, gid].join(", "));
  }

  return {
    id, setId, version, setVersion, fragment, setFragment, grants, setGrants,
    ctxReq, setCtxReq, busy: mutation.busy,
    error: validationError ?? mutation.error,
    ack, mutation, upsert, addGrant,
  };
}
