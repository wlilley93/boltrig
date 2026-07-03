// The admin console (Epic ADM, Beat 5 retrofit). The manifest stays the source
// of truth: this surface edits a section through TYPED controls (SchemaFormV2 +
// the form register), never a raw JSON blob. Two rails changed from the round
// three console:
//   1. Every WRITE goes through the governed control.config.upsert verb (the
//      same request-change/approval path Agents and Automations use): the first
//      submit 202s, a DiffView shows old vs new, and a PendingHumanCard applies
//      the change on approval. Direct config PUT is no longer used here.
//   2. Fail-closed validation: an unparseable per-field JSON escape hatch blocks
//      Save (SchemaFormV2.onValidity), and a section schema is an allowlist so a
//      partial edit preserves operator-only keys (e.g. OIDC wiring) untouched.
// Reads (revision history, manifest export, credential references) are
// unchanged; rollback now uses in-frame ArmConfirm instead of window.confirm.
// The server gates writes to author/admin roles; a 403 renders as a denial.

import { useCallback, useEffect, useMemo, useState } from "react";

import { api } from "../api/client";
import type {
  ConfigRevisionSummary,
  CredentialRef,
  InvokeResult,
} from "../api/types";
import { useIdentity } from "../identity";
import {
  ADMIN_SECTIONS,
  ADMIN_SECTION_OPTIONS,
  fromFormValue,
  stableKey,
  toFormValue,
} from "./admin/sections";
import type { AdminSection } from "./admin/sections";
import { apiReason, CodeBlock, errText } from "./shared";
import { SchemaFormV2, SegmentedV2 } from "./uxForm";
import {
  ArmConfirm,
  DiffView,
  Disclosure,
  PendingHumanCard,
  SaveBar,
} from "./uxFlow";
import { InfoCallout, PageIntro, Select } from "./ux";
import { TenancyAdmin } from "./admin/TenancyAdmin";

// The admin console has two views: the manifest CONFIGURATION editor (governed
// through control.config.upsert) and ORGANISATION administration (org policy,
// workspaces, members, AI keys, over the REST tenancy surface). One console, two
// views - not a parallel settings system.
const ADMIN_VIEWS = [
  { value: "config", label: "Configuration" },
  { value: "organisation", label: "Organisation & workspaces" },
];

const ADMIN_ROLES: ReadonlySet<string> = new Set(["org-admin"]);

// Config amendments are high-consequence: the first upsert always pauses for a
// human, and denied/error map to a faithful message.
function resultReason(result: InvokeResult): string | null {
  if (result.status === "denied" || result.status === "error") return result.reason;
  return null;
}

export function AdminPanel() {
  const identity = useIdentity();
  const isAdmin = ADMIN_ROLES.has(identity.role);

  // Which admin view is showing: the manifest config editor or the org/workspace
  // administration surface (both server-gated to org-admin).
  const [view, setView] = useState<string>("config");

  const [sectionKey, setSectionKey] = useState<string>(ADMIN_SECTIONS[0].key);
  const section: AdminSection = useMemo(
    () => ADMIN_SECTIONS.find((s) => s.key === sectionKey) ?? ADMIN_SECTIONS[0],
    [sectionKey],
  );

  // loaded = the section value as the server holds it; form = the object
  // SchemaFormV2 edits (list sections wrap the array under `items`).
  const [loaded, setLoaded] = useState<unknown>(null);
  const [form, setForm] = useState<Record<string, unknown>>({});
  const [formValid, setFormValid] = useState(true);

  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [denied, setDenied] = useState<string | null>(null);

  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveMsg, setSaveMsg] = useState<string | null>(null);
  const [pending, setPending] = useState<{
    id: string;
    params: { section: string; value: unknown };
  } | null>(null);

  const [history, setHistory] = useState<ConfigRevisionSummary[]>([]);
  const [historyError, setHistoryError] = useState<string | null>(null);

  const [exported, setExported] = useState<unknown>(null);
  const [exportError, setExportError] = useState<string | null>(null);

  const [creds, setCreds] = useState<CredentialRef[] | null>(null);
  const [credsError, setCredsError] = useState<string | null>(null);

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

  // Reload whenever the selected section changes.
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
      // ok / degraded: the change applied without a pause (e.g. not a blocking
      // verb for this tenant). Adopt the sent value as the new baseline.
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

  async function exportManifest() {
    setExportError(null);
    setExported(null);
    try {
      const res = await api.configExport();
      if (res.error) setExportError(res.error);
      else setExported(res.manifest ?? {});
    } catch (err) {
      setExportError(errText(err));
    }
  }

  async function loadCredentials() {
    setCredsError(null);
    setCreds(null);
    try {
      const res = await api.adminCredentials();
      if (res.error) setCredsError(res.error);
      else setCreds(res.credentials ?? []);
    } catch (err) {
      setCredsError(errText(err));
    }
  }

  const onValidity = useCallback((valid: boolean) => setFormValid(valid), []);

  return (
    <section className="panel">
      <PageIntro
        title="Admin"
        lead="Edit your organisation's configuration through typed, governed controls."
        how="Pick a section and change its settings. Saving requests a governed change - a high-consequence config amendment pauses for a human approval, then records a revision you can roll back to. Secrets are never shown, only referenced."
        actions={
          view === "config" ? (
            <>
              <div style={{ minWidth: 200 }}>
                <Select
                  value={sectionKey}
                  ariaLabel="Manifest section"
                  onChange={setSectionKey}
                  options={ADMIN_SECTION_OPTIONS}
                />
              </div>
              <button className="btn" onClick={() => void loadSection(section)}>
                Reload
              </button>
            </>
          ) : undefined
        }
      />

      <div className="admin__viewtoggle">
        <SegmentedV2
          value={view}
          onChange={setView}
          options={ADMIN_VIEWS}
          ariaLabel="Admin console view"
        />
      </div>

      {!isAdmin && (
        <p className="notice warn">
          The admin console is intended for org-admin. This identity (role:{" "}
          <code>{identity.role}</code>) may be rejected by the server with 403.
        </p>
      )}

      {view === "organisation" && <TenancyAdmin />}

      {view === "config" && (
      <div className="cols">
        <div className="stack">
          <div className="form">
            <div className="form__title">{section.label}</div>
            <p className="ux-hint">{section.blurb}</p>
            {section.preserves && (
              <InfoCallout tone="info">{section.preserves}</InfoCallout>
            )}
            {loading && <p className="muted">Loading...</p>}
            {loadError && <p className="error">Could not load: {loadError}</p>}
            {denied ? (
              <p className="error">denied: {denied}</p>
            ) : (
              !loading && (
                <>
                  <SchemaFormV2
                    key={section.key}
                    schema={section.schema}
                    value={form}
                    onChange={setForm}
                    onValidity={onValidity}
                  />
                  {!formValid && (
                    <InfoCallout tone="warn">
                      Fix the highlighted JSON before requesting a change.
                    </InfoCallout>
                  )}

                  <Disclosure summary="Review changes" changedCount={dirty ? 1 : 0}>
                    <DiffView before={baseline} after={form} />
                  </Disclosure>

                  {saveMsg && <p className="ok">{saveMsg}</p>}
                  {saveError && <InfoCallout tone="warn">{saveError}</InfoCallout>}

                  {pending && (
                    <PendingHumanCard
                      hitlRequestId={pending.id}
                      noun="control"
                      verb="control.config.upsert"
                      sentParams={pending.params}
                      onApplied={(result) => {
                        const reason = resultReason(result);
                        if (reason) {
                          setSaveError(reason);
                          return;
                        }
                        setLoaded(pending.params.value);
                        setSaveMsg("Approved and applied.");
                        setPending(null);
                        void loadHistory(section.key);
                      }}
                      onDenied={(reason) => setSaveError(reason)}
                    />
                  )}

                  <SaveBar
                    dirty={dirty}
                    saving={saving}
                    governed
                    label={
                      <>
                        Unsaved changes to <code>{section.label}</code>
                      </>
                    }
                    saveLabel="Request change"
                    onSave={() => void save()}
                    onDiscard={discard}
                  />
                </>
              )
            )}
          </div>

          <div className="form">
            <div className="form__title">Manifest export</div>
            <p className="muted">
              Exports a manifest equivalent to the live configuration (round-trip
              re-import).
            </p>
            <div className="form__actions">
              <button className="btn" onClick={exportManifest}>
                Export manifest
              </button>
              {exportError && <span className="error">{exportError}</span>}
            </div>
            {exported !== null && <CodeBlock value={exported} />}
          </div>

          <div className="form">
            <div className="form__title">Credential references</div>
            <p className="muted">
              References only - secret values are never returned (US-ADM-03).
            </p>
            <div className="form__actions">
              <button className="btn" onClick={loadCredentials}>
                Load credentials
              </button>
              {credsError && <span className="error">{credsError}</span>}
            </div>
            {creds &&
              (creds.length === 0 ? (
                <p className="muted">No credential references.</p>
              ) : (
                <div className="stack">
                  {creds.map((c, i) => (
                    <div className="row-line" key={`${c.adapter}-${i}`}>
                      <span className="muted">{c.adapter ?? "unassigned"}</span>
                      <code
                        className="tag"
                        title="Credential reference - the secret value is held server-side."
                      >
                        {c.credential}
                      </code>
                    </div>
                  ))}
                </div>
              ))}
          </div>
        </div>

        <div className="list-card">
          <div className="list-card__head">
            <h3>Revision history</h3>
            <button className="btn" onClick={() => void loadHistory(section.key)}>
              Refresh
            </button>
          </div>
          <div className="list-card__body">
            {historyError && <p className="error">Failed to load: {historyError}</p>}
            {!historyError && history.length === 0 && (
              <p className="muted">No revisions for this section.</p>
            )}
            {history.map((r) => (
              <div className="row-line" key={r.id}>
                <div>
                  <code>#{r.id}</code> <span className="muted">{r.version}</span>{" "}
                  {r.rolled_back && <span className="badge">rollback</span>}
                  <div className="muted">
                    {r.actor} - {r.created_at}
                  </div>
                </div>
                <ArmConfirm
                  label="Rollback"
                  armLabel={
                    <>
                      Roll back <code>{section.label}</code> to revision #{r.id}?
                      This changes live configuration and records a new revision.
                    </>
                  }
                  confirmLabel="Confirm rollback"
                  tone="danger"
                  busyLabel="Rolling back..."
                  onConfirm={() => rollback(r.id)}
                />
              </div>
            ))}
          </div>
        </div>
      </div>
      )}
    </section>
  );
}
