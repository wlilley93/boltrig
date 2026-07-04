import { useEffect, useMemo, useState } from "react";

import { api } from "../../api/client";
import type {
  BudgetItem,
  InvokeResult,
  SkillSummary,
  VerbInfo,
  WorkItem,
} from "../../api/types";
import { apiReason } from "../shared";
import { enrichAgents, type AgentModel } from "../agents/model";
import { type AgentParams, classifyResult, stable, toParams } from "./types";

export interface AgentSlideForm {
  saved: AgentParams | null;
  draft: AgentParams | null;
  jsonText: string;
  jsonError: string | null;
  saving: boolean;
  error: string | null;
  pending: { id: string; params: AgentParams } | null;
  preview: AgentModel | null;
  dirty: boolean;
  update: (next: Partial<AgentParams>) => void;
  updateJson: (text: string) => void;
  save: () => Promise<void>;
  discard: () => void;
  onApplied: (result: InvokeResult) => void;
  onDenied: (reason: string) => void;
}

export function useAgentSlideForm(input: {
  agent: AgentModel | undefined;
  skills: SkillSummary[];
  verbs: VerbInfo[];
  budgets: BudgetItem[];
  work: WorkItem[];
}): AgentSlideForm {
  const { agent } = input;
  const [saved, setSaved] = useState<AgentParams | null>(null);
  const [draft, setDraft] = useState<AgentParams | null>(null);
  const [jsonText, setJsonText] = useState("");
  const [jsonError, setJsonError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<{ id: string; params: AgentParams } | null>(null);

  useEffect(() => {
    if (!agent) return;
    const params = toParams(agent);
    setSaved(params);
    setDraft(params);
    setJsonText(JSON.stringify(params, null, 2));
    setJsonError(null);
    setError(null);
    setPending(null);
  }, [agent?.name]);

  const preview = useMemo(() => {
    if (!agent || !draft) return null;
    return enrichAgents(
      [{ ...agent, ...draft }],
      input.skills,
      input.verbs,
      input.budgets,
      input.work,
    )[0];
  }, [agent, draft, input.skills, input.verbs, input.budgets, input.work]);

  const dirty = draft !== null && saved !== null && stable(draft) !== stable(saved);

  function update(next: Partial<AgentParams>) {
    setDraft((current) => {
      if (!current) return current;
      const merged = { ...current, ...next };
      setJsonText(JSON.stringify(merged, null, 2));
      setJsonError(null);
      return merged;
    });
  }

  function updateJson(text: string) {
    setJsonText(text);
    try {
      const parsed = JSON.parse(text) as AgentParams;
      setDraft(parsed);
      setJsonError(null);
    } catch {
      setJsonError("Fix the JSON before requesting a change.");
    }
  }

  async function save() {
    if (!draft || jsonError) return;
    setSaving(true);
    setError(null);
    try {
      const result = await api.invoke({
        noun: "control",
        verb: "control.capability.upsert",
        params: draft,
      });
      if (result.status === "pending_human") {
        setPending({ id: result.hitl_request_id, params: draft });
        return;
      }
      const reason = classifyResult(result);
      if (reason) {
        setError(reason);
        return;
      }
      setSaved(draft);
    } catch (err) {
      setError(apiReason(err));
    } finally {
      setSaving(false);
    }
  }

  function discard() {
    if (!saved) return;
    setDraft(saved);
    setJsonText(JSON.stringify(saved, null, 2));
    setJsonError(null);
    setError(null);
  }

  function onApplied(result: InvokeResult) {
    if (!pending) return;
    const reason = classifyResult(result);
    if (reason) {
      setError(reason);
      return;
    }
    setSaved(pending.params);
    setDraft(pending.params);
    setPending(null);
  }

  function onDenied(reason: string) {
    setError(reason);
  }

  return {
    saved, draft, jsonText, jsonError, saving, error, pending, preview, dirty,
    update, updateJson, save, discard, onApplied, onDenied,
  };
}
