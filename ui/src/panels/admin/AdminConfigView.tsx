import type { ReactNode } from "react";

import type { ConfigRevisionSummary, CredentialRef, InvokeResult } from "../../api/types";
import { CodeBlock } from "../shared";
import { InfoCallout } from "../ux";
import { SchemaFormV2 } from "../uxForm";
import { ArmConfirm, ByChat, DiffView, Disclosure, PendingHumanCard, SaveBar } from "../uxFlow";
import type { AdminSection } from "./sections";
import type { AdminPending } from "./useAdminConfig";
import type { AdminPanelState } from "./useAdminPanel";

function AdminConfigForm({
  section,
  loading,
  loadError,
  denied,
  form,
  setForm,
  formValid,
  onValidity,
  baseline,
  dirty,
  saveMsg,
  saveError,
  pending,
  saving,
  onSave,
  onDiscard,
  onApplied,
  onDenied,
  onReset,
}: {
  section: AdminSection;
  loading: boolean;
  loadError: string | null;
  denied: string | null;
  form: Record<string, unknown>;
  setForm: (form: Record<string, unknown>) => void;
  formValid: boolean;
  onValidity: (valid: boolean) => void;
  baseline: Record<string, unknown>;
  dirty: boolean;
  saveMsg: string | null;
  saveError: string | null;
  pending: AdminPending | null;
  saving: boolean;
  onSave: () => void;
  onDiscard: () => void;
  onApplied: (result: InvokeResult) => void;
  onDenied: (reason: string) => void;
  onReset: () => void;
}): ReactNode {
  return (
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

            <ByChat phrase={`Update the ${section.label} configuration to match this draft.`} />

            {saveMsg && <p className="ok">{saveMsg}</p>}
            {saveError && <InfoCallout tone="warn">{saveError}</InfoCallout>}

            {pending && (
              <PendingHumanCard
                hitlRequestId={pending.id}
                noun="control"
                verb={pending.verb}
                sentParams={pending.params}
                onApplied={onApplied}
                onDenied={onDenied}
                onReset={onReset}
              />
            )}

            <SaveBar
              dirty={dirty && pending === null}
              saving={saving}
              governed
              label={
                <>
                  Unsaved changes to <code>{section.label}</code>
                </>
              }
              saveLabel="Request change"
              onSave={onSave}
              onDiscard={onDiscard}
            />
          </>
        )
      )}
    </div>
  );
}

function AdminManifestExport({
  exported,
  exportError,
  onExport,
}: {
  exported: unknown;
  exportError: string | null;
  onExport: () => void;
}): ReactNode {
  return (
    <div className="form">
      <div className="form__title">Manifest export</div>
      <p className="muted">
        Exports a manifest equivalent to the live configuration (round-trip
        re-import).
      </p>
      <div className="form__actions">
        <button className="btn" onClick={onExport}>
          Export manifest
        </button>
        {exportError && <span className="error">{exportError}</span>}
      </div>
      {exported !== null && <CodeBlock value={exported} />}
    </div>
  );
}

function AdminCredentialsPanel({
  creds,
  credsError,
  onLoadCreds,
}: {
  creds: CredentialRef[] | null;
  credsError: string | null;
  onLoadCreds: () => void;
}): ReactNode {
  return (
    <div className="form">
      <div className="form__title">Credential references</div>
      <p className="muted">
        References only - secret values are never returned (US-ADM-03).
      </p>
      <div className="form__actions">
        <button className="btn" onClick={onLoadCreds}>
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
  );
}

function AdminRevisionHistory({
  history,
  historyError,
  section,
  onRefresh,
  onRollback,
  pending,
}: {
  history: ConfigRevisionSummary[];
  historyError: string | null;
  section: AdminSection;
  onRefresh: () => void;
  onRollback: (revId: number) => Promise<void>;
  pending: boolean;
}): ReactNode {
  return (
    <div className="list-card">
      <div className="list-card__head">
        <h3>Revision history</h3>
        <button className="btn" onClick={onRefresh}>
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
              disabled={pending}
              onConfirm={() => onRollback(r.id)}
            />
          </div>
        ))}
      </div>
    </div>
  );
}

export function AdminConfigView({ a }: { a: AdminPanelState }): ReactNode {
  return (
    <div className="cols">
      <div className="stack">
        <AdminConfigForm
          section={a.section}
          loading={a.loading}
          loadError={a.loadError}
          denied={a.denied}
          form={a.form}
          setForm={a.setForm}
          formValid={a.formValid}
          onValidity={a.onValidity}
          baseline={a.baseline}
          dirty={a.dirty}
          saveMsg={a.saveMsg}
          saveError={a.saveError}
          pending={a.pending}
          saving={a.saving}
          onSave={() => void a.save()}
          onDiscard={a.discard}
          onApplied={a.onPendingApplied}
          onDenied={a.onPendingDenied}
          onReset={a.onPendingReset}
        />
        <AdminManifestExport
          exported={a.exported}
          exportError={a.exportError}
          onExport={a.exportManifest}
        />
        <AdminCredentialsPanel
          creds={a.creds}
          credsError={a.credsError}
          onLoadCreds={a.loadCredentials}
        />
      </div>
      <AdminRevisionHistory
        history={a.history}
        historyError={a.historyError}
        section={a.section}
        onRefresh={() => void a.loadHistory(a.section.key)}
        onRollback={a.rollback}
        pending={a.pending !== null}
      />
    </div>
  );
}
