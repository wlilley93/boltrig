import { useCallback, useEffect, useMemo, useState } from "react";

import { api } from "../../api/client";
import type { ConfigRevisionSummary, InvokeResult } from "../../api/types";
import { apiReason, errText } from "../shared";
import {
  ADMIN_SECTIONS,
  fromFormValue,
  stableKey,
  toFormValue,
} from "./sections";
import type { AdminSection } from "./sections";
import { resultReason } from "./adminConstants";

export interface AdminPending {
  id: string;
  params: { section: string; value: unknown };
}

export interface AdminConfigState {
  sectionKey: string;
  setSectionKey: (key: string) => void;
  section: AdminSection;
  loaded: unknown;
  form: Record<string, unknown>;
  setForm: (form: Record<string, unknown>) => void;
  formValid: boolean;
  loading: boolean;
  loadError: string | null;
  denied: string | null;
  saving: boolean;
  saveError: string | null;
  saveMsg: string | null;
  pending: AdminPending | null;
  history: ConfigRevisionSummary[];
  historyError: string | null;
  baseline: Record<string, unknown>;
  dirty: boolean;
  loadHistory: (name: string) => Promise<void>;
  loadSection: (sec: AdminSection) => Promise<void>;
  save: () => Promise<void>;
  discard: () => void;
  rollback: (revId: number) => Promise<void>;
  onValidity: (valid: boolean) => void;
  onPendingApplied: (result: InvokeResult) => void;
  onPendingDenied: (reason: string) => void;
}

export function useAdminConfig(): AdminConfigState {
  const [sectionKey, setSectionKey] = useState<string>(ADMIN_SECTIONS[0].key);
  const section: AdminSection = useMemo(
    () => ADMIN_SECTIONS.find((s) => s.key === sectionKey) ?? ADMIN_SECTIONS[0],
    [sectionKey],
  );

  const [loaded, setLoaded] = useState<unknown>(null);
  const [form, setForm] = useState<Record<string, unknown>>({});
  const [formValid, setFormValid] = useState(true);

  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [denied, setDenied] = useState<string | null>(null);

  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveMsg, setSaveMsg] = useState<string | null>(null);
  const [pending, setPending] = useState<AdminPending | null>(null);

  const [history, setHistory] = useState<ConfigRevisionSummary[]>([]);
  const [historyError, setHistoryError] = useState<string | null>(null);

  const baseline = useMemo(() => toFormValue(section, loaded), [section, loaded]);
  const dirty = stableKey(form) !== stableKey(baseline);

  const loadHistory = useCallback(async (name: string) => {
    setHistoryError(null);
    try {
      const res = await api.configHistory(name);
      if (res.error) {
        setHistoryError(res.error);
        setHistory([]);
      } else {
        setHistory(res.revisions ?? []);
      }
    } catch (err) {
      setHistoryError(errText(err));
    }
  }, []);

  const loadSection = useCallback(
    async (sec: AdminSection) => {
      setLoading(true);
      setLoadError(null);
      setDenied(null);
      setSaveMsg(null);
      setSaveError(null);
      setPending(null);
      try {
        const res = await api.getConfig(sec.key);
        if (res.status === "denied" || res.error) {
          setDenied(res.reason ?? res.error ?? "admin_forbidden");
          setLoaded(null);
          setForm({});
        } else {
          const value = res.value ?? (sec.list ? [] : {});
          setLoaded(value);
          setForm(toFormValue(sec, value));
        }
      } catch (err) {
        setLoadError(errText(err));
      } finally {
        setLoading(false);
      }
      void loadHistory(sec.key);
    },
    [loadHistory],
  );

  useEffect(() => {
    void loadSection(section);
  }, [section, loadSection]);

  async function save() {
    if (!dirty || !formValid) return;
    const params = { section: section.key, value: fromFormValue(section, form) };
    setSaving(true);
    setSaveError(null);
    setSaveMsg(null);
    try {
      const result = await api.invoke({
        noun: "control",
        verb: "control.config.upsert",
        params,
      });
      if (result.status === "pending_human") {
        setPending({ id: result.hitl_request_id, params });
        return;
      }
      const reason = resultReason(result);
      if (reason) {
        setSaveError(reason);
        return;
      }
      setLoaded(params.value);
      setSaveMsg("Saved.");
      void loadHistory(section.key);
    } catch (err) {
      setSaveError(apiReason(err));
    } finally {
      setSaving(false);
    }
  }

  function discard() {
    setForm(toFormValue(section, loaded));
    setSaveError(null);
    setSaveMsg(null);
  }

  async function rollback(revId: number) {
    setSaveError(null);
    setSaveMsg(null);
    const res = await api.configRollback(section.key, { revision_id: revId });
    if (res.status !== "ok") {
      throw new Error(res.reason ?? "rollback rejected");
    }
    const value = res.value ?? (section.list ? [] : {});
    setLoaded(value);
    setForm(toFormValue(section, value));
    setSaveMsg(`Rolled back to revision ${revId}.`);
    void loadHistory(section.key);
  }

  const onValidity = useCallback((valid: boolean) => setFormValid(valid), []);

  function onPendingApplied(result: InvokeResult) {
    if (!pending) return;
    const reason = resultReason(result);
    if (reason) {
      setSaveError(reason);
      return;
    }
    setLoaded(pending.params.value);
    setSaveMsg("Approved and applied.");
    setPending(null);
    void loadHistory(section.key);
  }

  function onPendingDenied(reason: string) {
    setSaveError(reason);
  }

  return {
    sectionKey, setSectionKey, section, loaded, form, setForm, formValid,
    loading, loadError, denied, saving, saveError, saveMsg, pending,
    history, historyError, baseline, dirty, loadHistory, loadSection,
    save, discard, rollback, onValidity, onPendingApplied, onPendingDenied,
  };
}
