// Round Three admin console (Epic ADM). The manifest stays the source of truth:
// this surface edits a section's JSON, records every Save as a revision, lists
// history with per-revision Rollback, exports a re-importable manifest, and
// shows credential REFERENCES only (never secret values, US-ADM-03). The server
// gates writes to author/admin roles; a 403 renders as a denial here.

import { useEffect, useState } from "react";

import { api } from "../api/client";
import type {
  ConfigRevisionSummary,
  CredentialRef,
} from "../api/types";
import { useIdentity } from "../identity";
import { CodeBlock, errText, prettyJson } from "./shared";
import { PageIntro, Select } from "./ux";

// Each manifest section + a one-line plain-language description, so a section
// picker is never a list of cryptic keys.
const SECTION_INFO: ReadonlyArray<{ key: string; label: string; blurb: string }> = [
  { key: "privacy", label: "Privacy", blurb: "Data handling, retention and redaction." },
  { key: "network", label: "Network", blurb: "Outbound network policy and egress rules." },
  { key: "hitl", label: "Approvals (HITL)", blurb: "When actions pause for a human to approve." },
  { key: "models", label: "Models", blurb: "Which AI models are available and how requests route." },
  { key: "notifications", label: "Notifications", blurb: "Default notification channels and events." },
  { key: "personal_agents", label: "Personal agents", blurb: "Defaults for users' personal agents." },
  { key: "evaluation", label: "Evaluation", blurb: "Configuration for the eval harness." },
  { key: "memory", label: "Memory", blurb: "The memory subsystem: engine, scopes and residency." },
];
const SECTIONS: ReadonlyArray<string> = SECTION_INFO.map((s) => s.key);
const SECTION_OPTIONS = SECTION_INFO.map((s) => ({ value: s.key, label: s.label }));

const ADMIN_ROLES: ReadonlySet<string> = new Set(["org-admin"]);

export function AdminPanel() {
  const identity = useIdentity();
  const isAdmin = ADMIN_ROLES.has(identity.role);

  const [section, setSection] = useState<string>(SECTIONS[0]);
  const [editor, setEditor] = useState<string>("");
  const [loadError, setLoadError] = useState<string | null>(null);
  const [denied, setDenied] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const [saveBusy, setSaveBusy] = useState(false);
  const [saveMsg, setSaveMsg] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);

  const [history, setHistory] = useState<ConfigRevisionSummary[]>([]);
  const [historyError, setHistoryError] = useState<string | null>(null);

  const [exported, setExported] = useState<unknown>(null);
  const [exportError, setExportError] = useState<string | null>(null);

  const [creds, setCreds] = useState<CredentialRef[] | null>(null);
  const [credsError, setCredsError] = useState<string | null>(null);

  async function loadSection(name: string) {
    setLoading(true);
    setLoadError(null);
    setDenied(null);
    setSaveMsg(null);
    setSaveError(null);
    try {
      const res = await api.getConfig(name);
      if (res.status === "denied" || res.error) {
        setDenied(res.reason ?? res.error ?? "admin_forbidden");
        setEditor("");
      } else {
        // value may be null (unset section); pre-fill an empty object so a first
        // Save is well-formed.
        setEditor(prettyJson(res.value ?? {}));
      }
    } catch (err) {
      setLoadError(errText(err));
    } finally {
      setLoading(false);
    }
    void loadHistory(name);
  }

  async function loadHistory(name: string) {
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
  }

  // Load whenever the selected section changes.
  useEffect(() => {
    void loadSection(section);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [section]);

  async function save() {
    let value: unknown;
    try {
      value = JSON.parse(editor || "{}");
    } catch {
      setSaveError("Editor content is not valid JSON.");
      return;
    }
    setSaveBusy(true);
    setSaveError(null);
    setSaveMsg(null);
    try {
      const res = await api.putConfig(section, { value });
      if (res.status === "ok") {
        setSaveMsg(`Saved revision ${res.revision ?? ""}.`);
        void loadHistory(section);
      } else {
        setSaveError(res.reason ?? "save rejected");
      }
    } catch (err) {
      setSaveError(errText(err));
    } finally {
      setSaveBusy(false);
    }
  }

  async function rollback(revId: number) {
    if (
      !window.confirm(
        `Roll back "${section}" to revision #${revId}? This changes live configuration and records a new revision.`,
      )
    ) {
      return;
    }
    setSaveError(null);
    setSaveMsg(null);
    try {
      const res = await api.configRollback(section, { revision_id: revId });
      if (res.status === "ok") {
        setEditor(prettyJson(res.value ?? {}));
        setSaveMsg(`Rolled back to revision ${revId}.`);
        void loadHistory(section);
      } else {
        setSaveError(res.reason ?? "rollback rejected");
      }
    } catch (err) {
      setSaveError(errText(err));
    }
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

  const sectionBlurb = SECTION_INFO.find((s) => s.key === section)?.blurb;

  return (
    <section className="panel">
      <PageIntro
        title="Admin"
        lead="Edit your organisation's configuration."
        how="Pick a section, change its settings, and Save - every Save is recorded as a revision you can roll back to. Secrets are never shown, only referenced."
        actions={
          <>
            <div style={{ minWidth: 180 }}>
              <Select
                value={section}
                ariaLabel="Manifest section"
                onChange={setSection}
                options={SECTION_OPTIONS}
              />
            </div>
            <button className="btn" onClick={() => loadSection(section)}>
              Reload
            </button>
          </>
        }
      />

      {!isAdmin && (
        <p className="notice warn">
          The admin console is intended for org-admin. This identity (role:{" "}
          <code>{identity.role}</code>) may be rejected by the server with 403.
        </p>
      )}

      <div className="cols">
        <div className="stack">
          <div className="form">
            <div className="form__title">
              {SECTION_INFO.find((s) => s.key === section)?.label ?? section}
            </div>
            {sectionBlurb && <p className="ux-hint">{sectionBlurb}</p>}
            {loading && <p className="muted">Loading...</p>}
            {loadError && (
              <p className="error">Could not load: {loadError}</p>
            )}
            {denied ? (
              <p className="error">denied: {denied}</p>
            ) : (
              <>
                <label className="field">
                  <span>Settings (JSON)</span>
                  <textarea
                    className="code"
                    value={editor}
                    onChange={(e) => setEditor(e.target.value)}
                  />
                </label>
                <p className="ux-hint">
                  This is the section's live configuration. Saving changes it
                  immediately and records a revision.
                </p>
                <div className="form__actions">
                  <button
                    className="btn btn--primary"
                    disabled={saveBusy}
                    onClick={save}
                  >
                    {saveBusy ? "Saving..." : "Save"}
                  </button>
                  {saveMsg && <span className="ok">{saveMsg}</span>}
                  {saveError && <span className="error">{saveError}</span>}
                </div>
              </>
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
                      <code className="tag" title="Credential reference - the secret value is held server-side.">
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
            <button className="btn" onClick={() => loadHistory(section)}>
              Refresh
            </button>
          </div>
          <div className="list-card__body">
            {historyError && (
              <p className="error">Failed to load: {historyError}</p>
            )}
            {!historyError && history.length === 0 && (
              <p className="muted">No revisions for this section.</p>
            )}
            {history.map((r) => (
              <div className="row-line" key={r.id}>
                <div>
                  <code>#{r.id}</code>{" "}
                  <span className="muted">{r.version}</span>{" "}
                  {r.rolled_back && <span className="badge">rollback</span>}
                  <div className="muted">
                    {r.actor} - {r.created_at}
                  </div>
                </div>
                <button className="btn btn--danger" onClick={() => rollback(r.id)}>
                  Rollback
                </button>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
